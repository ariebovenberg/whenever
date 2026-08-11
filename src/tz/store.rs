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
    fn get_or_insert_with<F>(&self, key: &NormalizedKey, load: F) -> PyResult<Option<Arc<TimeZone>>>
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
                Self::promote_lru(&arc, lru);
                return Some(arc);
            }
            // We're first (or the previous weak ref expired). Insert ours.
            lookup.insert(key.clone(), Arc::downgrade(&loaded));
            Self::new_to_lru(Arc::clone(&loaded), lru);
            Some(loaded)
        }))
    }

    fn new_to_lru(tz: Arc<TimeZone>, lru: &mut Lru) {
        debug_assert!(tz.key.is_some());
        if lru.len() == LRU_CAPACITY {
            lru.pop_back();
        }
        lru.push_front(tz);
    }

    fn promote_lru(tz: &Arc<TimeZone>, lru: &mut Lru) {
        match lru.iter().position(|ptr| Arc::ptr_eq(ptr, tz)) {
            Some(0) => {} // Already at the front
            Some(i) => {
                let t = lru.remove(i).unwrap(); // index validated by position
                lru.push_front(t);
            }
            None => {
                Self::new_to_lru(tz.clone(), lru);
            }
        }
    }

    fn clear_all(&self) {
        self.inner.with_mut(|CacheInner { lookup, lru }| {
            lookup.clear();
            lru.clear();
        });
    }

    fn clear_only(&self, keys: &[NormalizedKey]) {
        self.inner.with_mut(|CacheInner { lookup, lru }| {
            for key in keys {
                if let Some(tz) = lookup.remove(key).and_then(|weak| weak.upgrade()) {
                    // TimeZone stores the database spelling, not its normalized
                    // cache key, so identify the corresponding LRU entry by pointer.
                    lru.retain(|cached| !Arc::ptr_eq(cached, &tz));
                }
            }
        });
    }
}

type Lru = VecDeque<Arc<TimeZone>>;
type Lookup = AHashMap<NormalizedKey, Weak<TimeZone>>;

#[derive(Debug)]
struct CacheInner {
    // Weak references to timezones keyed by TZ ID.
    // Strong references are held by (1) the LRU and (2) ZonedDateTime objects.
    //
    // "Ahash" works significantly faster than the standard hashing algorithm.
    // We don't need cryptographic security since keys are validated
    // first to be zoneinfo IDs.
    lookup: Lookup,
    // Keeps the most recently used entries alive to prevent over-eager dropping.
    //
    // For example, if ZonedDateTimes with a given TZ ID are constantly created and dropped,
    // the LRU prevents reloading the TZif file on every lookup.
    //
    // A VecDeque gives O(1) push/pop at both ends.
    lru: Lru,
}

const LRU_CAPACITY: usize = 32;

/// Maps ASCII-lowercase entry names to their spelling on disk.
type DirectoryIndex = AHashMap<String, String>;
/// Maps scanned directory paths to their shared spelling indices.
type DirectoryEntries = AHashMap<PathBuf, Arc<DirectoryIndex>>;
/// Transient indices collected during one path resolution.
type DirectoryUpdates = Vec<(PathBuf, Arc<DirectoryIndex>)>;

#[derive(Debug)]
struct DirectoryCache {
    inner: SyncCell<DirectoryEntries>,
}

impl DirectoryCache {
    fn new() -> Self {
        Self {
            inner: SyncCell::new(AHashMap::new()),
        }
    }

    fn get(&self, path: &Path) -> Option<Arc<DirectoryIndex>> {
        self.inner.with(|i| i.get(path).cloned())
    }

    fn publish(&self, updates: DirectoryUpdates) {
        self.inner.with_mut(|i| {
            for (p, d) in updates {
                i.insert(p, d);
            }
        });
    }

    fn discard(&self, paths: &[PathBuf]) {
        self.inner.with_mut(|i| {
            for p in paths {
                i.remove(p);
            }
        });
    }

    fn clear(&self) {
        self.inner.with_mut(|i| i.clear());
    }

    fn resolve(&self, base: &Path, key: &NormalizedKey) -> Option<ResolvedPath> {
        match self.resolve_once(base, key) {
            ResolveAttempt::Found(r) => Some(r),
            ResolveAttempt::Missing => None,
            ResolveAttempt::Stale(paths) => {
                self.discard(&paths);
                match self.resolve_once(base, key) {
                    ResolveAttempt::Found(r) => Some(r),
                    ResolveAttempt::Missing | ResolveAttempt::Stale(_) => None,
                }
            }
        }
    }

    fn resolve_once(&self, base: &Path, key: &NormalizedKey) -> ResolveAttempt {
        let mut path = base.to_path_buf();
        let mut components = Vec::new();
        let mut updates = Vec::new();
        let mut cached_paths = Vec::new();

        for c in key.as_str().split('/') {
            let cached = self.get(&path);
            let (index, from_cache) = match cached {
                Some(i) if i.contains_key(c) => (i, true),
                _ => {
                    let Some(i) = scan_directory(&path) else {
                        return if cached_paths.is_empty() && updates.is_empty() {
                            ResolveAttempt::Missing
                        } else {
                            ResolveAttempt::Stale(cached_paths)
                        };
                    };
                    if !i.contains_key(c) {
                        return ResolveAttempt::Missing;
                    }
                    updates.push((path.clone(), Arc::clone(&i)));
                    (i, false)
                }
            };

            if from_cache {
                cached_paths.push(path.clone());
            }
            let n = index
                .get(c)
                .expect("the requested component was checked above")
                .clone();
            path.push(&n);
            components.push(n);
        }

        if path.is_file() {
            ResolveAttempt::Found(ResolvedPath {
                path,
                id: components.join("/"),
                updates,
            })
        } else if cached_paths.is_empty() && updates.is_empty() {
            ResolveAttempt::Missing
        } else {
            ResolveAttempt::Stale(cached_paths)
        }
    }

    #[cfg(test)]
    fn len(&self) -> usize {
        self.inner.with(|i| i.len())
    }
}

fn scan_directory(path: &Path) -> Option<Arc<DirectoryIndex>> {
    let entries = fs::read_dir(path).ok()?;
    let mut index = AHashMap::new();
    for e in entries.flatten() {
        let n = e.file_name();
        let Some(n) = n.to_str().filter(|n| n.is_ascii()) else {
            continue;
        };
        // Case collisions are unsupported; retain whichever entry the
        // filesystem enumerates first.
        index
            .entry(n.to_ascii_lowercase())
            .or_insert_with(|| n.to_owned());
    }
    Some(Arc::new(index))
}

/// The outcome of one pass through the directory indices.
enum ResolveAttempt {
    Found(ResolvedPath),
    Missing,
    Stale(Vec<PathBuf>),
}

/// A database-spelled TZif path and indices pending successful parsing.
struct ResolvedPath {
    path: PathBuf,
    id: String,
    updates: DirectoryUpdates,
}

/// Access layer for timezone data and relevant metadata.
#[derive(Debug)]
pub(crate) struct TzStore {
    // The zoneinfo timezone cache.
    cache: Cache,
    // Directory spelling indices, published only after a valid TZif load.
    directories: DirectoryCache,
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
            directories: DirectoryCache::new(),
            tzdata_path: OncePyCell::new(get_tzdata_path),
            paths: OncePyCell::new(init_paths),
            system_tz_cache: RwLock::new(None),
            exc_notfound,
        }
    }

    /// Set the timezone search paths, overriding the lazily-initialized default.
    pub(crate) fn set_paths(&self, new_paths: Vec<PathBuf>) {
        self.paths.set(new_paths);
        self.directories.clear();
    }

    /// Fetches the timezone definition for the given IANA time zone ID.
    pub(crate) fn get(&self, key: &str) -> PyResult<Arc<TimeZone>> {
        let Some(validated) = ValidatedKey::new(key) else {
            return raise(
                self.exc_notfound,
                format!("No time zone found with key {key}"),
            );
        };
        let normalized = NormalizedKey::from(validated);
        self.cache
            .get_or_insert_with(&normalized, || self.load_tzif(&normalized))?
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

    fn get_or_posix(&self, key: &str) -> PyResult<Arc<TimeZone>> {
        let Some(validated) = ValidatedKey::new(key) else {
            return TimeZone::parse_posix(key)
                .map(Arc::new)
                .ok_or_else_raise(self.exc_notfound, || {
                    format!("No time zone found with key or posix TZ string {key}")
                });
        };
        let normalized = NormalizedKey::from(validated);
        self.cache
            .get_or_insert_with(&normalized, || self.load_tzif(&normalized))?
            .or_else(|| TimeZone::parse_posix(key).map(Arc::new))
            .ok_or_else_raise(self.exc_notfound, || {
                format!("No time zone found with key or posix TZ string {key}")
            })
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
        self.directories.clear();
    }

    /// Clear specific entries from the cache.
    pub(crate) fn clear_only(&self, keys: &[String]) {
        self.cache.clear_only(
            &keys
                .iter()
                .filter_map(|key| ValidatedKey::new(key).map(NormalizedKey::from))
                .collect::<Vec<_>>(),
        );
        // Directory indices are shared by many keys, so clear them together.
        self.directories.clear();
    }

    /// Return the current TZPATH as a Python tuple of strings.
    /// Lazily initializes paths if needed.
    pub(crate) fn get_paths_as_pytuple(&self) -> PyReturn {
        let paths = self.paths.get()?;
        let tuple = PyTuple::with_len(paths.len() as _)?;
        for (i, p) in paths.iter().enumerate() {
            // SAFETY: the tuple has paths.len() uninitialized slots and enumerate visits each once.
            unsafe { tuple.init_item_unchecked(i as _, p.to_string_lossy().as_ref().to_py()?) };
        }
        // SAFETY: PyTuple is a PyObj subtype
        Ok(unsafe { tuple.cast_unchecked() })
    }

    fn load_tzif(&self, key: &NormalizedKey) -> PyResult<Option<TimeZone>> {
        self.load_tzif_from_tzpath(key)?
            .map_or_else(|| self.load_tzif_from_tzdata(key), |tz| Ok(Some(tz)))
    }

    /// Load a TZif from the TZPATH directory, assuming a benign TZ ID.
    /// Lazily initializes paths from Python if needed.
    fn load_tzif_from_tzpath(&self, key: &NormalizedKey) -> PyResult<Option<TimeZone>> {
        let paths = self.paths.get()?;
        for base in paths.iter() {
            if let Some(tz) = self.read_tzif_by_key(base, key) {
                return Ok(Some(tz));
            }
        }
        Ok(None)
    }

    /// Load a TZif from the tzdata package, assuming a benign TZ ID.
    fn load_tzif_from_tzdata(&self, key: &NormalizedKey) -> PyResult<Option<TimeZone>> {
        let tzdata_path = self.tzdata_path.get()?;
        match tzdata_path.as_deref() {
            Some(base) => Ok(self.read_tzif_by_key(base, key)),
            None => Ok(None),
        }
    }

    fn read_tzif_by_key(&self, base: &Path, key: &NormalizedKey) -> Option<TimeZone> {
        let ResolvedPath { path, id, updates } = self.directories.resolve(base, key)?;
        let timezone = self.read_tzif_at_path(&path, Some(&id));
        if timezone.is_some() {
            self.directories.publish(updates);
        }
        timezone
    }

    /// Read a TZif file from the given path, returning None if it doesn't exist
    /// or otherwise cannot be read.
    fn read_tzif_at_path(&self, path: &Path, key: Option<&str>) -> Option<TimeZone> {
        if path.is_file() {
            fs::read(path)
                .ok()
                .and_then(|d| TimeZone::parse_tzif(&d, key).ok())
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
        let tz_type = tz_type_obj.to_i64()?;
        let tz_value = tz_value_obj.as_str()?;

        match tz_type {
            // type 0: a zoneinfo key
            0 => self.get(tz_value),
            // type 1: Path to a TZif file
            1 => {
                let path = PathBuf::from(tz_value);
                let tzif = self
                    .read_tzif_at_path(&path, None)
                    .ok_or_else_raise(self.exc_notfound, || {
                        format!("No time zone found at path {path:?}")
                    })?;
                Ok(Arc::new(tzif))
            }
            // type 2: zoneinfo key OR posix TZ string (we're unsure which)
            2 => self.get_or_posix(tz_value),
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

/// A borrowed TZ ID proven safe for filesystem lookup.
#[derive(Debug, Clone, Copy)]
struct ValidatedKey<'a>(&'a str);

impl<'a> ValidatedKey<'a> {
    fn new(key: &'a str) -> Option<Self> {
        is_valid_key(key).then_some(Self(key))
    }
}

/// An owned, ASCII-lowercase TZ ID used as a cache key.
#[derive(Debug, Clone, Eq, Hash, PartialEq)]
struct NormalizedKey(String);

impl NormalizedKey {
    fn as_str(&self) -> &str {
        &self.0
    }
}

impl From<ValidatedKey<'_>> for NormalizedKey {
    fn from(value: ValidatedKey<'_>) -> Self {
        Self(value.0.to_ascii_lowercase())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::{
        env, fs,
        sync::atomic::{AtomicUsize, Ordering},
    };

    static NEXT_TEMP_DIR: AtomicUsize = AtomicUsize::new(0);

    struct TempDir(PathBuf);

    impl TempDir {
        fn new() -> Self {
            let path = env::temp_dir().join(format!(
                "whenever-tz-store-{}-{}",
                std::process::id(),
                NEXT_TEMP_DIR.fetch_add(1, Ordering::Relaxed),
            ));
            fs::create_dir(&path).unwrap();
            Self(path)
        }
    }

    impl Drop for TempDir {
        fn drop(&mut self) {
            fs::remove_dir_all(&self.0).unwrap();
        }
    }

    fn normalized(key: &str) -> NormalizedKey {
        NormalizedKey::from(ValidatedKey::new(key).unwrap())
    }

    #[test]
    fn resolve_path_recovers_database_spelling() {
        let dir = TempDir::new();
        let cache = DirectoryCache::new();
        let zone = dir.0.join("America/Argentina/Buenos_Aires");
        fs::create_dir_all(zone.parent().unwrap()).unwrap();
        fs::write(&zone, b"TZif").unwrap();

        let resolved = cache
            .resolve(&dir.0, &normalized("aMeRiCa/aRgEnTiNa/bUeNoS_aIrEs"))
            .expect("expected a matching path");
        assert_eq!(resolved.path, zone);
        assert_eq!(resolved.id, "America/Argentina/Buenos_Aires");
        assert_eq!(resolved.updates.len(), 3);
    }

    #[test]
    fn resolve_path_stops_for_missing_or_wrong_entry_type() {
        let dir = TempDir::new();
        let cache = DirectoryCache::new();
        fs::write(dir.0.join("Europe"), b"not a directory").unwrap();
        fs::create_dir(dir.0.join("America")).unwrap();
        fs::create_dir(dir.0.join("America/Argentina")).unwrap();
        fs::create_dir(dir.0.join("America/Argentina/Buenos_Aires")).unwrap();

        for key in [
            "Europe/Amsterdam",
            "America/Missing/Buenos_Aires",
            "America/Argentina/Buenos_Aires",
        ] {
            assert!(cache.resolve(&dir.0, &normalized(key)).is_none());
        }
    }

    #[test]
    fn resolve_path_ignores_non_ascii_entries() {
        let dir = TempDir::new();
        let cache = DirectoryCache::new();
        let zone = dir.0.join("Éurope/Amsterdam");
        fs::create_dir_all(zone.parent().unwrap()).unwrap();
        fs::write(zone, b"TZif").unwrap();

        assert!(
            cache
                .resolve(&dir.0, &normalized("Europe/Amsterdam"))
                .is_none()
        );
    }

    #[test]
    fn directory_cache_reuses_and_refreshes_indices() {
        let dir = TempDir::new();
        let cache = DirectoryCache::new();
        let europe = dir.0.join("Europe");
        fs::create_dir(&europe).unwrap();
        fs::write(europe.join("Amsterdam"), b"TZif").unwrap();

        let first = cache
            .resolve(&dir.0, &normalized("europe/amsterdam"))
            .unwrap();
        assert_eq!(first.updates.len(), 2);
        cache.publish(first.updates);
        assert_eq!(cache.len(), 2);

        let cached = cache
            .resolve(&dir.0, &normalized("EUROPE/AMSTERDAM"))
            .unwrap();
        assert!(cached.updates.is_empty());

        fs::write(europe.join("Paris"), b"TZif").unwrap();
        let added = cache.resolve(&dir.0, &normalized("europe/paris")).unwrap();
        assert_eq!(added.id, "Europe/Paris");
        assert_eq!(added.updates.len(), 1);
        cache.publish(added.updates);
        assert_eq!(cache.len(), 2);

        assert!(
            cache
                .resolve(&dir.0, &normalized("Europe/Missing"))
                .is_none()
        );
        assert_eq!(cache.len(), 2);

        cache.clear();
        assert_eq!(cache.len(), 0);
    }

    #[test]
    fn strong_lru_keeps_its_most_recent_32_entries() {
        const TZIF: &[u8] = include_bytes!("../../tests/tzif/UTC.tzif");
        let mut lru = VecDeque::new();
        for i in 0..=LRU_CAPACITY {
            let key = format!("Etc/Test{i}");
            let tz = Arc::new(TimeZone::parse_tzif(TZIF, Some(&key)).unwrap());
            Cache::new_to_lru(tz, &mut lru);
        }

        assert_eq!(lru.len(), LRU_CAPACITY);
        assert_eq!(lru.front().unwrap().key.as_deref(), Some("Etc/Test32"));
        assert_eq!(lru.back().unwrap().key.as_deref(), Some("Etc/Test1"));
    }
}
