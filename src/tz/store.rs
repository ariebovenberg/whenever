use crate::{
    py::*,
    tz::tzif::{TimeZone, is_valid_key},
};
use ahash::AHashMap;
use pyo3_ffi::*;
use std::{
    cell::UnsafeCell,
    collections::VecDeque,
    fs,
    ops::Deref,
    path::{Path, PathBuf},
    ptr::NonNull,
};

/// A manually reference-counted pointer to a timezone definition.
/// Since it's just a thin wrapper around a pointer, and
/// meant to be used in a single-threaded context, it's safe to share and copy
#[derive(Debug, Clone, Copy, Eq, PartialEq)]
pub(crate) struct TzPtr {
    inner: NonNull<Inner>,
}

struct Inner {
    value: TimeZone,
    refcnt: UnsafeCell<usize>,
}

impl TzPtr {
    /// Creates a new instance with specified refcount.
    fn new(value: TimeZone) -> Self {
        let inner = Box::new(Inner {
            // We start with refcount of 2:
            // - one to share outside of the tzstore
            // - one to keep the pointer alive in the LRU
            refcnt: UnsafeCell::new(2),
            value,
        });
        Self {
            inner: NonNull::new(Box::into_raw(inner)).unwrap(),
        }
    }

    /// Create a new handle that shares ownership of the same pointer.
    pub(crate) fn newref<'a>(self) -> TzHandle<'a> {
        TzHandle::new_nonunique(self)
    }

    /// Decrement the reference count and clean up if it reaches zero.
    /// Note the store is passed as a closure,
    /// so it doesn't need to be fetched until we actually need it.
    pub(crate) fn decref_with_cleanup<'a>(self, get_store: impl FnOnce() -> &'a TzStore) {
        if self.decref() == 0 {
            if let Some(key) = self.key.as_ref() {
                // If we have a key, we need to remove it from the store
                // This is necessary to prevent memory leaks
                get_store().remove_key(key);
            }
            // SAFETY: we are the last strong reference, so it's safe to drop it
            unsafe { self.drop_in_place() };
        }
    }

    /// Determine if two timezone pointers point to the same timezone.
    /// Two different pointers may point to the same timezone data,
    /// for example after cache clearing and reloading.
    pub(crate) fn is_same_tz(self, other: TzPtr) -> bool {
        // The first check is crucial in avoiding unnecessary value comparisons
        // in the common case where pointers are unique.
        self == other || self.deref() == other.deref()
    }

    fn decref(&self) -> usize {
        unsafe {
            let refcnt = self.inner.as_ref().refcnt.get();
            *refcnt -= 1;
            *refcnt
        }
    }

    fn incref(&self) {
        unsafe {
            let refcnt = self.inner.as_ref().refcnt.get();
            *refcnt += 1;
        }
    }

    #[cfg(debug_assertions)]
    pub(crate) fn ref_count(&self) -> usize {
        unsafe { *self.inner.as_ref().refcnt.get() }
    }

    unsafe fn drop_in_place(&self) {
        // SAFETY: the pointer was allocated with Box::new,
        // and the caller should know when to drop it.
        drop(unsafe { Box::from_raw(self.inner.as_ptr()) });
    }
}

impl Deref for TzPtr {
    type Target = TimeZone;

    fn deref(&self) -> &Self::Target {
        unsafe { &self.inner.as_ref().value }
    }
}

/// A smart handle that manages the lifetime of a timezone pointer.
/// It automatically decrements the reference count when it goes out of scope.
///
/// There are two variants:
/// - a pointer that has a refcount of >=1, and thus requires a reference to the `TzStore`
///   to manage proper cleanup.
/// - a "non-unique" pointer that has a refcount of >= 2, will never trigger cleanup on Drop,
///   and therefore does not require a reference to the `TzStore`.
///   This is typically useful if copying from a Python object
///   that already holds a strong reference to the timezone.
#[derive(Debug)]
pub(crate) enum TzHandle<'a> {
    Ptr(TzPtr, &'a TzStore),
    NonUniquePtr(TzPtr),
}

impl TzHandle<'_> {
    /// Transfer ownership of the pointer to Python.
    /// Rust is no longer responsible for the memory (i.e. Drop)
    pub(crate) fn into_py(self) -> TzPtr {
        let ptr = self.as_ptr();
        std::mem::forget(self);
        ptr
    }

    fn as_ptr(&self) -> TzPtr {
        match *self {
            TzHandle::Ptr(ptr, _) => ptr,
            TzHandle::NonUniquePtr(ptr) => ptr,
        }
    }

    fn new_nonunique(ptr: TzPtr) -> Self {
        ptr.incref();
        Self::NonUniquePtr(ptr)
    }
}

impl Drop for TzHandle<'_> {
    fn drop(&mut self) {
        match self {
            TzHandle::Ptr(ptr, store) => ptr.decref_with_cleanup(|| store),
            TzHandle::NonUniquePtr(ptr) => {
                // Non-unique pointers do not require cleanup,
                // since they are never the last strong reference.
                ptr.decref();
            }
        }
    }
}

impl Deref for TzHandle<'_> {
    type Target = TzPtr;

    fn deref(&self) -> &Self::Target {
        match self {
            TzHandle::Ptr(ptr, _) => ptr,
            TzHandle::NonUniquePtr(ptr) => ptr,
        }
    }
}

/// Timezone cache meant for single-threaded use.
/// It's designed to be used by the ZonedDateTime class,
/// which only calls it from a single thread while holding the GIL.
/// This avoids the need for synchronization.
/// It is based on the cache approach of zoneinfo in Python's standard library.
#[derive(Debug)]
struct Cache {
    inner: UnsafeCell<CacheInner>,
}

impl Cache {
    fn new() -> Self {
        Self {
            inner: UnsafeCell::new(CacheInner {
                lru: VecDeque::with_capacity(LRU_CAPACITY),
                lookup: AHashMap::with_capacity(8), // a reasonable default size
            }),
        }
    }

    /// Get an entry from the cache, or insert it from the supplied function.
    /// Returns a strong reference.
    fn get_or_insert_with<F>(&self, key: &str, load: F) -> Option<TzPtr>
    where
        F: FnOnce() -> Option<TimeZone>,
    {
        // SAFETY: this is safe because we only access the cache from a single thread
        // while holding the GIL. The UnsafeCell is only used to allow mutable access
        // to the inner cache.
        let CacheInner { lookup, lru } = unsafe { self.inner.get().as_mut().unwrap() };

        match lookup.get(key) {
            // Found in cache. Mark it as recently used
            Some(&tz) => {
                tz.incref(); // Increment the refcount to ensure it's not dropped
                Self::promote_lru(tz, lru, lookup);
                Some(tz)
            }
            // Not found in cache. Load it and insert it into the cache
            None => load().map(TzPtr::new).inspect(|&tz| {
                Self::new_to_lru(tz, lru, lookup);
                lookup.insert(key.to_string(), tz);
            }),
        }
    }

    fn decref<F>(tz: TzPtr, cleanup: F)
    where
        F: FnOnce(),
    {
        if tz.decref() == 0 {
            cleanup();
            // SAFETY: this is safe because we are the last strong reference
            // to the timezone.
            unsafe {
                tz.drop_in_place();
            }
        }
    }

    fn remove_key(&self, key: &str) {
        let lookup = &mut unsafe { self.inner.get().as_mut().unwrap() }.lookup;
        lookup.remove(key);
    }

    fn new_to_lru(tz: TzPtr, lru: &mut Lru, lookup: &mut Lookup) {
        debug_assert!(!lru.contains(&tz));
        #[cfg(debug_assertions)]
        assert!(tz.ref_count() > 0);
        debug_assert!(tz.key.is_some());
        // If the LRU exceeds capacity, remove the least recently used entry
        if lru.len() == LRU_CAPACITY {
            // SAFETY: we know the LRU is not empty, so pop_back is safe
            let least_used = lru.pop_back().unwrap();
            Self::decref(least_used, || {
                lookup.remove(least_used.key.as_ref().expect("LRU entry always has a key"));
            });
        }
        // Now add the new entry to the front
        lru.push_front(tz);
    }

    /// Register the given timezone was "used recently", moving it to the front of the LRU.
    fn promote_lru(tz: TzPtr, lru: &mut Lru, lookup: &mut Lookup) {
        match lru.iter().position(|&ptr| ptr == tz) {
            Some(0) => {} // Already at the front
            Some(i) => {
                // Move it to the front. Note we don't need to increment the refcount,
                // since it's already in the LRU.
                lru.remove(i);
                lru.push_front(tz);
            }
            None => {
                tz.incref(); // LRU needs a strong reference
                Self::new_to_lru(tz, lru, lookup);
            }
        }
    }

    /// Clear the cache, dropping all entries.
    fn clear_all(&self) {
        let CacheInner { lookup, lru } = unsafe { self.inner.get().as_mut().unwrap() };

        // Clear all weak references. Note that strong references may still exist
        // both in the LRU and in ZonedDateTime objects.
        lookup.clear();

        // Clear the LRU
        let mut lru_old = std::mem::replace(lru, VecDeque::with_capacity(LRU_CAPACITY));
        for tz in lru_old.drain(..) {
            Self::decref(tz, || {
                // No cleanup needed: the lookup table is already cleared
            });
        }
    }

    /// Clear specific entries from the cache.
    fn clear_only(&self, keys: &[String]) {
        let CacheInner { lookup, lru } = unsafe { self.inner.get().as_mut().unwrap() };
        for k in keys {
            lookup.remove(k); // Always remove, regardless of refcount
            if let Some(i) = lru
                .iter()
                .position(|tz| tz.key.as_ref().expect("LRU entries always have a key") == k)
            {
                Self::decref(lru.remove(i).unwrap(), || {
                    // No cleanup needed: the lookup table is already cleared
                });
            };
        }
    }
}

impl Drop for Cache {
    /// Drop the cache, clearing all entries. This should only trigger during module unloading,
    /// and there should be no ZonedDateTime objects left.
    fn drop(&mut self) {
        let CacheInner { lookup, lru } = unsafe { self.inner.get().as_mut().unwrap() };
        // At this point, the only strong references should be in the LRU.
        let mut lru = std::mem::take(lru);
        for tz in lru.drain(..) {
            Self::decref(tz, || {
                // Remove the weak reference too
                lookup.remove(tz.key.as_ref().expect("LRU entries always have a key"));
            });
        }
        // By now, the lookup table should be empty (it contains only weak references)
        debug_assert!(lookup.is_empty());
    }
}

type Lru = VecDeque<TzPtr>;
type Lookup = AHashMap<String, TzPtr>;

struct CacheInner {
    // Weak references to the timezones, keyed by TZ ID.
    // String references are held by (1) the ZonedDateTime objects, and (2) the LRU
    //
    // Choice of data structure:
    // "Ahash" works significantly faster than the standard hashing algorithm.
    // We don't need the cryptographic security of the standard algorithm,
    // since the keys are trusted (they are limited to valid zoneinfo keys).
    // Other alternatives that benchmarked *slower* are `BTreeMap`, gxhash, fxhash, and phf.
    //
    // Cleanup strategy:
    // Removal of 0-refcount entries is done by the `decref` method of the tz pointer.
    lookup: Lookup,
    // Keeps the most recently used entries alive, to prevent over-eager dropping.
    //
    // For example, if constantly creating and dropping ZonedDateTimes
    // with a particular TZ ID, we don't want to keep reloading the same file.
    // Thus, we keep the most recently used entries in the cache.
    //
    // Choice of data structure:
    // A VecDeque is great for push/popping from both ends, and is simple to use,
    // although a Vec wasn't much slower in benchmarks.
    lru: Lru,
}

const LRU_CAPACITY: usize = 8; // this value seems to work well for Python's zoneinfo

/// Access layer for timezone data and relevant metadata.
#[derive(Debug)]
pub(crate) struct TzStore {
    // The zoneinfo timezone cache.
    cache: Cache,
    // The path to the `tzdata` Python package contents, if any.
    tzdata_path: Option<PathBuf>,
    // The paths to search for zoneinfo files. Patchable during runtime.
    pub(crate) paths: Vec<PathBuf>,
    // We cache the system timezone here, since it's expensive to determine.
    // The pointer represents a strong reference to a timezone.
    system_tz_cache: UnsafeCell<Option<TzPtr>>,
    // This reference is borrowed from the module, which outlives this store.
    exc_notfound: PyObj,
}

impl TzStore {
    pub(crate) fn new(exc_notfound: PyObj) -> PyResult<Self> {
        Ok(Self {
            cache: Cache::new(),
            tzdata_path: get_tzdata_path()?,
            // Empty. The actual search paths are patched in at module import
            // because this is determined in Python code.
            paths: Vec::with_capacity(4),
            system_tz_cache: UnsafeCell::new(None),
            exc_notfound,
        })
    }

    /// Fetches the timezone definition for the given IANA time zone ID.
    pub(crate) fn get(&self, key: &str) -> PyResult<TzHandle<'_>> {
        let ptr = self
            .cache
            .get_or_insert_with(key, || self.load_tzif(key))
            .ok_or_else_raise(self.exc_notfound.as_ptr(), || {
                format!("No time zone found with key {key}")
            })?;
        Ok(TzHandle::Ptr(ptr, self))
    }

    /// The `get` function, but accepts a Python Object as the key.
    pub(crate) fn obj_get(&self, tz_obj: PyObj) -> PyResult<TzHandle<'_>> {
        self.get(
            tz_obj
                .cast_allow_subclass::<PyStr>()
                .ok_or_type_err("tz must be a string")?
                .as_str()?,
        )
    }

    /// Retrieve the system timezone definition (cached for repeat calls).
    pub(crate) fn get_system_tz(&self) -> PyResult<TzHandle<'_>> {
        // Check if we already have the system timezone cached
        let ptr = match unsafe { *self.system_tz_cache.get() } {
            Some(p) => {
                p.incref();
                p
            }
            None => {
                let p = self.determine_system_tz()?;
                unsafe { *self.system_tz_cache.get() = Some(p) };
                p
            }
        };
        Ok(TzHandle::Ptr(ptr, self))
    }

    /// Reset the cached system timezone.
    pub(crate) fn reset_system_tz(&self) -> PyResult<()> {
        // Clear the cached system timezone
        let new_ptr = self.determine_system_tz()?;
        let old_ptr = unsafe { *self.system_tz_cache.get() };
        old_ptr.inspect(|ptr| {
            ptr.decref_with_cleanup(|| self);
        });
        unsafe { *self.system_tz_cache.get() = Some(new_ptr) }
        Ok(())
    }

    /// Clear the entire cache, dropping all entries.
    pub(crate) fn clear_all(&self) {
        self.cache.clear_all();
    }

    /// Clear specific entries from the cache.
    pub(crate) fn clear_only(&self, keys: &[String]) {
        self.cache.clear_only(keys);
    }

    /// Load a TZif file by key, assuming the key is untrusted input.
    fn load_tzif(&self, raw_key: &str) -> Option<TimeZone> {
        let key = BenignKey::new(raw_key)?;
        self.load_tzif_from_tzpath(key)
            .or_else(|| self.load_tzif_from_tzdata(key))
    }

    /// Load a TZif from the TZPATH directory, assuming a benign TZ ID.
    fn load_tzif_from_tzpath(&self, key: BenignKey) -> Option<TimeZone> {
        self.paths
            .iter()
            .find_map(|base| self.read_tzif_at_path(&base.join(key), Some(key)))
    }

    /// Load a TZif from the tzdata package, assuming a benign TZ ID.
    fn load_tzif_from_tzdata(&self, key: BenignKey) -> Option<TimeZone> {
        self.tzdata_path
            .as_ref()
            .and_then(|base| self.read_tzif_at_path(&base.join(key), Some(key)))
    }

    /// Read a TZif file from the given path, returning None if it doesn't exist
    /// or otherwise cannot be read.
    fn read_tzif_at_path(&self, path: &Path, key: Option<BenignKey>) -> Option<TimeZone> {
        if path.is_file() {
            fs::read(path)
                .ok()
                .and_then(|d| TimeZone::parse_tzif(&d, key.as_ref().map(|k| k.as_ref())).ok())
        } else {
            None
        }
    }

    /// Get a pointer to what is currently considered the system timezone.
    /// The pointer is already a strong reference.
    fn determine_system_tz(&self) -> PyResult<TzPtr> {
        const ERR_MSG: &str = "get_tz() gave unexpected result";
        let tz_tuple = import(c"whenever._tz.system")?
            .getattr(c"get_tz")?
            .call0()?
            .cast_exact::<PyTuple>()
            .ok_or_type_err(ERR_MSG)?;

        let mut items = tz_tuple.iter();
        // We expect a tuple of (int, str)
        let (Some(tz_type_obj), Some(tz_value_obj), None) = (
            items.next().and_then(|x| x.cast_exact::<PyInt>()),
            items.next().and_then(|x| x.cast_exact::<PyStr>()),
            items.next(),
        ) else {
            raise_type_err(ERR_MSG)?
        };
        let tz_type = tz_type_obj.to_long()?;
        let tz_value = tz_value_obj.as_str()?;

        match tz_type {
            // type 0: a zoneinfo key
            0 => self
                .cache
                .get_or_insert_with(tz_value, || self.load_tzif(tz_value))
                .ok_or_else_raise(self.exc_notfound.as_ptr(), || {
                    format!("No time zone found with key {tz_value}")
                }),
            // type 1: Path to a TZif file
            1 => {
                let path = PathBuf::from(tz_value);
                let tzif = self
                    .read_tzif_at_path(&path, None)
                    .ok_or_else_raise(self.exc_notfound.as_ptr(), || {
                        format!("No time zone found at path {path:?}")
                    })?;
                Ok(TzPtr::new(tzif))
            }
            // type 2: zoneinfo key OR posix TZ string (we're unsure which)
            2 => {
                self.cache
                    // Try to load it as a zoneinfo key first.
                    .get_or_insert_with(tz_value, || self.load_tzif(tz_value))
                    // If this fails, try to parse it as a posix TZ string.
                    .or_else(|| TimeZone::parse_posix(tz_value).map(TzPtr::new))
                    .ok_or_else_raise(self.exc_notfound.as_ptr(), || {
                        format!("No time zone found with key or posix TZ string {tz_value}")
                    })
            }
            _ => raise_type_err(ERR_MSG)?,
        }
    }

    fn remove_key(&self, key: &str) {
        self.cache.remove_key(key);
    }
}

impl Drop for TzStore {
    fn drop(&mut self) {
        // Clear the system timezone cache
        if let Some(ptr) = unsafe { *self.system_tz_cache.get() } {
            ptr.decref_with_cleanup(|| self);
            unsafe { *self.system_tz_cache.get() = None };
        }
        // The rest of the fields will be dropped automatically
    }
}

fn get_tzdata_path() -> PyResult<Option<PathBuf>> {
    Ok(Some(PathBuf::from({
        let __path__ = match import(c"tzdata.zoneinfo") {
            Ok(obj) => Ok(obj),
            // i.e. catch ImportError: no tzdata installed.
            _ if unsafe { PyErr_ExceptionMatches(PyExc_ImportError) } == 1 => {
                unsafe { PyErr_Clear() };
                return Ok(None);
            }
            e => e,
        }?
        .getattr(c"__path__")?;
        // __path__ is a list of paths. It will only have one element,
        // unless somebody is doing something strange.
        let py_str = __path__
            .getitem((0).to_py()?.borrow())?
            .cast_exact::<PyStr>()
            .ok_or_type_err("tzdata module path must be a string")?;

        py_str.as_str()?.to_owned()
    })))
}

/// Wrapper around a timezone key that has been validated to be "benign",
/// i.e. it only contains characters that are safe to use in file paths.
/// This is used to prevent directory traversal attacks when loading TZif files.
#[derive(Debug, Clone, Copy, Eq, PartialEq)]
struct BenignKey<'a>(&'a str);

impl<'a> BenignKey<'a> {
    fn new(key: &'a str) -> Option<Self> {
        is_valid_key(key).then_some(Self(key))
    }
}

impl AsRef<str> for BenignKey<'_> {
    fn as_ref(&self) -> &str {
        self.0
    }
}

impl AsRef<Path> for BenignKey<'_> {
    fn as_ref(&self) -> &Path {
        Path::new(self.0)
    }
}
