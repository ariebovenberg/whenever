use crate::common::*;
use crate::tz::tzif::{self, TZif};
use crate::OptionExt;
use ahash::AHashMap;
use pyo3_ffi::*;
use std::fs;
use std::path::Path;
use std::{collections::VecDeque, ptr::NonNull};

/// A manually reference-counted handle to a `TZif` object.
/// Since it's just a thin wrapper around a pointer, and
/// meant to be used in a single-threaded context, it's safe to share and copy
#[derive(Debug, Clone, Copy, Eq, PartialEq)]
pub struct TzRef {
    inner: NonNull<Inner>,
}

struct Inner {
    value: TZif,
    // For interior mutability. UnsafeCell is OK here because we're not sharing
    // it between threads.
    refcnt: std::cell::UnsafeCell<usize>,
}

impl TzRef {
    /// Creates a new `RcTZif` with a refcount of 1
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
    pub fn incref(&self) {
        unsafe {
            let refcnt = self.inner.as_ref().refcnt.get();
            *refcnt += 1;
        }
        // println!("Incremented refcount: {:?}", self.ref_count());
    }

    /// Decrement the reference count manually and return true if it drops to zero.
    #[inline]
    pub fn decref<'a, F>(&self, get_cache: F) -> bool
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
        // println!("Decremented refcount: {:?}", *refcnt);
        if refcnt == 0 {
            let cache = get_cache();
            // println!("Dropping TZif: {:?}", self.inner.as_ref().value.key);

            // Before dropping the data, we need to remove it from the cache.
            // Otherwise, the cache will keep a dangling pointer!
            // Note that we only need to remove it from the lookup table, not the LRU.
            // The LRU is a strong-reference cache, meaning anything in it
            // by definition has a reference count of at least 1.
            debug_assert!(cache.lru.contains(&self));
            cache.lookup.remove(&self.key);
            // Ok to drop the data now
            unsafe {
                drop(Box::from_raw(self.inner.as_ptr()));
            }
            return true;
        }
        false
    }

    pub fn value(&self) -> &TZif {
        // Safety:
        unsafe { &self.inner.as_ref().value }
    }

    /// Gets the current reference count (for debugging purposes).
    pub fn ref_count(&self) -> usize {
        unsafe { *self.inner.as_ref().refcnt.get() }
    }
}

impl std::ops::Deref for TzRef {
    type Target = TZif;

    fn deref(&self) -> &Self::Target {
        self.value()
    }
}

type TzID = String;

/// A cache for `TZif` objects, keyed by TZ ID.
/// It's designed to be used by the `ZonedDateTime` class,
/// and is based on the cache approach of zoneinfo in Python's standard library.
pub struct TZifCache {
    // "Ahash" works significantly faster than the standard hashing algorithm.
    // We don't need the cryptographic security of the standard algorithm,
    // since the keys are trusted (they are limited to valid zoneinfo keys).
    lookup: AHashMap<TzID, TzRef>,
    /// Keeps the most recently used entries alive, to prevent over-eager dropping.
    /// For example, if constantly creating and dropping ZonedDateTimes
    /// with a particular TZ ID, we don't want to keep reloading the same file.
    /// Thus, we keep the most recently used entries in the cache.
    lru: VecDeque<TzRef>,
}

const BASE_PATH: &str = "/usr/share/zoneinfo";
const LRU_CAPACITY: usize = 8;

/// A simple cache for zoneinfo files.
/// It's designed to be used by the ZonedDateTime class,
/// which only calls it from a single thread while holding the GIL.
/// This allows avoiding synchronization.
impl TZifCache {
    pub fn new() -> Self {
        Self {
            lookup: AHashMap::with_capacity(LRU_CAPACITY),
            lru: VecDeque::with_capacity(LRU_CAPACITY),
        }
    }
    /// BIG TODO: cleanup from cache after decref!
    /// Fetches a `TZif` for the given `tzid`.
    /// If not already cached, reads the file from the filesystem.
    pub(crate) fn get(&mut self, tzid_str: &str) -> Option<TzRef> {
        // println!("Getting TZif: {:?}", tzid_str);
        let handle = match self.lookup.get(tzid_str) {
            Some(&entry) => {
                // println!("Found TZif in cache: {:?}", tzid_str);
                // TODO does this make sense?
                self.touch_lru(entry);
                entry
            }
            // Not in cache: attempt to load and insert
            None => {
                let tzif = self.load_tzif(Path::new(BASE_PATH), tzid_str)?;
                // TODO: lru_cache here, with assumptions
                let entry = TzRef::new(tzif);
                let tz_id_str = tzid_str.to_string();
                self.lookup.insert(tz_id_str, entry);
                entry
            }
        };
        return Some(handle);
    }

    /// The `get` function, but with Python exception handling
    pub(crate) unsafe fn py_get(
        &mut self,
        tz_obj: *mut PyObject,
        exc_notfound: *mut PyObject,
    ) -> PyResult<TzRef> {
        self.get(tz_obj.to_str()?.ok_or_type_err("tz must be a string")?)
            .ok_or_else_raise(exc_notfound, || {
                format!("No time zone found with key {}", tz_obj.repr())
            })
    }

    /// Adds the given TZ ID to the front of the LRU cache.
    /// Removes the least recently used entry if the capacity is exceeded.
    fn touch_lru(&mut self, tzif: TzRef) {
        // println!("Touching LRU for TZif: {:?}", unsafe { tzif.as_ref() }.key);

        // Remove the pointer if it's already in the LRU
        if let Some(pos) = self.lru.iter().position(|&ptr| ptr == tzif) {
            self.lru.remove(pos);
        } else {
            // Only increment the refcount if it's not already in the LRU
            tzif.incref();
        }

        // Push the pointer to the back (most recently used)
        self.lru.push_back(tzif);

        // If the LRU exceeds capacity, remove the least recently used entry
        if self.lru.len() > LRU_CAPACITY {
            self.lru
                .pop_front()
                .unwrap() // Safe: We've just checked len()
                .decref(|| self);
        }
    }

    /// Join a TZ id path with a base path, assuming the TZ id is untrusted input.
    /// The base path is assumed to be a trusted directory
    fn load_tzif(&self, base: &Path, tzid: &str) -> Option<TZif> {
        // println!("Reading TZif from filesystem: {:?}", tzid);
        if !tzid.is_ascii()
            || tzid.contains("..")
            || tzid.contains("//")
            || tzid.contains('\0')
            || tzid.starts_with('/')
            || tzid.ends_with('/')
        {
            return None;
        }
        let fullpath = base.join(tzid).canonicalize().ok()?;
        tzif::parse(&fs::read(fullpath).ok()?, tzid).ok()
    }
}
