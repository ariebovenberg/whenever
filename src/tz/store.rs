use crate::{
    common::sync::{OncePyCell, SyncCell},
    py::*,
    tz::tzif::{TimeZone, is_valid_key},
};
use ahash::AHashMap;
use std::{
    collections::VecDeque,
    fs,
    path::{Path, PathBuf},
    sync::{Arc, RwLock, Weak},
};

/// Timezone cache.
/// In GIL-enabled builds, access is synchronized by the GIL.
/// In free-threaded builds, a mutex provides synchronization.
/// It is based on the cache approach of zoneinfo in Python's standard library.
#[derive(Debug)]
struct Cache {
    inner: SyncCell<CacheInner>,
}

impl Cache {
    fn new() -> Self {
        Self {
            inner: SyncCell::new(CacheInner {
                lru: VecDeque::with_capacity(LRU_CAPACITY),
                lookup: AHashMap::with_capacity(8),
            }),
        }
    }

    /// Get an entry from the cache, or insert it from the supplied function.
    /// Returns a strong `Arc` reference.
    /// The load function is called outside the lock to avoid holding it during I/O.
    fn get_or_insert_with<F>(&self, key: &str, load: F) -> PyResult<Option<Arc<TimeZone>>>
    where
        F: FnOnce() -> PyResult<Option<TimeZone>>,
    {
        // First check: attempt to upgrade the weak ref under the lock
        let cached = self.inner.with_mut(|CacheInner { lookup, lru }| {
            lookup.get(key).and_then(Weak::upgrade).inspect(|arc| {
                Self::promote_lru(arc, lru);
            })
        });
        if let Some(arc) = cached {
            return Ok(Some(arc));
        }

        // Cache miss: load outside the lock (may do file I/O)
        let Some(timezone) = load()? else {
            return Ok(None);
        };
        let loaded = Arc::new(timezone);

        // Re-acquire lock to insert. Another thread may have raced us.
        Ok(self.inner.with_mut(|CacheInner { lookup, lru }| {
            if let Some(arc) = lookup.get(key).and_then(Weak::upgrade) {
                // Another thread loaded it; use theirs
                Self::promote_lru(&arc, lru);
                return Some(arc);
            }
            // We're first (or the previous weak ref expired). Insert ours.
            lookup.insert(key.to_string(), Arc::downgrade(&loaded));
            Self::new_to_lru(Arc::clone(&loaded), lru);
            Some(loaded)
        }))
    }

    fn new_to_lru(tz: Arc<TimeZone>, lru: &mut Lru) {
        debug_assert!(tz.key.is_some());
        if lru.len() == LRU_CAPACITY {
            // Evict LRU entry; stale weak refs in lookup are cleaned up lazily
            lru.pop_back();
        }
        lru.push_front(tz);
    }

    fn promote_lru(tz: &Arc<TimeZone>, lru: &mut Lru) {
        match lru.iter().position(|ptr| Arc::ptr_eq(ptr, tz)) {
            Some(0) => {} // Already at the front
            Some(i) => {
                lru.remove(i);
                lru.push_front(Arc::clone(tz));
            }
            None => {
                Self::new_to_lru(Arc::clone(tz), lru);
            }
        }
    }

    fn clear_all(&self) {
        self.inner.with_mut(|CacheInner { lookup, lru }| {
            lookup.clear();
            lru.clear();
        });
    }

    fn clear_only(&self, keys: &[String]) {
        self.inner.with_mut(|CacheInner { lookup, lru }| {
            for k in keys {
                lookup.remove(k);
                lru.retain(|tz| tz.key.as_deref() != Some(k));
            }
        });
    }
}

type Lru = VecDeque<Arc<TimeZone>>;
type Lookup = AHashMap<String, Weak<TimeZone>>;

#[derive(Debug)]
struct CacheInner {
    // Weak references to timezones keyed by TZ ID.
    // Strong references are held by (1) the LRU and (2) ZonedDateTime objects (via Arc).    // Stale entries (where the Weak ref has expired) are cleaned up lazily on next access.
    //
    // "Ahash" works significantly faster than the standard hashing algorithm.
    // We don't need cryptographic security since keys are trusted (valid zoneinfo IDs).
    lookup: Lookup,
    // Keeps the most recently used entries alive to prevent over-eager dropping.
    //
    // For example, if ZonedDateTimes with a given TZ ID are constantly created and dropped,
    // the LRU prevents reloading the TZif file on every lookup.
    //
    // A VecDeque gives O(1) push/pop at both ends.
    lru: Lru,
}

const LRU_CAPACITY: usize = 8; // this value seems to work well for Python's zoneinfo

/// Access layer for timezone data and relevant metadata.
#[derive(Debug)]
pub(crate) struct TzStore {
    // The zoneinfo timezone cache.
    cache: Cache,
    // The path to the `tzdata` Python package contents, if any.
    // Lazily initialized on first timezone lookup.
    tzdata_path: OncePyCell<Option<PathBuf>>,
    // The paths to search for zoneinfo files.
    // Lazily initialized from Python's TZPATH on first use; can be overridden via set_paths().
    paths: OncePyCell<Vec<PathBuf>>,
    // Cached system timezone. Held behind an RwLock for safe concurrent access.
    // The Arc keeps the allocation alive even if the cache entry is evicted while being read.
    system_tz_cache: RwLock<Option<Arc<TimeZone>>>,
    // This reference is borrowed from the module, which outlives this store.
    exc_notfound: PyObj,
}

impl TzStore {
    pub(crate) fn new(exc_notfound: PyObj) -> Self {
        Self {
            cache: Cache::new(),
            tzdata_path: OncePyCell::new(get_tzdata_path),
            paths: OncePyCell::new(init_paths),
            system_tz_cache: RwLock::new(None),
            exc_notfound,
        }
    }

    /// Set the timezone search paths, overriding the lazily-initialized default.
    pub(crate) fn set_paths(&self, new_paths: Vec<PathBuf>) {
        self.paths.set(new_paths);
    }

    /// Fetches the timezone definition for the given IANA time zone ID.
    pub(crate) fn get(&self, key: &str) -> PyResult<Arc<TimeZone>> {
        self.cache
            .get_or_insert_with(key, || self.load_tzif(key))?
            .ok_or_else_raise(self.exc_notfound, || {
                format!("No time zone found with key {key}")
            })
    }

    /// The `get` function, but accepts a Python Object as the key.
    pub(crate) fn obj_get(&self, tz_obj: PyObj) -> PyResult<Arc<TimeZone>> {
        self.get(
            tz_obj
                .cast_allow_subclass::<PyStr>()
                .ok_or_type_err("tz must be a string")?
                .as_str()?,
        )
    }

    /// Retrieve the system timezone definition (cached for repeat calls).
    pub(crate) fn get_system_tz(&self) -> PyResult<Arc<TimeZone>> {
        // Fast path: clone the Arc under a read lock
        if let Some(arc) = self
            .system_tz_cache
            .read()
            .unwrap()
            .as_ref()
            .map(Arc::clone)
        {
            return Ok(arc);
        }
        self.reset_system_tz()
    }

    /// Reset the cached system timezone.
    pub(crate) fn reset_system_tz(&self) -> PyResult<Arc<TimeZone>> {
        let new_arc = self.determine_system_tz()?;
        *self.system_tz_cache.write().unwrap() = Some(Arc::clone(&new_arc));
        Ok(new_arc)
    }

    /// Clear the entire cache, dropping all entries.
    pub(crate) fn clear_all(&self) {
        self.cache.clear_all();
    }

    /// Clear specific entries from the cache.
    pub(crate) fn clear_only(&self, keys: &[String]) {
        self.cache.clear_only(keys);
    }

    /// Return the current TZPATH as a Python tuple of strings.
    /// Lazily initializes paths if needed.
    pub(crate) fn get_paths_as_pytuple(&self) -> PyReturn {
        let paths = self.paths.get()?;
        let tuple = PyTuple::with_len(paths.len() as _)?;
        for (i, p) in paths.iter().enumerate() {
            tuple.init_item(i as _, p.to_string_lossy().as_ref().to_py()?);
        }
        // SAFETY: PyTuple is a PyObj subtype
        Ok(unsafe { tuple.cast_unchecked() })
    }

    /// Load a TZif file by key, assuming the key is untrusted input.
    fn load_tzif(&self, raw_key: &str) -> PyResult<Option<TimeZone>> {
        let Some(key) = BenignKey::new(raw_key) else {
            return Ok(None);
        };
        self.load_tzif_from_tzpath(key)?
            .map_or_else(|| self.load_tzif_from_tzdata(key), |tz| Ok(Some(tz)))
    }

    /// Load a TZif from the TZPATH directory, assuming a benign TZ ID.
    /// Lazily initializes paths from Python if needed.
    fn load_tzif_from_tzpath(&self, key: BenignKey) -> PyResult<Option<TimeZone>> {
        let paths = self.paths.get()?;
        Ok(paths
            .iter()
            .find_map(|base| self.read_tzif_at_path(&base.join(key), Some(key))))
    }

    /// Load a TZif from the tzdata package, assuming a benign TZ ID.
    fn load_tzif_from_tzdata(&self, key: BenignKey) -> PyResult<Option<TimeZone>> {
        let tzdata_path = self.tzdata_path.get()?;
        Ok(tzdata_path
            .as_deref()
            .and_then(|base| self.read_tzif_at_path(&base.join(key), Some(key))))
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

    /// Determine the current system timezone, returning a strong Arc reference.
    fn determine_system_tz(&self) -> PyResult<Arc<TimeZone>> {
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
                .get_or_insert_with(tz_value, || self.load_tzif(tz_value))?
                .ok_or_else_raise(self.exc_notfound, || {
                    format!("No time zone found with key {tz_value}")
                }),
            // type 1: Path to a TZif file
            1 => {
                let path = PathBuf::from(tz_value);
                let tzif = self.read_tzif_at_path(&path, None).ok_or_else_raise(
                    self.exc_notfound,
                    || {
                        // TODO: better print?
                        format!("No time zone found at path {path:?}")
                    },
                )?;
                Ok(Arc::new(tzif))
            }
            // type 2: zoneinfo key OR posix TZ string (we're unsure which)
            2 => self
                .cache
                .get_or_insert_with(tz_value, || self.load_tzif(tz_value))?
                .or_else(|| TimeZone::parse_posix(tz_value).map(Arc::new))
                .ok_or_else_raise(self.exc_notfound, || {
                    format!("No time zone found with key or posix TZ string {tz_value}")
                }),
            _ => raise_type_err(ERR_MSG)?,
        }
    }
}

fn get_tzdata_path() -> PyResult<Option<PathBuf>> {
    let Some(tzdata) = import(c"tzdata.zoneinfo").catch(exc_import_error())? else {
        // ImportError: no tzdata installed
        return Ok(None);
    };
    let __path__ = tzdata.getattr(c"__path__")?;
    // __path__ is a list of paths. It will only have one element,
    // unless somebody is doing something strange.
    let py_str = __path__
        .getitem(*(0).to_py()?)?
        .cast_exact::<PyStr>()
        .ok_or_type_err("tzdata module path must be a string")?;
    Ok(Some(PathBuf::from(py_str.as_str()?)))
}

fn init_paths() -> PyResult<Vec<PathBuf>> {
    let py_paths = import(c"whenever._shared")?
        .getattr(c"_tzpath_from_env")?
        .call0()?;
    tuple_to_pathvec(*py_paths)
}

/// Convert a Python tuple of str to Vec<PathBuf>.
fn tuple_to_pathvec(obj: PyObj) -> PyResult<Vec<PathBuf>> {
    let tuple = obj
        .cast_exact::<PyTuple>()
        .ok_or_type_err("expected tuple of strings")?;
    let mut result = Vec::with_capacity(tuple.len() as _);
    for item in tuple.iter() {
        result.push(PathBuf::from(
            item.cast_allow_subclass::<PyStr>()
                .ok_or_type_err("path must be a string")?
                .as_str()?,
        ));
    }
    Ok(result)
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
