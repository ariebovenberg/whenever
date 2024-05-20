use core::ffi::{c_int, c_void};
use core::{mem, ptr};
use pyo3_ffi::*;
use std::fmt;
use std::ops::Neg;
use std::ptr::null_mut as NULL;

use crate::common::*;
use crate::date_delta::{self, parse_prefix, DateDelta, InitError, Unit as DateUnit};
use crate::time_delta::{
    self, handle_unit, TimeDelta, MAX_HOURS, MAX_MICROSECONDS, MAX_MILLISECONDS, MAX_MINUTES,
    MAX_SECS,
};
use crate::State;

#[derive(Debug, Eq, PartialEq, Copy, Clone)]
pub(crate) struct DateTimeDelta {
    // invariant: these never have opposite signs
    pub(crate) ddelta: DateDelta,
    pub(crate) tdelta: TimeDelta,
}

#[repr(C)]
pub(crate) struct PyDateTimeDelta {
    _ob_base: PyObject,
    data: DateTimeDelta,
}

impl DateTimeDelta {
    pub(crate) fn extract(obj: *mut PyObject) -> DateTimeDelta {
        unsafe { (*obj.cast::<PyDateTimeDelta>()).data }
    }

    pub(crate) fn pyhash(self) -> Py_hash_t {
        self.ddelta.pyhash() ^ self.tdelta.pyhash()
    }

    pub(crate) fn new(ddelta: DateDelta, tdelta: TimeDelta) -> Option<Self> {
        if ddelta.months >= 0 && ddelta.days >= 0 && tdelta.secs >= 0
            || ddelta.months <= 0 && ddelta.days <= 0 && tdelta.secs <= 0
        {
            Some(Self { ddelta, tdelta })
        } else {
            None
        }
    }

    pub(crate) fn checked_mul(self, factor: i32) -> Option<Self> {
        let Self { ddelta, tdelta } = self;
        ddelta
            .checked_mul(factor)
            .zip(tdelta.checked_mul(factor.into()))
            .map(|(ddelta, tdelta)| Self { ddelta, tdelta })
    }

    pub(crate) fn checked_add(self, other: Self) -> Result<Self, InitError> {
        let ddelta = self.ddelta.checked_add(other.ddelta)?;
        let tdelta = self
            .tdelta
            .checked_add(other.tdelta)
            .ok_or(InitError::TooBig)?;
        // Confirm the signs of date- and timedelta didn't get out of sync
        if ddelta.months >= 0 && ddelta.days >= 0 && tdelta.secs >= 0
            || ddelta.months <= 0 && ddelta.days <= 0 && tdelta.secs <= 0
        {
            Ok(Self { ddelta, tdelta })
        } else {
            Err(InitError::MixedSign)
        }
    }
}

impl Neg for DateTimeDelta {
    type Output = Self;

    fn neg(self) -> Self {
        Self {
            ddelta: -self.ddelta,
            tdelta: -self.tdelta,
        }
    }
}

pub(crate) const SINGLETONS: [(&str, DateTimeDelta); 1] = [(
    "ZERO\0",
    DateTimeDelta {
        ddelta: DateDelta { months: 0, days: 0 },
        tdelta: TimeDelta::from_secs_unchecked(0),
    },
)];

impl fmt::Display for DateTimeDelta {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        let DateTimeDelta { ddelta, tdelta } =
            if self.tdelta.secs < 0 || self.ddelta.months < 0 || self.ddelta.days < 0 {
                write!(f, "-P")?;
                -*self
            } else if self.tdelta.is_zero() && self.ddelta.is_zero() {
                return write!(f, "P0D");
            } else {
                write!(f, "P")?;
                *self
            };

        let mut s = String::with_capacity(8);
        if !ddelta.is_zero() {
            date_delta::format_components(ddelta, &mut s);
        }
        if !tdelta.is_zero() {
            s.push('T');
            time_delta::format_components(tdelta, &mut s);
        }
        f.write_str(&s)
    }
}

unsafe fn __new__(cls: *mut PyTypeObject, args: *mut PyObject, kwargs: *mut PyObject) -> PyReturn {
    let nargs = PyTuple_GET_SIZE(args);
    let nkwargs = if kwargs.is_null() {
        0
    } else {
        PyDict_Size(kwargs)
    };
    let mut months: i32 = 0;
    let mut days: i32 = 0;
    let mut nanos: i128 = 0;
    let &State {
        str_years,
        str_months,
        str_weeks,
        str_days,
        str_hours,
        str_minutes,
        str_seconds,
        str_microseconds,
        str_milliseconds,
        str_nanoseconds,
        ..
    } = State::for_type(cls);
    let delta = match (nargs, nkwargs) {
        (0, 0) => DateTimeDelta {
            ddelta: DateDelta { months: 0, days: 0 },
            tdelta: TimeDelta { secs: 0, nanos: 0 },
        }, // OPTIMIZE: return the singleton
        (0, _) => {
            let mut key: *mut PyObject = NULL();
            let mut value: *mut PyObject = NULL();
            let mut pos: Py_ssize_t = 0;
            while PyDict_Next(kwargs, &mut pos, &mut key, &mut value) != 0 {
                if key == str_years {
                    months = value
                        .to_long()?
                        .ok_or_else(|| value_error!("years must be an integer"))?
                        .checked_mul(12)
                        .and_then(|y| y.try_into().ok())
                        .and_then(|y| months.checked_add(y))
                        .ok_or_else(|| value_error!("total years out of range"))?;
                } else if key == str_months {
                    months = value
                        .to_long()?
                        .ok_or_else(|| value_error!("months must be an integer"))?
                        .try_into()
                        .ok()
                        .and_then(|m| months.checked_add(m))
                        .ok_or_else(|| value_error!("total months out of range"))?;
                } else if key == str_weeks {
                    days = value
                        .to_long()?
                        .ok_or_else(|| value_error!("weeks must be an integer"))?
                        .checked_mul(7)
                        .and_then(|d| d.try_into().ok())
                        .and_then(|d| days.checked_add(d))
                        .ok_or_else(|| value_error!("total days out of range"))?;
                } else if key == str_days {
                    days = value
                        .to_long()?
                        .ok_or_else(|| value_error!("days must be an integer"))?
                        .try_into()
                        .ok()
                        .and_then(|d| days.checked_add(d))
                        .ok_or_else(|| value_error!("total days out of range"))?;
                } else if key == str_hours {
                    nanos += handle_unit!(value, "hours", MAX_HOURS, 3_600_000_000_000_i128);
                } else if key == str_minutes {
                    nanos += handle_unit!(value, "minutes", MAX_MINUTES, 60_000_000_000_i128);
                } else if key == str_seconds {
                    nanos += handle_unit!(value, "seconds", MAX_SECS, 1_000_000_000_i128);
                } else if key == str_milliseconds {
                    nanos += handle_unit!(value, "milliseconds", MAX_MILLISECONDS, 1_000_000_i128);
                } else if key == str_microseconds {
                    nanos += handle_unit!(value, "microseconds", MAX_MICROSECONDS, 1_000_i128);
                } else if key == str_nanoseconds {
                    nanos += value
                        .to_i128()?
                        .ok_or_else(|| value_error!("nanoseconds must be an integer"))?;
                } else {
                    Err(type_error!(
                        "TimeDelta() got an unexpected keyword argument: %R",
                        key
                    ))?
                }
            }
            if months >= 0 && days >= 0 && nanos >= 0 || months <= 0 && days <= 0 && nanos <= 0 {
                DateTimeDelta {
                    ddelta: DateDelta::from_same_sign(months, days)
                        .ok_or_else(|| value_error!("Out of range"))?,
                    tdelta: TimeDelta::from_nanos(nanos)
                        .ok_or_else(|| value_error!("TimeDelta out of range"))?,
                }
            } else {
                Err(value_error!("Mixed sign in DateTimeDelta"))?
            }
        }
        _ => Err(type_error!("TimeDelta() takes no positional arguments"))?,
    };
    new_unchecked(cls, delta)
}

unsafe fn __richcmp__(a_obj: *mut PyObject, b_obj: *mut PyObject, op: c_int) -> PyReturn {
    Ok(newref(if Py_TYPE(b_obj) == Py_TYPE(a_obj) {
        let a = DateTimeDelta::extract(a_obj);
        let b = DateTimeDelta::extract(b_obj);
        match op {
            pyo3_ffi::Py_EQ => (a == b).to_py()?,
            pyo3_ffi::Py_NE => (a != b).to_py()?,
            _ => Py_NotImplemented(),
        }
    } else {
        Py_NotImplemented()
    }))
}

unsafe extern "C" fn __hash__(slf: *mut PyObject) -> Py_hash_t {
    hashmask(DateTimeDelta::extract(slf).pyhash())
}

unsafe fn __neg__(slf: *mut PyObject) -> PyReturn {
    new_unchecked(Py_TYPE(slf), -DateTimeDelta::extract(slf))
}

unsafe extern "C" fn __bool__(slf: *mut PyObject) -> c_int {
    let DateTimeDelta {
        ddelta: DateDelta { months, days },
        tdelta: TimeDelta { secs, nanos },
    } = DateTimeDelta::extract(slf);
    (months != 0 || days != 0 || secs != 0 || nanos != 0).into()
}

unsafe fn __repr__(slf: *mut PyObject) -> PyReturn {
    format!("DateTimeDelta({})", DateTimeDelta::extract(slf)).to_py()
}

unsafe fn __str__(slf: *mut PyObject) -> PyReturn {
    format!("{}", DateTimeDelta::extract(slf)).to_py()
}

unsafe fn __mul__(obj_a: *mut PyObject, obj_b: *mut PyObject) -> PyReturn {
    // This circus is because this method can also be called as __rmul__.
    let (delta_obj, factor) = if obj_a.is_int() {
        (obj_b, obj_a.to_long()?.unwrap())
    } else if obj_b.is_int() {
        (obj_a, obj_b.to_long()?.unwrap())
    } else {
        return Ok(newref(Py_NotImplemented()));
    };
    if factor == 1 {
        return Ok(newref(delta_obj));
    };
    let delta = DateTimeDelta::extract(delta_obj);
    // FUTURE: optimize zero delta case, zero factor case
    new_unchecked(
        Py_TYPE(delta_obj),
        i32::try_from(factor)
            .ok()
            .and_then(|f| delta.checked_mul(f))
            .ok_or_else(|| value_error!("Multiplication factor or result out of bounds"))?,
    )
}

unsafe fn __add__(a_obj: *mut PyObject, b_obj: *mut PyObject) -> PyReturn {
    _add_method(a_obj, b_obj, false)
}

unsafe fn __sub__(obj_a: *mut PyObject, obj_b: *mut PyObject) -> PyReturn {
    _add_method(obj_a, obj_b, true)
}

#[inline]
unsafe fn _add_method(obj_a: *mut PyObject, obj_b: *mut PyObject, negate: bool) -> PyReturn {
    // FUTURE: optimize zero cases
    let type_a = Py_TYPE(obj_a);
    let type_b = Py_TYPE(obj_b);
    // The easy case: DateTimeDelta + DateTimeDelta
    let (a, mut b) = if type_a == type_b {
        (DateTimeDelta::extract(obj_a), DateTimeDelta::extract(obj_b))
    // Other cases are more difficult, as they can be triggered
    // by reflexive operations with arbitrary types.
    // We need to eliminate them carefully.
    } else {
        let mod_a = PyType_GetModule(type_a);
        let mod_b = PyType_GetModule(type_b);
        if mod_a == mod_b {
            // at this point we know that `a` is a `DateTimeDelta`
            let state = State::for_mod(mod_a);
            let delta_a = DateTimeDelta::extract(obj_a);
            let delta_b = if type_b == state.date_delta_type {
                DateTimeDelta {
                    ddelta: DateDelta::extract(obj_b),
                    tdelta: TimeDelta::ZERO,
                }
            } else if type_b == state.time_delta_type {
                DateTimeDelta {
                    ddelta: DateDelta::ZERO,
                    tdelta: TimeDelta::extract(obj_b),
                }
            } else {
                return Err(type_error!(
                    "unsupported operand type(s) for +/-: %R and %R",
                    type_a,
                    type_b
                ));
            };
            (delta_a, delta_b)
        } else {
            return Ok(newref(Py_NotImplemented()));
        }
    };
    if negate {
        b = -b;
    };
    new_unchecked(
        type_a,
        a.checked_add(b).map_err(|e| match e {
            InitError::TooBig => value_error!("Addition result out of bounds"),
            InitError::MixedSign => value_error!("Mixed sign in DateTimeDelta"),
        })?,
    )
}

unsafe fn __abs__(slf: *mut PyObject) -> PyReturn {
    let DateTimeDelta { ddelta, tdelta } = DateTimeDelta::extract(slf);
    // FUTURE: optimize case where self is already positive
    new_unchecked(
        Py_TYPE(slf),
        DateTimeDelta {
            ddelta: ddelta.abs(),
            tdelta: tdelta.abs(),
        },
    )
}

static mut SLOTS: &[PyType_Slot] = &[
    slotmethod!(Py_tp_new, __new__),
    slotmethod!(Py_tp_richcompare, __richcmp__),
    slotmethod!(Py_nb_negative, __neg__, 1),
    slotmethod!(Py_tp_repr, __repr__, 1),
    slotmethod!(Py_tp_str, __str__, 1),
    slotmethod!(Py_nb_positive, identity1, 1),
    slotmethod!(Py_nb_absolute, __abs__, 1),
    slotmethod!(Py_nb_multiply, __mul__, 2),
    slotmethod!(Py_nb_add, __add__, 2),
    slotmethod!(Py_nb_subtract, __sub__, 2),
    PyType_Slot {
        slot: Py_tp_doc,
        pfunc: "A delta for calendar units\0".as_ptr() as *mut c_void,
    },
    PyType_Slot {
        slot: Py_tp_methods,
        pfunc: unsafe { METHODS.as_ptr() as *mut c_void },
    },
    PyType_Slot {
        slot: Py_tp_hash,
        pfunc: __hash__ as *mut c_void,
    },
    PyType_Slot {
        slot: Py_nb_bool,
        pfunc: __bool__ as *mut c_void,
    },
    PyType_Slot {
        slot: Py_tp_dealloc,
        pfunc: dealloc as *mut c_void,
    },
    PyType_Slot {
        slot: 0,
        pfunc: NULL(),
    },
];

unsafe fn default_format(slf: *mut PyObject, _: *mut PyObject) -> PyReturn {
    __str__(slf)
}

pub(crate) fn parse_date_components(s: &mut &[u8]) -> Option<DateDelta> {
    let mut months = 0;
    let mut days = 0;
    let mut prev_unit: Option<DateUnit> = None;

    while !s.is_empty() && s[0] != b'T' {
        if let Some((value, unit)) = date_delta::parse_component(s) {
            match (unit, prev_unit.replace(unit)) {
                (DateUnit::Years, None) => {
                    months += value * 12;
                }
                (DateUnit::Months, None | Some(DateUnit::Years)) => {
                    months += value;
                }
                (DateUnit::Weeks, None | Some(DateUnit::Years | DateUnit::Months)) => {
                    days += value * 7;
                }
                (DateUnit::Days, _) => {
                    days += value;
                    break;
                }
                _ => {
                    // i.e. the order of the components is wrong
                    return None;
                }
            }
        } else {
            // i.e. the component is invalid
            return None;
        }
    }
    Some(DateDelta { months, days })
}

unsafe fn from_default_format(cls: *mut PyObject, s_obj: *mut PyObject) -> PyReturn {
    let s = &mut s_obj
        .to_utf8()?
        .ok_or_else(|| type_error!("argument must be str"))?;
    if s.len() < 3 {
        // at least `P0D`
        Err(value_error!("Invalid format: %R", s_obj))?
    }

    let negated = parse_prefix(s).ok_or_else(|| value_error!("1 Invalid format: %R", s_obj))?;
    if s.len() < 2 {
        // This check prevents "empty" deltas without units, like `-PT`
        Err(value_error!("Invalid format: %R", s_obj))?
    }
    let mut ddelta = match parse_date_components(s) {
        Some(d) => d,
        None => Err(value_error!("2 Invalid format: %R", s_obj))?,
    };
    let mut tdelta = if s.is_empty() {
        TimeDelta::ZERO
    } else {
        *s = &s[1..];
        let (nanos, _) = match time_delta::parse_all_components(s) {
            Some(t) => t,
            None => Err(value_error!("3 Invalid format: %R", s_obj))?,
        };
        TimeDelta::from_nanos(nanos).ok_or_else(|| value_error!("TimeDelta out of range"))?
    };
    // TODO: ensure there's at least one component
    if negated {
        ddelta = -ddelta;
        tdelta = -tdelta;
    }
    new_unchecked(cls.cast(), DateTimeDelta { ddelta, tdelta })
}

unsafe fn in_months_days_secs_nanos(slf: *mut PyObject, _: *mut PyObject) -> PyReturn {
    let DateTimeDelta {
        ddelta: DateDelta { months, days },
        tdelta: TimeDelta { mut secs, nanos },
    } = DateTimeDelta::extract(slf);
    let signed_nanos = if secs < 0 && nanos > 0 {
        secs += 1;
        nanos as i32 - 1_000_000_000
    } else {
        nanos as i32
    };
    PyTuple_Pack(
        4,
        steal!(months.to_py()?),
        steal!(days.to_py()?),
        steal!(secs.to_py()?),
        steal!(signed_nanos.to_py()?),
    )
    .as_result()
}

unsafe fn date_part(slf: *mut PyObject, _: *mut PyObject) -> PyReturn {
    let DateTimeDelta { ddelta, .. } = DateTimeDelta::extract(slf);
    date_delta::new_unchecked(State::for_obj(slf).date_delta_type, ddelta)
}

unsafe fn time_part(slf: *mut PyObject, _: *mut PyObject) -> PyReturn {
    let DateTimeDelta { tdelta, .. } = DateTimeDelta::extract(slf);
    time_delta::new_unchecked(State::for_obj(slf).time_delta_type, tdelta)
}

unsafe fn __reduce__(slf: *mut PyObject, _: *mut PyObject) -> PyReturn {
    let DateTimeDelta {
        ddelta: DateDelta { months, days },
        tdelta: TimeDelta { secs, nanos },
    } = DateTimeDelta::extract(slf);
    PyTuple_Pack(
        2,
        State::for_type(Py_TYPE(slf)).unpickle_datetime_delta,
        // We don't do our own bit packing because the numbers are small
        // and Python's pickle protocol handles them more efficiently.
        steal!(PyTuple_Pack(
            4,
            steal!(months.to_py()?),
            steal!(days.to_py()?),
            steal!(secs.to_py()?),
            steal!(nanos.to_py()?)
        )
        .as_result()?),
    )
    .as_result()
}

pub(crate) unsafe fn unpickle(module: *mut PyObject, args: &[*mut PyObject]) -> PyReturn {
    if args.len() == 4 {
        new_unchecked(
            State::for_mod(module).datetime_delta_type,
            DateTimeDelta {
                ddelta: DateDelta {
                    months: args[0]
                        .to_long()?
                        .ok_or_else(|| type_error!("Invalid pickle data"))?
                        as _,
                    days: args[1]
                        .to_long()?
                        .ok_or_else(|| type_error!("Invalid pickle data"))?
                        as _,
                },
                tdelta: TimeDelta {
                    secs: args[2]
                        .to_long()?
                        .ok_or_else(|| type_error!("Invalid pickle data"))?
                        as _,
                    nanos: args[3]
                        .to_long()?
                        .ok_or_else(|| type_error!("Invalid pickle data"))?
                        as _,
                },
            },
        )
    } else {
        Err(type_error!("Invalid pickle data"))
    }
}

static mut METHODS: &[PyMethodDef] = &[
    // TODO: rename to method!
    method!(identity2 named "__copy__", ""),
    method!(identity2 named "__deepcopy__", "", METH_O),
    method!(default_format, ""),
    method!(default_format named "common_iso8601", "Return the ISO 8601 string representation"),
    method!(from_default_format, "", METH_O | METH_CLASS),
    method!(
        date_part,
        "Return the date part of the delta as a DateDelta"
    ),
    method!(
        time_part,
        "Return the time part of the delta as a TimeDelta"
    ),
    method!(
        from_default_format named "from_common_iso8601",
        "Parse from the common ISO8601 period format",
        METH_O | METH_CLASS
    ),
    method!(__reduce__, ""),
    method!(
        in_months_days_secs_nanos,
        "Extract the components of the delta"
    ),
    PyMethodDef::zeroed(),
];

pub(crate) unsafe fn new_unchecked(type_: *mut PyTypeObject, d: DateTimeDelta) -> PyReturn {
    let f: allocfunc = (*type_).tp_alloc.expect("tp_alloc is not set");
    let slf = f(type_, 0).cast::<PyDateTimeDelta>();
    if slf.is_null() {
        return Err(PyErrOccurred());
    }
    ptr::addr_of_mut!((*slf).data).write(d);
    Ok(slf.cast::<PyObject>().as_mut().unwrap())
}

pub(crate) static mut SPEC: PyType_Spec = PyType_Spec {
    name: c_str!("whenever.DateTimeDelta"),
    basicsize: mem::size_of::<PyDateTimeDelta>() as _,
    itemsize: 0,
    flags: Py_TPFLAGS_DEFAULT as _,
    slots: unsafe { SLOTS as *const [_] as *mut _ },
};
