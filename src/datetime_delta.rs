use core::ffi::{c_int, c_void, CStr};
use core::mem;
use pyo3_ffi::*;
use std::fmt;
use std::ops::Neg;
use std::ptr::null_mut as NULL;

use crate::common::*;
use crate::date_delta::{self, parse_prefix, DateDelta, InitError, Unit as DateUnit};
use crate::time_delta::{
    self, TimeDelta, MAX_HOURS, MAX_MICROSECONDS, MAX_MILLISECONDS, MAX_MINUTES, MAX_SECS,
};
use crate::State;

#[derive(Debug, Eq, PartialEq, Copy, Clone)]
pub(crate) struct DateTimeDelta {
    // invariant: these never have opposite signs
    pub(crate) ddelta: DateDelta,
    pub(crate) tdelta: TimeDelta,
}

impl DateTimeDelta {
    pub(crate) fn pyhash(self) -> Py_hash_t {
        hash_combine(self.ddelta.pyhash(), self.tdelta.pyhash())
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

impl PyWrapped for DateTimeDelta {}

impl Neg for DateTimeDelta {
    type Output = Self;

    fn neg(self) -> Self {
        Self {
            ddelta: -self.ddelta,
            tdelta: -self.tdelta,
        }
    }
}

#[inline]
pub(crate) unsafe fn handle_exact_unit(
    value: *mut PyObject,
    max: i64,
    name: &str,
    factor: i128,
) -> PyResult<i128> {
    if value.is_int() {
        let i = value
            .to_i64()?
            // Safe to unwrap since we just checked that it's an int
            .unwrap();
        if (-max..=max).contains(&i) {
            Ok(i as i128 * factor)
        } else {
            Err(value_err!("{} out of range", name))?
        }
    } else {
        let f = value
            .to_f64()?
            .ok_or_else(|| value_err!("{} must be an integer or float", name))?;
        if (-max as f64..=max as f64).contains(&f) {
            Ok((f * factor as f64) as i128)
        } else {
            Err(value_err!("{} out of range", name))?
        }
    }
}

// OPTIMIZE: a version for cases in which days are a fixed amount of nanos
#[inline]
pub(crate) unsafe fn set_units_from_kwargs(
    key: *mut PyObject,
    value: *mut PyObject,
    months: &mut i32,
    days: &mut i32,
    nanos: &mut i128,
    state: &State,
    eq: fn(*mut PyObject, *mut PyObject) -> bool,
) -> PyResult<bool> {
    if eq(key, state.str_years) {
        *months = value
            .to_long()?
            .ok_or_value_err("years must be an integer")?
            .checked_mul(12)
            .and_then(|y| y.try_into().ok())
            .and_then(|y| months.checked_add(y))
            .ok_or_value_err("total years out of range")?;
    } else if eq(key, state.str_months) {
        *months = value
            .to_long()?
            .ok_or_value_err("months must be an integer")?
            .try_into()
            .ok()
            .and_then(|m| months.checked_add(m))
            .ok_or_value_err("total months out of range")?;
    } else if eq(key, state.str_weeks) {
        *days = value
            .to_long()?
            .ok_or_value_err("weeks must be an integer")?
            .checked_mul(7)
            .and_then(|d| d.try_into().ok())
            .and_then(|d| days.checked_add(d))
            .ok_or_value_err("total days out of range")?;
    } else if eq(key, state.str_days) {
        *days = value
            .to_long()?
            .ok_or_value_err("days must be an integer")?
            .try_into()
            .ok()
            .and_then(|d| days.checked_add(d))
            .ok_or_value_err("total days out of range")?;
    } else if eq(key, state.str_hours) {
        *nanos += handle_exact_unit(value, MAX_HOURS, "hours", 3_600_000_000_000_i128)?;
    } else if eq(key, state.str_minutes) {
        *nanos += handle_exact_unit(value, MAX_MINUTES, "minutes", 60_000_000_000_i128)?;
    } else if eq(key, state.str_seconds) {
        *nanos += handle_exact_unit(value, MAX_SECS, "seconds", 1_000_000_000_i128)?;
    } else if eq(key, state.str_milliseconds) {
        *nanos += handle_exact_unit(value, MAX_MILLISECONDS, "milliseconds", 1_000_000_i128)?;
    } else if eq(key, state.str_microseconds) {
        *nanos += handle_exact_unit(value, MAX_MICROSECONDS, "microseconds", 1_000_i128)?;
    } else if eq(key, state.str_nanoseconds) {
        *nanos = value
            .to_i128()?
            .ok_or_value_err("nanoseconds must be an integer")?
            .checked_add(*nanos)
            .ok_or_value_err("total nanoseconds out of range")?;
    } else {
        return Ok(false);
    }
    Ok(true)
}

pub(crate) const SINGLETONS: &[(&CStr, DateTimeDelta); 1] = &[(
    c"ZERO",
    DateTimeDelta {
        ddelta: DateDelta::ZERO,
        tdelta: TimeDelta::ZERO,
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
    let state = State::for_type(cls);
    match (nargs, nkwargs) {
        (0, 0) => DateTimeDelta {
            ddelta: DateDelta { months: 0, days: 0 },
            tdelta: TimeDelta { secs: 0, nanos: 0 },
        }, // OPTIMIZE: return the singleton
        (0, _) => {
            handle_kwargs(
                "DateTimeDelta",
                DictItems::new_unchecked(kwargs),
                |key, value, eq| {
                    set_units_from_kwargs(key, value, &mut months, &mut days, &mut nanos, state, eq)
                },
            )?;
            if months >= 0 && days >= 0 && nanos >= 0 || months <= 0 && days <= 0 && nanos <= 0 {
                DateTimeDelta {
                    ddelta: DateDelta::from_same_sign(months, days)
                        .ok_or_value_err("Out of range")?,
                    tdelta: TimeDelta::from_nanos(nanos)
                        .ok_or_value_err("TimeDelta out of range")?,
                }
            } else {
                Err(value_err!("Mixed sign in DateTimeDelta"))?
            }
        }
        _ => Err(value_err!("TimeDelta() takes no positional arguments"))?,
    }
    .to_obj(cls)
}

unsafe fn __richcmp__(a_obj: *mut PyObject, b_obj: *mut PyObject, op: c_int) -> PyReturn {
    Ok(if Py_TYPE(b_obj) == Py_TYPE(a_obj) {
        let a = DateTimeDelta::extract(a_obj);
        let b = DateTimeDelta::extract(b_obj);
        match op {
            pyo3_ffi::Py_EQ => (a == b).to_py()?,
            pyo3_ffi::Py_NE => (a != b).to_py()?,
            _ => newref(Py_NotImplemented()),
        }
    } else {
        newref(Py_NotImplemented())
    })
}

unsafe extern "C" fn __hash__(slf: *mut PyObject) -> Py_hash_t {
    hashmask(DateTimeDelta::extract(slf).pyhash())
}

unsafe fn __neg__(slf: *mut PyObject) -> PyReturn {
    (-DateTimeDelta::extract(slf)).to_obj(Py_TYPE(slf))
}

unsafe extern "C" fn __bool__(slf: *mut PyObject) -> c_int {
    let DateTimeDelta { ddelta, tdelta } = DateTimeDelta::extract(slf);
    (!(ddelta.is_zero() && tdelta.is_zero())).into()
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
    i32::try_from(factor)
        .ok()
        .and_then(|f| delta.checked_mul(f))
        .ok_or_value_err("Multiplication factor or result out of bounds")?
        .to_obj(Py_TYPE(delta_obj))
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
            let state = State::for_mod(mod_a);
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
                // We can safely discount other types within our module
                return Err(value_err!(
                    "unsupported operand type(s) for +/-: {} and {}",
                    (type_a as *mut PyObject).repr(),
                    (type_b as *mut PyObject).repr()
                ));
            };
            debug_assert_eq!(type_a, state.datetime_delta_type);
            (DateTimeDelta::extract(obj_a), delta_b)
        } else {
            return Ok(newref(Py_NotImplemented()));
        }
    };
    if negate {
        b = -b;
    };
    a.checked_add(b)
        .map_err(|e| match e {
            InitError::TooBig => value_err!("Addition result out of bounds"),
            InitError::MixedSign => value_err!("Mixed sign in DateTimeDelta"),
        })?
        .to_obj(type_a)
}

unsafe fn __abs__(slf: *mut PyObject) -> PyReturn {
    let DateTimeDelta { ddelta, tdelta } = DateTimeDelta::extract(slf);
    // FUTURE: optimize case where self is already positive
    DateTimeDelta {
        ddelta: ddelta.abs(),
        tdelta: tdelta.abs(),
    }
    .to_obj(Py_TYPE(slf))
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
        pfunc: c"A delta for calendar and exact units".as_ptr() as *mut c_void,
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
        pfunc: generic_dealloc as *mut c_void,
    },
    PyType_Slot {
        slot: 0,
        pfunc: NULL(),
    },
];

unsafe fn format_common_iso(slf: *mut PyObject, _: *mut PyObject) -> PyReturn {
    __str__(slf)
}

pub(crate) fn parse_date_components(s: &mut &[u8]) -> Option<DateDelta> {
    let mut months = 0;
    let mut days = 0;
    let mut prev_unit: Option<DateUnit> = None;

    while !s.is_empty() && s[0] != b'T' {
        let (value, unit) = date_delta::parse_component(s)?;
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
            _ => None?, // i.e. the order of the components is wrong
        }
    }
    Some(DateDelta { months, days })
}

unsafe fn parse_common_iso(cls: *mut PyObject, s_obj: *mut PyObject) -> PyReturn {
    let s = &mut s_obj.to_utf8()?.ok_or_value_err("argument must be str")?;
    let raise = || value_err!("Invalid format: {}", s_obj.repr());
    if s.len() < 3 {
        // at least `P0D`
        Err(raise())?
    }

    let negated = parse_prefix(s).ok_or_else(raise)?;
    if s[s.len() - 1] == b'T' {
        // catch 'empty' cases
        Err(raise())?
    }
    let mut ddelta = parse_date_components(s).ok_or_else(raise)?;
    let mut tdelta = if s.is_empty() {
        TimeDelta::ZERO
    } else {
        *s = &s[1..];
        let (nanos, _) = time_delta::parse_all_components(s).ok_or_else(raise)?;
        TimeDelta::from_nanos(nanos).ok_or_value_err("TimeDelta out of range")?
    };
    if negated {
        ddelta = -ddelta;
        tdelta = -tdelta;
    }
    DateTimeDelta { ddelta, tdelta }.to_obj(cls.cast())
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
    (
        steal!(months.to_py()?),
        steal!(days.to_py()?),
        steal!(secs.to_py()?),
        steal!(signed_nanos.to_py()?),
    )
        .to_py()
}

unsafe fn date_part(slf: *mut PyObject, _: *mut PyObject) -> PyReturn {
    DateTimeDelta::extract(slf)
        .ddelta
        .to_obj(State::for_obj(slf).date_delta_type)
}

unsafe fn time_part(slf: *mut PyObject, _: *mut PyObject) -> PyReturn {
    DateTimeDelta::extract(slf)
        .tdelta
        .to_obj(State::for_obj(slf).time_delta_type)
}

unsafe fn __reduce__(slf: *mut PyObject, _: *mut PyObject) -> PyReturn {
    let DateTimeDelta {
        ddelta: DateDelta { months, days },
        tdelta: TimeDelta { secs, nanos },
    } = DateTimeDelta::extract(slf);
    (
        State::for_type(Py_TYPE(slf)).unpickle_datetime_delta,
        // We don't do our own bit packing because the numbers are small
        // and Python's pickle protocol handles them more efficiently.
        steal!((
            steal!(months.to_py()?),
            steal!(days.to_py()?),
            steal!(secs.to_py()?),
            steal!(nanos.to_py()?)
        )
            .to_py()?),
    )
        .to_py()
}

pub(crate) unsafe fn unpickle(module: *mut PyObject, args: &[*mut PyObject]) -> PyReturn {
    match args {
        &[months, days, secs, nanos] => DateTimeDelta {
            ddelta: DateDelta {
                months: months.to_long()?.ok_or_type_err("Invalid pickle data")? as _,
                days: days.to_long()?.ok_or_type_err("Invalid pickle data")? as _,
            },
            tdelta: TimeDelta {
                secs: secs.to_long()?.ok_or_type_err("Invalid pickle data")? as _,
                nanos: nanos.to_long()?.ok_or_type_err("Invalid pickle data")? as _,
            },
        }
        .to_obj(State::for_mod(module).datetime_delta_type),
        _ => Err(type_err!("Invalid pickle data"))?,
    }
}

static mut METHODS: &[PyMethodDef] = &[
    method!(identity2 named "__copy__", ""),
    method!(identity2 named "__deepcopy__", "", METH_O),
    method!(format_common_iso, "Format as common ISO8601 period"),
    method!(
        date_part,
        "Return the date part of the delta as a DateDelta"
    ),
    method!(
        time_part,
        "Return the time part of the delta as a TimeDelta"
    ),
    method!(
        parse_common_iso,
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

type_spec!(DateTimeDelta, SLOTS);
