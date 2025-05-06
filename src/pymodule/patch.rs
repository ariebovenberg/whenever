/// Functionality related to patching the current time
use crate::{
    classes::instant::Instant,
    common::{math::*, pyobject::*, pytype::*},
    pymodule::State,
};
use pyo3_ffi::*;
use std::time::SystemTime;

pub(crate) unsafe fn _patch_time_frozen(module: *mut PyObject, arg: *mut PyObject) -> PyReturn {
    _patch_time(module, arg, true)
}

pub(crate) unsafe fn _patch_time_keep_ticking(
    module: *mut PyObject,
    arg: *mut PyObject,
) -> PyReturn {
    _patch_time(module, arg, false)
}

pub(crate) unsafe fn _patch_time(
    module: *mut PyObject,
    arg: *mut PyObject,
    freeze: bool,
) -> PyReturn {
    let state = State::for_mod_mut(module);
    if Py_TYPE(arg) != state.instant_type.as_ptr().cast() {
        raise_type_err("Expected an Instant")?
    }
    let instant = Instant::extract(arg);
    let pos_epoch = u64::try_from(instant.epoch.get())
        .ok()
        .ok_or_type_err("Can only set time after 1970")?;

    let patch = &mut state.time_patch;

    patch.set_state(if freeze {
        PatchState::Frozen(instant)
    } else {
        PatchState::KeepTicking {
            pin: std::time::Duration::new(pos_epoch, instant.subsec.get() as _),
            at: SystemTime::now()
                .duration_since(SystemTime::UNIX_EPOCH)
                .ok()
                .ok_or_type_err("System time before 1970")?,
        }
    });
    Py_None().as_result()
}

pub(crate) unsafe fn _unpatch_time(module: *mut PyObject, _: *mut PyObject) -> PyReturn {
    let patch = &mut State::for_mod_mut(module).time_patch;
    patch.set_state(PatchState::Unset);
    Py_None().as_result()
}

#[derive(Debug, Clone, Copy)]
pub(crate) struct Patch {
    state: PatchState,
    time_machine_installed: bool,
}

impl Patch {
    pub(crate) unsafe fn new() -> PyResult<Self> {
        Ok(Self {
            state: PatchState::Unset,
            time_machine_installed: time_machine_installed()?,
        })
    }

    pub(crate) fn set_state(&mut self, state: PatchState) {
        self.state = state;
    }
}

unsafe fn time_machine_installed() -> PyResult<bool> {
    // Important: we don't import `time_machine` here,
    // because that would be slower. We only need to check its existence.
    let find_spec = import_from(c"importlib.util", c"find_spec")?;
    defer_decref!(find_spec);
    let spec = call1(find_spec, steal!("time_machine".to_py()?))?;
    defer_decref!(spec);
    Ok(!is_none(spec))
}

#[derive(Debug, Clone, Copy)]
pub(crate) enum PatchState {
    Unset,
    Frozen(Instant),
    KeepTicking {
        pin: std::time::Duration,
        at: std::time::Duration,
    },
}

impl Instant {
    pub(crate) fn from_duration_since_epoch(d: std::time::Duration) -> Option<Self> {
        Some(Instant {
            epoch: EpochSecs::new(d.as_secs() as _)?,
            // Safe: subsec on Duration is always in range
            subsec: SubSecNanos::new_unchecked(d.subsec_nanos() as _),
        })
    }

    fn from_nanos_i64(ns: i64) -> Option<Self> {
        Some(Instant {
            epoch: EpochSecs::new(ns / 1_000_000_000)?,
            subsec: SubSecNanos::from_remainder(ns),
        })
    }
}

impl State {
    pub(crate) fn time_ns(&self) -> PyResult<Instant> {
        let Patch {
            state: status,
            time_machine_installed,
        } = self.time_patch;
        match status {
            PatchState::Unset => {
                if time_machine_installed {
                    unsafe { self.time_ns_py() }
                } else {
                    self.time_ns_rust()
                }
            }
            PatchState::Frozen(e) => Ok(e),
            PatchState::KeepTicking { pin, at } => {
                let dur = pin
                    + SystemTime::now()
                        .duration_since(SystemTime::UNIX_EPOCH)
                        .ok()
                        .ok_or_raise(unsafe { PyExc_OSError }, "System time out of range")?
                    - at;
                Instant::from_duration_since_epoch(dur)
                    .ok_or_raise(unsafe { PyExc_OSError }, "System time out of range")
            }
        }
    }

    // TODO safety
    unsafe fn time_ns_py(&self) -> PyResult<Instant> {
        let ts = PyObject_CallNoArgs(self.time_ns).as_result()?;
        defer_decref!(ts);
        let ns = (ts as *mut PyObject)
            // FUTURE: this will break in the year 2262. Fix it before then.
            .to_i64()?
            .ok_or_raise(PyExc_RuntimeError, "time_ns() returned a non-integer")?;
        Instant::from_nanos_i64(ns).ok_or_raise(PyExc_OSError, "System time out of range")
    }

    fn time_ns_rust(&self) -> PyResult<Instant> {
        SystemTime::now()
            .duration_since(SystemTime::UNIX_EPOCH)
            .ok()
            .and_then(Instant::from_duration_since_epoch)
            .ok_or_raise(unsafe { PyExc_OSError }, "System time out of range")
    }
}
