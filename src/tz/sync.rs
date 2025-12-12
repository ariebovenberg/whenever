//! Thread-safety abstractions that are conditionally compiled based on whether
//! the GIL is disabled (free-threaded Python) or not.
//!
//! - `SyncCell<T>`: A mutex-like wrapper. Uses `UnsafeCell` for GIL builds (no overhead),
//!   `Mutex` for free-threaded builds.
//! - `SyncRwLock<T>`: A read-write lock wrapper. Uses `UnsafeCell` for GIL builds,
//!   `RwLock` for free-threaded builds. Useful for data that is read frequently
//!   but written rarely.
//! - `AtomicRefCount`: A reference counter. Uses plain `usize` for GIL builds,
//!   `AtomicUsize` for free-threaded builds.

// =============================================================================
// GIL-enabled builds: no synchronization needed
// =============================================================================

#[cfg(not(Py_GIL_DISABLED))]
mod gil_enabled {
    use std::cell::UnsafeCell;

    /// A cell that provides interior mutability without synchronization.
    /// Safe only when the GIL guarantees single-threaded access.
    pub(crate) struct SyncCell<T>(UnsafeCell<T>);

    impl<T> std::fmt::Debug for SyncCell<T> {
        fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
            f.debug_struct("SyncCell").finish_non_exhaustive()
        }
    }

    impl<T> SyncCell<T> {
        pub(crate) fn new(value: T) -> Self {
            Self(UnsafeCell::new(value))
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

    /// A read-write "lock" that provides interior mutability without synchronization.
    /// Safe only when the GIL guarantees single-threaded access.
    pub(crate) struct SyncRwLock<T>(UnsafeCell<T>);

    impl<T> std::fmt::Debug for SyncRwLock<T> {
        fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
            f.debug_struct("SyncRwLock").finish_non_exhaustive()
        }
    }

    impl<T> SyncRwLock<T> {
        pub(crate) fn new(value: T) -> Self {
            Self(UnsafeCell::new(value))
        }

        /// Access the inner value immutably (no actual locking with GIL).
        #[inline]
        pub(crate) fn with_read<R, F: FnOnce(&T) -> R>(&self, f: F) -> R {
            // SAFETY: GIL guarantees single-threaded access
            f(unsafe { &*self.0.get() })
        }

        /// Access the inner value mutably (no actual locking with GIL).
        #[inline]
        pub(crate) fn with_write<R, F: FnOnce(&mut T) -> R>(&self, f: F) -> R {
            // SAFETY: GIL guarantees single-threaded access
            f(unsafe { &mut *self.0.get() })
        }
    }

    // SAFETY: With GIL enabled, Python ensures single-threaded access
    unsafe impl<T> Sync for SyncRwLock<T> {}

    /// A reference counter without atomic operations.
    /// Safe only when the GIL guarantees single-threaded access.
    pub(crate) struct AtomicRefCount(UnsafeCell<usize>);

    impl AtomicRefCount {
        pub(crate) fn new(value: usize) -> Self {
            Self(UnsafeCell::new(value))
        }

        #[inline]
        #[cfg(debug_assertions)]
        pub(crate) fn get(&self) -> usize {
            // SAFETY: GIL guarantees single-threaded access
            unsafe { *self.0.get() }
        }

        #[inline]
        pub(crate) fn increment(&self) {
            // SAFETY: GIL guarantees single-threaded access
            unsafe { *self.0.get() += 1 }
        }

        /// This method always succeeds in GIL-enabled builds.
        /// Its purpose is to provide a consistent API with free-threaded builds.
        #[inline]
        pub(crate) fn try_increment(&self) -> bool {
            self.increment();
            true
        }

        /// Decrements the counter and returns the new value.
        #[inline]
        pub(crate) fn decrement(&self) -> usize {
            // SAFETY: GIL guarantees single-threaded access
            unsafe {
                let ptr = self.0.get();
                *ptr -= 1;
                *ptr
            }
        }
    }

    // SAFETY: With GIL enabled, Python ensures single-threaded access
    unsafe impl Sync for AtomicRefCount {}
}

// =============================================================================
// Free-threaded builds: synchronization required
// =============================================================================

#[cfg(Py_GIL_DISABLED)]
mod free_threaded {
    use std::sync::{
        Mutex, RwLock,
        atomic::{AtomicUsize, Ordering},
    };

    /// A cell that provides interior mutability with mutex synchronization.
    pub(crate) struct SyncCell<T>(Mutex<T>);

    impl<T> std::fmt::Debug for SyncCell<T> {
        fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
            f.debug_struct("SyncCell").finish_non_exhaustive()
        }
    }

    impl<T> SyncCell<T> {
        pub(crate) fn new(value: T) -> Self {
            Self(Mutex::new(value))
        }

        /// Access the inner value mutably under the mutex.
        #[inline]
        pub(crate) fn with_mut<R, F: FnOnce(&mut T) -> R>(&self, f: F) -> R {
            let mut guard = self.0.lock().expect("mutex poisoned");
            f(&mut guard)
        }
    }

    /// A read-write lock that provides interior mutability with RwLock synchronization.
    pub(crate) struct SyncRwLock<T>(RwLock<T>);

    impl<T> std::fmt::Debug for SyncRwLock<T> {
        fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
            f.debug_struct("SyncRwLock").finish_non_exhaustive()
        }
    }

    impl<T> SyncRwLock<T> {
        pub(crate) fn new(value: T) -> Self {
            Self(RwLock::new(value))
        }

        /// Access the inner value immutably under a read lock.
        #[inline]
        pub(crate) fn with_read<R, F: FnOnce(&T) -> R>(&self, f: F) -> R {
            let guard = self.0.read().expect("rwlock poisoned");
            f(&guard)
        }

        /// Access the inner value mutably under a write lock.
        #[inline]
        pub(crate) fn with_write<R, F: FnOnce(&mut T) -> R>(&self, f: F) -> R {
            let mut guard = self.0.write().expect("rwlock poisoned");
            f(&mut guard)
        }
    }

    /// A reference counter with atomic operations.
    pub(crate) struct AtomicRefCount(AtomicUsize);

    impl AtomicRefCount {
        pub(crate) fn new(value: usize) -> Self {
            Self(AtomicUsize::new(value))
        }

        #[inline]
        #[cfg(debug_assertions)]
        pub(crate) fn get(&self) -> usize {
            self.0.load(Ordering::Acquire)
        }

        #[inline]
        pub(crate) fn increment(&self) {
            self.0.fetch_add(1, Ordering::AcqRel);
        }

        /// Try to increment the counter if it's not zero.
        /// Returns true if successful, false if the counter was zero.
        /// Uses compare-and-swap to atomically check and increment.
        #[inline]
        pub(crate) fn try_increment(&self) -> bool {
            let mut current = self.0.load(Ordering::Acquire);
            loop {
                if current == 0 {
                    return false;
                }
                match self.0.compare_exchange_weak(
                    current,
                    current + 1,
                    Ordering::AcqRel,
                    Ordering::Acquire,
                ) {
                    Ok(_) => return true,
                    Err(new) => current = new,
                }
            }
        }

        /// Decrements the counter and returns the new value.
        #[inline]
        pub(crate) fn decrement(&self) -> usize {
            self.0.fetch_sub(1, Ordering::AcqRel) - 1
        }
    }
}

#[cfg(not(Py_GIL_DISABLED))]
pub(crate) use gil_enabled::*;

#[cfg(Py_GIL_DISABLED)]
pub(crate) use free_threaded::*;
