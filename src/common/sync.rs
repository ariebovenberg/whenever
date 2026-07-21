//! Thread-safety abstractions that are conditionally compiled based on whether
//! the GIL is disabled (free-threaded Python) or not.
//!
//! - `SyncCell<T>`: A mutex-like wrapper. Uses `UnsafeCell` for GIL builds (no overhead),
//!   `Mutex` for free-threaded builds.
//! - `SwapPtr<T>`: A cell for `Option<NonNull<T>>` optimized for read-heavy, write-rare patterns.
//!   Avoids Box indirection since `Option<NonNull<T>>` is pointer-sized.
//!   Has `try_init` for lock-free init-once patterns (CAS null→value).
//! - `OncePyCell<T>`: A cell that computes its value on first access (fallible).
//!   Supports `set()` to override the value later (e.g. for user-controlled search paths).
//!   Returns `Arc<T>` so that a concurrent `set()` never frees memory still reachable by a reader.
//!   GIL builds use `UnsafeCell<Option<Arc<T>>>` (no lock overhead).
//!   Free-threaded builds use `RwLock<Option<Arc<T>>>` (shared read lock, exclusive write lock).

// =============================================================================
// GIL-enabled builds: no synchronization needed
// =============================================================================

#[cfg(not(Py_GIL_DISABLED))]
mod gil_enabled {
    use crate::py::PyResult;
    use std::cell::UnsafeCell;
    use std::ptr::NonNull;
    use std::sync::Arc;

    /// A cell that provides interior mutability without synchronization.
    /// Safe only when the GIL guarantees single-threaded access.
    #[derive(Debug)]
    pub(crate) struct SyncCell<T>(UnsafeCell<T>);

    impl<T> SyncCell<T> {
        pub(crate) fn new(value: T) -> Self {
            Self(UnsafeCell::new(value))
        }

        /// Access the inner value immutably.
        #[inline]
        pub(crate) fn with<R, F: FnOnce(&T) -> R>(&self, f: F) -> R {
            // SAFETY: GIL guarantees single-threaded access
            f(unsafe { &*self.0.get() })
        }

        /// Access the inner value mutably.
        #[inline]
        pub(crate) fn with_mut<R, F: FnOnce(&mut T) -> R>(&self, f: F) -> R {
            // SAFETY: GIL guarantees single-threaded access
            f(unsafe { &mut *self.0.get() })
        }
    }

    // SAFETY: With GIL enabled, Python ensures single-threaded access
    unsafe impl<T> Sync for SyncCell<T> {}

    /// A cell for `Option<NonNull<T>>` optimized for read-heavy, write-rare patterns.
    /// In GIL builds, this is just an UnsafeCell with no overhead.
    #[derive(Debug)]
    pub(crate) struct SwapPtr<T>(UnsafeCell<Option<NonNull<T>>>);

    impl<T> SwapPtr<T> {
        pub(crate) const fn new(value: Option<NonNull<T>>) -> Self {
            Self(UnsafeCell::new(value))
        }

        /// Read the pointer. Lock-free (no-op with GIL).
        #[inline]
        pub(crate) fn load(&self) -> Option<NonNull<T>> {
            // SAFETY: GIL guarantees single-threaded access
            unsafe { *self.0.get() }
        }

        /// Replace the pointer, returning the old one.
        #[inline]
        pub(crate) fn swap(&self, new: Option<NonNull<T>>) -> Option<NonNull<T>> {
            // SAFETY: GIL guarantees single-threaded access
            std::mem::replace(unsafe { &mut *self.0.get() }, new)
        }

        /// Try to set the pointer from null to `value`.
        /// Returns Ok(()) on success, Err(existing) if already set.
        #[inline]
        pub(crate) fn try_init(&self, value: NonNull<T>) -> Result<(), NonNull<T>> {
            // SAFETY: GIL guarantees single-threaded access
            let current = unsafe { *self.0.get() };
            match current {
                None => {
                    unsafe { *self.0.get() = Some(value) };
                    Ok(())
                }
                Some(existing) => Err(existing),
            }
        }
    }

    // SAFETY: With GIL enabled, Python ensures single-threaded access
    unsafe impl<T> Sync for SwapPtr<T> {}

    /// A cell that computes its value on first access (fallible).
    /// In GIL builds: no synchronization needed. Stores `Arc<T>` so the API
    /// is identical to the free-threaded variant.
    pub(crate) struct OncePyCell<T> {
        init: fn() -> PyResult<T>,
        value: UnsafeCell<Option<Arc<T>>>,
    }

    impl<T> OncePyCell<T> {
        pub(crate) const fn new(init: fn() -> PyResult<T>) -> Self {
            Self {
                init,
                value: UnsafeCell::new(None),
            }
        }

        /// Get the value, initializing on first call.
        #[inline]
        pub(crate) fn get(&self) -> PyResult<Arc<T>> {
            // SAFETY: GIL guarantees single-threaded access
            let slot = unsafe { &mut *self.value.get() };
            if slot.is_none() {
                *slot = Some(Arc::new((self.init)()?));
            }
            // SAFETY: We just ensured it's Some
            Ok(unsafe { slot.as_ref().unwrap_unchecked() }.clone())
        }

        /// Get the value if already initialized (e.g. for GC traverse).
        #[inline]
        pub(crate) fn get_if_init(&self) -> Option<Arc<T>> {
            // SAFETY: GIL guarantees single-threaded access
            unsafe { (*self.value.get()).as_ref() }.map(Arc::clone)
        }

        /// Override the stored value, replacing any existing one (or bypassing lazy init).
        #[inline]
        pub(crate) fn set(&self, value: T) {
            // SAFETY: GIL guarantees single-threaded access
            *unsafe { &mut *self.value.get() } = Some(Arc::new(value));
        }
    }

    impl<T: std::fmt::Debug> std::fmt::Debug for OncePyCell<T> {
        fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
            f.debug_struct("OncePyCell")
                .field("value", unsafe { &*self.value.get() })
                .finish()
        }
    }

    // SAFETY: With GIL enabled, Python ensures single-threaded access
    unsafe impl<T> Sync for OncePyCell<T> {}
}

// =============================================================================
// Free-threaded builds: synchronization required
// =============================================================================

#[cfg(Py_GIL_DISABLED)]
mod free_threaded {
    use crate::py::PyResult;
    use std::ptr::NonNull;
    use std::sync::{
        Arc, Mutex, RwLock,
        atomic::{AtomicPtr, Ordering},
    };

    /// A cell that provides interior mutability with mutex synchronization.
    #[derive(Debug)]
    pub(crate) struct SyncCell<T>(Mutex<T>);

    impl<T> SyncCell<T> {
        pub(crate) fn new(value: T) -> Self {
            Self(Mutex::new(value))
        }

        /// Access the inner value immutably under the mutex.
        #[inline]
        pub(crate) fn with<R, F: FnOnce(&T) -> R>(&self, f: F) -> R {
            let guard = self.0.lock().expect("mutex poisoned");
            f(&guard)
        }

        /// Access the inner value mutably under the mutex.
        #[inline]
        pub(crate) fn with_mut<R, F: FnOnce(&mut T) -> R>(&self, f: F) -> R {
            let mut guard = self.0.lock().expect("mutex poisoned");
            f(&mut guard)
        }
    }

    /// A cell for `Option<NonNull<T>>` optimized for read-heavy, write-rare patterns.
    /// Uses AtomicPtr directly since Option<NonNull<T>> is pointer-sized.
    /// No Box indirection needed.
    #[derive(Debug)]
    pub(crate) struct SwapPtr<T>(AtomicPtr<T>);

    impl<T> SwapPtr<T> {
        pub(crate) const fn new(value: Option<NonNull<T>>) -> Self {
            let ptr = match value {
                Some(p) => p.as_ptr(),
                None => std::ptr::null_mut(),
            };
            Self(AtomicPtr::new(ptr))
        }

        /// Read the pointer. Lock-free.
        #[inline]
        pub(crate) fn load(&self) -> Option<NonNull<T>> {
            NonNull::new(self.0.load(Ordering::Acquire))
        }

        /// Replace the pointer, returning the old one.
        #[inline]
        pub(crate) fn swap(&self, new: Option<NonNull<T>>) -> Option<NonNull<T>> {
            let new_ptr = new.map_or(std::ptr::null_mut(), |p| p.as_ptr());
            NonNull::new(self.0.swap(new_ptr, Ordering::AcqRel))
        }

        /// Try to set the pointer from null to `value`.
        /// Returns Ok(()) on success, Err(existing) if already set.
        #[inline]
        pub(crate) fn try_init(&self, value: NonNull<T>) -> Result<(), NonNull<T>> {
            match self.0.compare_exchange(
                std::ptr::null_mut(),
                value.as_ptr(),
                Ordering::AcqRel,
                Ordering::Acquire,
            ) {
                Ok(_) => Ok(()),
                Err(existing) => {
                    // SAFETY: CAS failed because ptr was non-null
                    Err(unsafe { NonNull::new_unchecked(existing) })
                }
            }
        }
    }

    /// A cell that computes its value on first access (fallible).
    /// In free-threaded builds: uses `RwLock<Option<Arc<T>>>`.
    /// Reads take a shared read lock (fast when uncontested) and clone the `Arc`.
    /// Writes (init or `set()`) take an exclusive write lock.
    ///
    /// Storing `Arc<T>` fixes the `set()` vs `get()` race present in a raw-pointer
    /// design: `set()` replaces the `Arc` under the write lock; any reader already
    /// holding a cloned `Arc` keeps its allocation alive until the clone drops.
    ///
    /// For truly lock-free reads, `arc-swap` (or hazard pointers) would be needed,
    /// but the overhead of an uncontested read lock is negligible for this use case.
    pub(crate) struct OncePyCell<T> {
        init: fn() -> PyResult<T>,
        value: RwLock<Option<Arc<T>>>,
    }

    impl<T> OncePyCell<T> {
        pub(crate) const fn new(init: fn() -> PyResult<T>) -> Self {
            Self {
                init,
                value: RwLock::new(None),
            }
        }

        /// Get the value, initializing on first call.
        /// Fast path: one read lock + Arc clone (2 uncontested atomics).
        #[inline]
        pub(crate) fn get(&self) -> PyResult<Arc<T>> {
            if let Some(arc) = self.value.read().unwrap().as_ref() {
                return Ok(arc.clone());
            }
            self.get_slow()
        }

        /// Slow path: compute the value and store it under a write lock.
        /// Double-checked: another thread may have initialized while we computed.
        #[cold]
        fn get_slow(&self) -> PyResult<Arc<T>> {
            let val = Arc::new((self.init)()?);
            let mut guard = self.value.write().unwrap();
            if let Some(existing) = guard.as_ref() {
                return Ok(existing.clone());
            }
            *guard = Some(val.clone());
            Ok(val)
        }

        /// Get the value if already initialized (e.g. for GC traverse).
        #[inline]
        pub(crate) fn get_if_init(&self) -> Option<Arc<T>> {
            self.value.read().unwrap().as_ref().map(Arc::clone)
        }

        /// Override the stored value, replacing any existing one (or bypassing lazy init).
        /// Safe: write lock ensures no reader is active; old `Arc` is dropped after the lock
        /// is released, and existing `Arc` clones (held by readers) keep the allocation alive.
        pub(crate) fn set(&self, value: T) {
            *self.value.write().unwrap() = Some(Arc::new(value));
        }
    }

    impl<T: std::fmt::Debug> std::fmt::Debug for OncePyCell<T> {
        fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
            f.debug_struct("OncePyCell")
                .field("value", &*self.value.read().unwrap())
                .finish()
        }
    }

    // SAFETY: OncePyCell uses RwLock for safe concurrent access
    unsafe impl<T: Send + Sync> Sync for OncePyCell<T> {}
    unsafe impl<T: Send> Send for OncePyCell<T> {}
}

#[cfg(not(Py_GIL_DISABLED))]
pub(crate) use gil_enabled::{OncePyCell, SwapPtr, SyncCell};

#[cfg(Py_GIL_DISABLED)]
pub(crate) use free_threaded::{OncePyCell, SwapPtr, SyncCell};
