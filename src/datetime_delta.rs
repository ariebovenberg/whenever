use core::ffi::{c_int, c_void, CStr};
use pyo3_ffi::*;
use std::fmt;
use std::ops::Neg;
use std::ptr::null_mut as NULL;

use crate::common::math::*;
use crate::common::*;
use crate::date_delta::{self, parse_prefix, DateDelta, InitError, Unit as DateUnit};
use crate::docstrings as doc;
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
        if ddelta.months.get() >= 0 && ddelta.days.get() >= 0 && tdelta.secs.get() >= 0
            || ddelta.months.get() <= 0 && ddelta.days.get() <= 0 && tdelta.secs.get() <= 0
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
            // Safe: multiplication can't result in different signs
            .map(|(ddelta, tdelta)| Self { ddelta, tdelta })
    }

    pub(crate) fn checked_add(self, other: Self) -> Result<Self, InitError> {
        let ddelta = self.ddelta.checked_add(other.ddelta)?;
        let tdelta = self
            .tdelta
            .checked_add(other.tdelta)
            .ok_or(InitError::TooBig)?;
        // Confirm the signs of date- and timedelta didn't get out of sync
        if ddelta.months.get() >= 0 && ddelta.days.get() >= 0 && tdelta.secs.get() >= 0
            || ddelta.months.get() <= 0 && ddelta.days.get() <= 0 && tdelta.secs.get() <= 0
        {
            Ok(Self { ddelta, tdelta })
        } else {
            Err(InitError::MixedSign)
        }
    }

    fn fmt_iso(self) -> String {
        let mut s = String::with_capacity(8);
        let DateTimeDelta { ddelta, tdelta } = if self.tdelta.secs.get() < 0
            || self.ddelta.months.get() < 0
            || self.ddelta.days.get() < 0
        {
            s.push('-');
            -self
        } else if self.tdelta.is_zero() && self.ddelta.is_zero() {
            return "P0D".to_string();
        } else {
            self
        };
        s.push('P');

        if !ddelta.is_zero() {
            date_delta::format_components(ddelta, &mut s);
        }
        if !tdelta.is_zero() {
            s.push('T');
            time_delta::fmt_components_abs(tdelta, &mut s);
        }
        s
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
            raise_value_err(format!("{} out of range", name))?
        }
    } else {
        let f = value
            .to_f64()?
            .ok_or_else_value_err(|| format!("{} must be an integer or float", name))?;
        if (-max as f64..=max as f64).contains(&f) {
            Ok((f * factor as f64) as i128)
        } else {
            raise_value_err(format!("{} out of range", name))?
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
        // A bit inefficient, but this isn't performance-critical
        let mut isofmt = self.fmt_iso().into_bytes();
        // Safe: we know the string is valid ASCII
        for c in isofmt.iter_mut().skip(2) {
            if *c != b'T' {
                *c = c.to_ascii_lowercase();
            }
        }
        f.write_str(unsafe { std::str::from_utf8_unchecked(&isofmt) })
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
            ddelta: DateDelta {
                months: DeltaMonths::ZERO,
                days: DeltaDays::ZERO,
            },
            tdelta: TimeDelta {
                secs: DeltaSeconds::ZERO,
                subsec: SubSecNanos::MIN,
            },
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
                    ddelta: DeltaMonths::new(months)
                        .zip(DeltaDays::new(days))
                        .map(|(m, d)| DateDelta { months: m, days: d })
                        .ok_or_value_err("Out of range")?,
                    tdelta: TimeDelta::from_nanos(nanos)
                        .ok_or_value_err("TimeDelta out of range")?,
                }
            } else {
                raise_value_err("Mixed sign in DateTimeDelta")?
            }
        }
        _ => raise_value_err("TimeDelta() takes no positional arguments")?,
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
    DateTimeDelta::extract(slf).fmt_iso().to_py()
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
                return raise_value_err(format!(
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
        .map_err(|e| {
            value_err(match e {
                InitError::TooBig => "Addition result out of bounds",
                InitError::MixedSign => "Mixed sign in DateTimeDelta",
            })
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

#[allow(static_mut_refs)]
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
        pfunc: doc::DATETIMEDELTA.as_ptr() as *mut c_void,
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
    DateTimeDelta::extract(slf).fmt_iso().to_py()
}

pub(crate) fn parse_date_components(s: &mut &[u8]) -> Option<DateDelta> {
    let mut months = 0;
    let mut days = 0;
    let mut prev_unit: Option<DateUnit> = None;

    while !s.is_empty() && !s[0].eq_ignore_ascii_case(&b'T') {
        let (value, unit) = date_delta::parse_component(s)?;
        match (unit, prev_unit.replace(unit)) {
            // Note: We prevent overflow by limiting how many digits we parse
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
    DeltaMonths::new(months)
        .zip(DeltaDays::new(days))
        .map(|(months, days)| DateDelta { months, days })
}

unsafe fn parse_common_iso(cls: *mut PyObject, s_obj: *mut PyObject) -> PyReturn {
    let s = &mut s_obj.to_utf8()?.ok_or_value_err("argument must be str")?;
    let err = || format!("Invalid format or out of range: {}", s_obj.repr());
    if s.len() < 3 {
        // at least `P0D`
        raise_value_err(err())?
    }

    let negated = parse_prefix(s).ok_or_else_value_err(err)?;
    // Safe: we checked the string is at least 3 bytes long
    if s[s.len() - 1].eq_ignore_ascii_case(&b'T') {
        // catch 'empty' cases
        raise_value_err(err())?
    }
    let mut ddelta = parse_date_components(s).ok_or_else_value_err(err)?;
    let mut tdelta = if s.is_empty() {
        TimeDelta::ZERO
    } else if s[0].eq_ignore_ascii_case(&b'T') {
        *s = &s[1..];
        let (nanos, _) = time_delta::parse_all_components(s).ok_or_else_value_err(err)?;
        TimeDelta::from_nanos(nanos).ok_or_else_value_err(err)?
    } else {
        raise_value_err(err())?
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
        tdelta: TimeDelta { secs, subsec },
    } = DateTimeDelta::extract(slf);
    let mut secs = secs.get();
    let nanos = if secs < 0 && subsec.get() > 0 {
        secs += 1;
        subsec.get() - 1_000_000_000
    } else {
        subsec.get()
    };
    (
        steal!(months.get().to_py()?),
        steal!(days.get().to_py()?),
        steal!(secs.to_py()?),
        steal!(nanos.to_py()?),
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
        tdelta: TimeDelta { secs, subsec },
    } = DateTimeDelta::extract(slf);
    (
        State::for_type(Py_TYPE(slf)).unpickle_datetime_delta,
        // We don't do our own bit packing because the numbers are usually small
        // and Python's pickle protocol handles them more efficiently.
        steal!((
            steal!(months.get().to_py()?),
            steal!(days.get().to_py()?),
            steal!(secs.get().to_py()?),
            steal!(subsec.get().to_py()?)
        )
            .to_py()?),
    )
        .to_py()
}

pub(crate) unsafe fn unpickle(module: *mut PyObject, args: &[*mut PyObject]) -> PyReturn {
    match args {
        &[months, days, secs, nanos] => DateTimeDelta {
            ddelta: DateDelta {
                months: DeltaMonths::new_unchecked(
                    months.to_long()?.ok_or_type_err("Invalid pickle data")? as _,
                ),
                days: DeltaDays::new_unchecked(
                    days.to_long()?.ok_or_type_err("Invalid pickle data")? as _,
                ),
            },
            tdelta: TimeDelta {
                secs: DeltaSeconds::new_unchecked(
                    secs.to_long()?.ok_or_type_err("Invalid pickle data")? as _,
                ),
                subsec: SubSecNanos::new_unchecked(
                    nanos.to_long()?.ok_or_type_err("Invalid pickle data")? as _,
                ),
            },
        }
        .to_obj(State::for_mod(module).datetime_delta_type),
        _ => raise_type_err("Invalid pickle data")?,
    }
}

static mut METHODS: &[PyMethodDef] = &[
    method!(identity2 named "__copy__", c""),
    method!(identity2 named "__deepcopy__", c"", METH_O),
    method!(format_common_iso, doc::DATETIMEDELTA_FORMAT_COMMON_ISO),
    method!(date_part, doc::DATETIMEDELTA_DATE_PART),
    method!(time_part, doc::DATETIMEDELTA_TIME_PART),
    method!(
        parse_common_iso,
        doc::DATETIMEDELTA_PARSE_COMMON_ISO,
        METH_O | METH_CLASS
    ),
    method!(__reduce__, c""),
    method!(
        in_months_days_secs_nanos,
        doc::DATETIMEDELTA_IN_MONTHS_DAYS_SECS_NANOS
    ),
    PyMethodDef::zeroed(),
];

pub(crate) static mut SPEC: PyType_Spec =
    type_spec::<DateTimeDelta>(c"whenever.DateTimeDelta", unsafe { SLOTS });
