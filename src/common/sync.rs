//! Thread-safety abstractions that are conditionally compiled based on whether
//! the GIL is disabled (free-threaded Python) or not.
//!
//! - `SyncCell<T>`: A mutex-like wrapper. Uses `UnsafeCell` for GIL builds (no overhead),
//!   `Mutex` for free-threaded builds.
//! - `SwapCell<T>`: A cell optimized for read-heavy workloads with rare writes.
//!   Uses `UnsafeCell` for GIL builds, `AtomicPtr` for free-threaded builds.
//!   Reads are lock-free; writes atomically swap the entire value.
//! - `SwapPtr<T>`: Like `SwapCell` but for `Option<NonNull<T>>` specifically,
//!   avoiding the extra Box indirection since it's already pointer-sized.
//!   Has `try_init` for lock-free init-once patterns (CAS null→value).
//! - `OncePyCell<T>`: A cell that computes its value on first access (fallible).
//!   Uses `UnsafeCell` for GIL builds, lock-free CAS for free-threaded builds.
//!   On concurrent init, both threads compute the value; the CAS loser drops theirs.
//! - `AtomicRefCount`: A reference counter. Uses plain `usize` for GIL builds,
//!   `AtomicUsize` for free-threaded builds.

// =============================================================================
// GIL-enabled builds: no synchronization needed
// =============================================================================

#[cfg(not(Py_GIL_DISABLED))]
mod gil_enabled {
    use crate::py::PyResult;
    use std::cell::UnsafeCell;
    use std::ptr::NonNull;

    /// A cell that provides interior mutability without synchronization.
    /// Safe only when the GIL guarantees single-threaded access.
    #[derive(Debug)]
    pub(crate) struct SyncCell<T>(UnsafeCell<T>);

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

    /// A cell optimized for read-heavy, write-rare access patterns.
    /// In GIL builds, this is just an UnsafeCell with no overhead.
    #[derive(Debug)]
    pub(crate) struct SwapCell<T>(UnsafeCell<T>);

    impl<T> SwapCell<T> {
        pub(crate) fn new(value: T) -> Self {
            Self(UnsafeCell::new(value))
        }

        /// Read the value. Lock-free (no-op with GIL).
        #[inline]
        pub(crate) fn with_read<R, F: FnOnce(&T) -> R>(&self, f: F) -> R {
            // SAFETY: GIL guarantees single-threaded access
            f(unsafe { &*self.0.get() })
        }

        /// Replace the value, returning the old one.
        #[inline]
        pub(crate) fn swap(&self, new: T) -> T {
            // SAFETY: GIL guarantees single-threaded access
            std::mem::replace(unsafe { &mut *self.0.get() }, new)
        }
    }

    // SAFETY: With GIL enabled, Python ensures single-threaded access
    unsafe impl<T> Sync for SwapCell<T> {}

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

    /// A reference counter without atomic operations.
    /// Safe only when the GIL guarantees single-threaded access.
    #[derive(Debug)]
    pub(crate) struct AtomicRefCount(UnsafeCell<usize>);

    impl AtomicRefCount {
        pub(crate) fn new(value: usize) -> Self {
            Self(UnsafeCell::new(value))
        }

        #[inline]
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
        /// See the free-threaded version for details.
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

    /// A cell that computes its value on first access (fallible).
    /// In GIL builds: no synchronization needed.
    pub(crate) struct OncePyCell<T> {
        init: fn() -> PyResult<T>,
        value: UnsafeCell<Option<T>>,
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
        pub(crate) fn get(&self) -> PyResult<&T> {
            // SAFETY: GIL guarantees single-threaded access
            let slot = unsafe { &mut *self.value.get() };
            if slot.is_none() {
                *slot = Some((self.init)()?);
            }
            // SAFETY: We just ensured it's Some
            Ok(unsafe { slot.as_ref().unwrap_unchecked() })
        }

        /// Get the value if already initialized (e.g. for GC traverse).
        #[inline]
        pub(crate) fn get_if_init(&self) -> Option<&T> {
            // SAFETY: GIL guarantees single-threaded access
            unsafe { (*self.value.get()).as_ref() }
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
        Mutex,
        atomic::{AtomicPtr, AtomicUsize, Ordering},
    };

    /// A cell that provides interior mutability with mutex synchronization.
    #[derive(Debug)]
    pub(crate) struct SyncCell<T>(Mutex<T>);

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

    /// A cell optimized for read-heavy, write-rare access patterns.
    /// Uses AtomicPtr for lock-free reads and atomic swaps for writes.
    #[derive(Debug)]
    pub(crate) struct SwapCell<T>(AtomicPtr<T>);

    impl<T> SwapCell<T> {
        pub(crate) fn new(value: T) -> Self {
            Self(AtomicPtr::new(Box::into_raw(Box::new(value))))
        }

        /// Read the value. Lock-free.
        #[inline]
        pub(crate) fn with_read<R, F: FnOnce(&T) -> R>(&self, f: F) -> R {
            let ptr = self.0.load(Ordering::Acquire);
            // SAFETY: ptr is always valid - we only store valid Box pointers,
            // and swap always replaces with another valid pointer.
            f(unsafe { &*ptr })
        }

        /// Replace the value, returning the old one.
        #[inline]
        pub(crate) fn swap(&self, new: T) -> T {
            let new_ptr = Box::into_raw(Box::new(new));
            let old_ptr = self.0.swap(new_ptr, Ordering::AcqRel);
            // SAFETY: old_ptr was created by Box::into_raw
            *unsafe { Box::from_raw(old_ptr) }
        }
    }

    impl<T> Drop for SwapCell<T> {
        fn drop(&mut self) {
            let ptr = *self.0.get_mut();
            // SAFETY: ptr was created by Box::into_raw
            drop(unsafe { Box::from_raw(ptr) });
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

    /// A reference counter with atomic operations.
    #[derive(Debug)]
    pub(crate) struct AtomicRefCount(AtomicUsize);

    impl AtomicRefCount {
        pub(crate) fn new(value: usize) -> Self {
            Self(AtomicUsize::new(value))
        }

        #[inline]
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

    /// A cell that computes its value on first access (fallible).
    /// In free-threaded builds: uses lock-free CAS. On concurrent init, both
    /// threads compute the value; the CAS loser drops theirs.
    pub(crate) struct OncePyCell<T> {
        init: fn() -> PyResult<T>,
        ptr: AtomicPtr<T>,
    }

    impl<T> OncePyCell<T> {
        pub(crate) const fn new(init: fn() -> PyResult<T>) -> Self {
            Self {
                init,
                ptr: AtomicPtr::new(std::ptr::null_mut()),
            }
        }

        /// Fast path: return reference if already initialized.
        #[inline]
        pub(crate) fn get(&self) -> PyResult<&T> {
            let p = self.ptr.load(Ordering::Acquire);
            if !p.is_null() {
                // SAFETY: non-null ptr is a valid Box pointer that's never moved
                return Ok(unsafe { &*p });
            }
            self.get_slow()
        }

        /// Slow path: compute the value and CAS it in.
        #[cold]
        fn get_slow(&self) -> PyResult<&T> {
            let val = (self.init)()?;
            let new_ptr = Box::into_raw(Box::new(val));
            match self.ptr.compare_exchange(
                std::ptr::null_mut(),
                new_ptr,
                Ordering::AcqRel,
                Ordering::Acquire,
            ) {
                Ok(_) => {
                    // SAFETY: we just stored this pointer, it's valid
                    Ok(unsafe { &*new_ptr })
                }
                Err(winner) => {
                    // Another thread won — drop ours, use theirs
                    drop(unsafe { Box::from_raw(new_ptr) });
                    // SAFETY: winner is non-null and stable (never swapped after init)
                    Ok(unsafe { &*winner })
                }
            }
        }

        /// Get the value if already initialized (e.g. for GC traverse).
        #[inline]
        pub(crate) fn get_if_init(&self) -> Option<&T> {
            let p = self.ptr.load(Ordering::Acquire);
            if p.is_null() {
                None
            } else {
                // SAFETY: non-null ptr is stable and valid
                Some(unsafe { &*p })
            }
        }
    }

    impl<T> Drop for OncePyCell<T> {
        fn drop(&mut self) {
            let p = *self.ptr.get_mut();
            if !p.is_null() {
                // SAFETY: p was created by Box::into_raw
                drop(unsafe { Box::from_raw(p) });
            }
        }
    }

    impl<T: std::fmt::Debug> std::fmt::Debug for OncePyCell<T> {
        fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
            let p = self.ptr.load(Ordering::Acquire);
            let value: Option<&T> = if p.is_null() {
                None
            } else {
                Some(unsafe { &*p })
            };
            f.debug_struct("OncePyCell").field("value", &value).finish()
        }
    }

    // SAFETY: OncePyCell uses proper atomic synchronization for concurrent access
    unsafe impl<T: Send + Sync> Sync for OncePyCell<T> {}
    unsafe impl<T: Send> Send for OncePyCell<T> {}
}

#[cfg(not(Py_GIL_DISABLED))]
pub(crate) use gil_enabled::*;

#[cfg(Py_GIL_DISABLED)]
pub(crate) use free_threaded::*;
