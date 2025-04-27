use crate::{
    common::*,
    tz::tzif::{self, is_valid_key, TZif},
    OptionExt,
};
use ahash::AHashMap;
use pyo3_ffi::*;
use std::{
    collections::VecDeque,
    fs,
    path::{Path, PathBuf},
    ptr::NonNull,
};

/// A manually reference-counted handle to a `TZif` object.
/// Since it's just a thin wrapper around a pointer, and
/// meant to be used in a single-threaded context, it's safe to share and copy
#[derive(Debug, Clone, Copy, Eq, PartialEq)]
pub(crate) struct TzRef {
    inner: NonNull<Inner>,
}

struct Inner {
    value: TZif,
    // For interior mutability. UnsafeCell is OK here because we're not sharing
    // it between threads.
    refcnt: std::cell::UnsafeCell<usize>,
}

impl TzRef {
    /// Creates a new instance with a refcount of 1
    fn new(value: TZif) -> Self {
        let inner = Box::new(Inner {
            refcnt: std::cell::UnsafeCell::new(1),
            value,
        });
        Self {
            inner: NonNull::new(Box::into_raw(inner)).unwrap(),
        }
    }

    /// Increments the reference count.
    pub(crate) fn incref(&self) {
        unsafe {
            let refcnt = self.inner.as_ref().refcnt.get();
            *refcnt += 1;
        }
    }

    /// Decrement the reference count manually and return true if it drops to zero.
    #[inline]
    pub(crate) fn decref<'a, F>(&self, get_cache: F) -> bool
    where
        // Passing the cache lazily ensures we only get it if we need it,
        // i.e. if the refcount drops to zero.
        F: FnOnce() -> &'a mut TZifCache,
    {
        let refcnt = unsafe {
            let refcnt = self.inner.as_ref().refcnt.get();
            *refcnt -= 1;
            *refcnt
        };
        if refcnt == 0 {
            let cache = get_cache();

            // Before dropping the data, we need to remove it from the cache.
            // Otherwise, the cache will keep a dangling pointer!
            // Note that we only need to remove it from the lookup table, not the LRU.
            // The LRU is a strong-reference cache, meaning anything in it
            // by definition has a reference count of at least 1.
            // Also, note that the key isn't guaranteed to be in the cache,
            // since intermediate cache clearings may have removed it already.
            cache.lookup.remove(&self.key);
            // Ok to drop the data now
            unsafe {
                drop(Box::from_raw(self.inner.as_ptr()));
            }
            return true;
        }
        false
    }

    /// Gets the current reference count (for debugging purposes).
    #[allow(dead_code)]
    pub(crate) fn ref_count(&self) -> usize {
        unsafe { *self.inner.as_ref().refcnt.get() }
    }
}

impl std::ops::Deref for TzRef {
    type Target = TZif;

    fn deref(&self) -> &Self::Target {
        unsafe { &self.inner.as_ref().value }
    }
}

/// A simple cache for zoneinfo files.
/// It's designed to be used by the ZonedDateTime class,
/// which only calls it from a single thread while holding the GIL.
/// This avoids the need for synchronization.
/// It is based on the cache approach of zoneinfo in Python's standard library.
#[derive(Debug)]
pub(crate) struct TZifCache {
    // Weak references to the `TZif` objects, keyed by TZ ID.
    // ZonedDateTime objects hold strong references to the `TZif` objects,
    // along with the cache's LRU.
    //
    // Choice of data structure:
    // "Ahash" works significantly faster than the standard hashing algorithm.
    // We don't need the cryptographic security of the standard algorithm,
    // since the keys are trusted (they are limited to valid zoneinfo keys).
    // Other alternatives that benchmarked *slower* are `BTreeMap`, gxhash, fxhash, and phf.
    //
    // Cleanup strategy:
    // Removal of 0-refcount entries is done by the `decref` method of the `TZRef` handle.
    lookup: AHashMap<String, TzRef>,
    // Keeps the most recently used entries alive, to prevent over-eager dropping.
    //
    // For example, if constantly creating and dropping ZonedDateTimes
    // with a particular TZ ID, we don't want to keep reloading the same file.
    // Thus, we keep the most recently used entries in the cache.
    //
    // Choice of data structure:
    // A VecDeque is great for push/popping from both ends, and is simple to use,
    // although a Vec wasn't much slower in benchmarks.
    lru: VecDeque<TzRef>,
    // The paths to search for zoneinfo files.
    pub(crate) paths: Vec<PathBuf>,
    // The path to the tzdata package contents, if any.
    tzdata_path: Option<PathBuf>,
}

const LRU_CAPACITY: usize = 8; // this value seems to work well for Python's zoneinfo

impl TZifCache {
    pub(crate) fn new(tzdata_path: Option<PathBuf>) -> Self {
        Self {
            lru: VecDeque::with_capacity(LRU_CAPACITY),
            lookup: AHashMap::with_capacity(8), // a reasonable default size
            tzdata_path,
            // Empty. The actual search paths are patched in at module import
            paths: Vec::with_capacity(4),
        }
    }

    /// Fetches a `TZif` for the given IANA time zone ID.
    /// If not already cached, reads the file from the filesystem.
    /// Returns a *borrowed* reference to the `TZif` object.
    /// Its reference count is *not* incremented.
    pub(crate) unsafe fn get(
        &mut self,
        tz_id: &str,
        exc_notfound: *mut PyObject,
    ) -> PyResult<TzRef> {
        Ok(match self.lookup.get(tz_id) {
            // Found in cache. Mark it as recently used
            Some(&entry) => {
                self.touch_lru(entry);
                entry
            }
            // Not in cache: attempt to load and insert
            None => {
                let entry =
                    TzRef::new(self.load_tzif(tz_id).ok_or_else_raise(exc_notfound, || {
                        format!("No time zone found with key {}", tz_id)
                    })?);
                self.new_to_lru(entry);
                self.lookup.insert(tz_id.to_string(), entry);
                entry
            }
        })
    }

    /// The `get` function, but accepts a Python Object as the key.
    pub(crate) unsafe fn obj_get(
        &mut self,
        tz_obj: *mut PyObject,
        exc_notfound: *mut PyObject,
    ) -> PyResult<TzRef> {
        self.get(
            tz_obj.to_str()?.ok_or_type_err("tz must be a string")?,
            exc_notfound,
        )
    }

    /// Insert a new entry into the LRU, assuming the caller ensures:
    /// - it's not already in the LRU.
    /// - the refcount has been incremented.
    fn new_to_lru(&mut self, tz: TzRef) {
        debug_assert!(!self.lru.contains(&tz));
        debug_assert!(tz.ref_count() > 0);
        // If the LRU exceeds capacity, remove the least recently used entry
        if self.lru.len() == LRU_CAPACITY {
            self.lru
                .pop_back()
                // Safe: we've just checked the length
                .unwrap()
                // Don't forget to decrement the refcount of dropped entries!
                .decref(|| self);
        }
        // Now add the new entry to the front
        self.lru.push_front(tz);
    }

    /// Register the given TZif was "used recently", moving it to the front of the LRU.
    fn touch_lru(&mut self, tz: TzRef) {
        match self.lru.iter().position(|&ptr| ptr == tz) {
            Some(0) => {} // Already at the front
            Some(i) => {
                // Move it to the front. Note we don't need to increment the refcount,
                // since it's already in the LRU.
                self.lru.remove(i);
                self.lru.push_front(tz);
            }
            None => {
                tz.incref(); // LRU needs a strong refence
                self.new_to_lru(tz);
            }
        }
    }

    /// Load a TZif file by key, assuming the key is untrusted input.
    fn load_tzif(&self, tzid: &str) -> Option<TZif> {
        if !is_valid_key(tzid) {
            return None;
        }
        self.load_tzif_from_tzpath(tzid)
            .or_else(|| self.load_tzif_from_tzdata(tzid))
    }

    /// Load a TZif from the TZPATH directory, assuming a benign TZ ID.
    fn load_tzif_from_tzpath(&self, tzid: &str) -> Option<TZif> {
        self.paths
            .iter()
            .find_map(|base| self.read_tzif_at_path(&base.join(tzid), tzid))
    }

    /// Load a TZif from the tzdata package, assuming a benign TZ ID.
    fn load_tzif_from_tzdata(&self, tzid: &str) -> Option<TZif> {
        self.tzdata_path
            .as_ref()
            .and_then(|base| self.read_tzif_at_path(&base.join(tzid), tzid))
    }

    /// Read a TZif file from the given path, returning None if it doesn't exist
    /// or otherwise cannot be read.
    fn read_tzif_at_path(&self, path: &Path, tzid: &str) -> Option<TZif> {
        if path.is_file() {
            fs::read(path).ok().and_then(|d| tzif::parse(&d, tzid).ok())
        } else {
            None
        }
    }

    /// Clear the cache, dropping all entries.
    pub(crate) fn clear_all(&mut self) {
        // Clear the LRU, dropping all entries
        let mut lru = std::mem::replace(&mut self.lru, VecDeque::with_capacity(LRU_CAPACITY));
        for tz in lru.drain(..) {
            // NOTE: this is a bit hairy, as we pass the cache while it's being cleared.
            // However, decreffing doesn't touch the LRU, so we should be fine.
            tz.decref(|| self);
        }
        self.lookup.clear();
    }

    /// Clear specific entries from the cache.
    pub(crate) fn clear_only(&mut self, keys: &[&str]) {
        for &k in keys {
            self.lookup.remove(k);
            if let Some(i) = self.lru.iter().position(|tz| tz.key == *k) {
                self.lru
                    .remove(i)
                    // Safe: we just checked the index
                    .unwrap()
                    // This technically tries removing it from the lookup again.
                    // Not a problem, just a tad wasteful.
                    .decref(|| self);
            };
        }
    }
}

impl Drop for TZifCache {
    /// Drop the cache, clearing all entries. This should only trigger during module unloading,
    /// and there should be no ZonedDateTime objects left.
    fn drop(&mut self) {
        // Drop all the entries in the LRU
        let mut lru = std::mem::take(&mut self.lru);
        for tz in lru.drain(..) {
            // NOTE: this is a bit hairy, as we pass the cache while it's being cleared.
            // However, decreffing doesn't touch the LRU, so we should be fine.
            tz.decref(|| self);
        }
        // By now, the lookup table should be empty (it contains only weak references)
        debug_assert!(self.lookup.is_empty());
    }
}
