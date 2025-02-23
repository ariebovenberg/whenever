use core::ffi::{c_int, c_long, c_void, CStr};
use core::mem;
use pyo3_ffi::*;
use std::cmp::min;
use std::fmt;
use std::ops::Neg;
use std::ptr::null_mut as NULL;

use crate::common::*;
use crate::date::MAX_YEAR;
use crate::datetime_delta::DateTimeDelta;
use crate::docstrings as doc;
use crate::time_delta::TimeDelta;
use crate::State;

#[derive(Debug, Eq, PartialEq, Copy, Clone)]
pub(crate) struct DateDelta {
    // invariant: these never have opposite signs
    pub(crate) months: i32,
    pub(crate) days: i32,
}

pub(crate) enum InitError {
    TooBig,
    MixedSign,
}

impl DateDelta {
    #[cfg(target_pointer_width = "32")]
    pub(crate) fn pyhash(self) -> Py_hash_t {
        hash_combine(self.months as Py_hash_t, self.days as Py_hash_t)
    }

    #[cfg(target_pointer_width = "64")]
    pub(crate) fn pyhash(self) -> Py_hash_t {
        self.months as Py_hash_t | (self.days as Py_hash_t) << 32
    }

    pub(crate) fn new(months: i32, days: i32) -> Result<Self, InitError> {
        match same_sign(months, days) {
            false => Err(InitError::MixedSign),
            true => Ok(Self::from_same_sign(months, days).ok_or(InitError::TooBig)?),
        }
    }

    pub(crate) fn from_same_sign(months: i32, days: i32) -> Option<Self> {
        debug_assert!(same_sign(months, days));
        (in_range(months, MAX_MONTHS) && in_range(days, MAX_DAYS)).then_some(Self { months, days })
    }

    pub(crate) fn from_months(months: i32) -> Option<Self> {
        in_range(months, MAX_MONTHS).then_some(Self { months, days: 0 })
    }

    pub(crate) fn from_days(days: i32) -> Option<Self> {
        in_range(days, MAX_DAYS).then_some(Self { months: 0, days })
    }

    pub(crate) fn checked_mul(self, factor: i32) -> Option<Self> {
        let Self { months, days } = self;
        months
            .checked_mul(factor)
            .zip(days.checked_mul(factor))
            .and_then(|(months, days)| Self::from_same_sign(months, days))
    }

    pub(crate) fn checked_add(self, other: Self) -> Result<Self, InitError> {
        // The maths won't overflow due to the ranges;
        // the constructor will check the rest.
        Self::new(self.months + other.months, self.days + other.days)
    }

    pub(crate) const fn is_zero(self) -> bool {
        self.months == 0 && self.days == 0
    }

    pub(crate) fn abs(self) -> Self {
        Self {
            // Arithmetic overflow is impossible due to the ranges
            months: self.months.abs(),
            days: self.days.abs(),
        }
    }

    pub(crate) const ZERO: Self = Self { months: 0, days: 0 };
}

impl PyWrapped for DateDelta {}

impl Neg for DateDelta {
    type Output = Self;

    fn neg(self) -> Self {
        Self {
            // Arithmetic overflow is impossible due to the ranges
            months: -self.months,
            days: -self.days,
        }
    }
}

fn same_sign(months: i32, days: i32) -> bool {
    months >= 0 && days >= 0 || months <= 0 && days <= 0
}

pub(crate) const MAX_MONTHS: i32 = (MAX_YEAR * 12) as _;
pub(crate) const MAX_DAYS: i32 = (MAX_YEAR * 366) as _;

pub(crate) const SINGLETONS: &[(&CStr, DateDelta); 1] = &[(c"ZERO", DateDelta::ZERO)];

impl fmt::Display for DateDelta {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        let &Self { months, days } = self;
        let delta = if months < 0 || days < 0 {
            write!(f, "-P")?;
            -*self
        } else if months == 0 && days == 0 {
            return write!(f, "P0D");
        } else {
            write!(f, "P")?;
            *self
        };
        let s = &mut String::with_capacity(8);
        format_components(delta, s);
        f.write_str(s)?;
        Ok(())
    }
}

// NOTE: delta must be positive
pub(crate) fn format_components(delta: DateDelta, s: &mut String) {
    let DateDelta { mut months, days } = delta;
    debug_assert!(months >= 0 && days >= 0);
    debug_assert!(months > 0 || days > 0);
    let years = months / 12;
    months %= 12;
    if years != 0 {
        s.push_str(&format!("{}Y", years));
    }
    if months != 0 {
        s.push_str(&format!("{}M", months));
    }
    if days != 0 {
        s.push_str(&format!("{}D", days));
    }
}

// NOTE: while in range, the signs may be mixed
pub(crate) unsafe fn handle_init_kwargs<T>(
    fname: &str,
    kwargs: T,
    str_years: *mut PyObject,
    str_months: *mut PyObject,
    str_days: *mut PyObject,
    str_weeks: *mut PyObject,
) -> PyResult<(i32, i32)>
where
    T: IntoIterator<Item = (*mut PyObject, *mut PyObject)>,
{
    let mut days: c_long = 0;
    let mut months: c_long = 0;
    handle_kwargs(fname, kwargs, |key, value, eq| {
        if eq(key, str_days) {
            days = value
                .to_long()?
                .ok_or_type_err("days must be an integer")?
                .checked_add(days)
                .ok_or_value_err("days out of range")?;
        } else if eq(key, str_months) {
            months = value
                .to_long()?
                .ok_or_type_err("months must be an integer")?
                .checked_add(months)
                .ok_or_value_err("months out of range")?;
        } else if eq(key, str_years) {
            months = value
                .to_long()?
                .ok_or_type_err("years must be an integer")?
                .checked_mul(12)
                .and_then(|m| m.checked_add(months))
                .ok_or_value_err("years out of range")?;
        } else if eq(key, str_weeks) {
            days = value
                .to_long()?
                .ok_or_type_err("weeks must be an integer")?
                .checked_mul(7)
                .and_then(|d| d.checked_add(days))
                .ok_or_value_err("weeks out of range")?;
        } else {
            return Ok(false);
        }
        Ok(true)
    })?;
    Ok((
        clamp(months, MAX_MONTHS).ok_or_value_err("months out of range")?,
        clamp(days, MAX_DAYS).ok_or_value_err("days out of range")?,
    ))
}

unsafe fn __new__(cls: *mut PyTypeObject, args: *mut PyObject, kwargs: *mut PyObject) -> PyReturn {
    if PyTuple_GET_SIZE(args) != 0 {
        return Err(type_err!("DateDelta() takes no positional arguments"));
    }
    let &State {
        str_years,
        str_months,
        str_days,
        str_weeks,
        ..
    } = State::for_type(cls);
    match DictItems::new(kwargs) {
        None => DateDelta::ZERO,
        Some(items) => {
            let (months, days) = handle_init_kwargs(
                "DateDelta",
                items,
                str_years,
                str_months,
                str_days,
                str_weeks,
            )?;
            same_sign(months, days)
                .then_some(DateDelta { months, days })
                .ok_or_value_err("Mixed sign in DateDelta")?
        }
    }
    .to_obj(cls)
}

pub(crate) unsafe fn years(module: *mut PyObject, amount: *mut PyObject) -> PyReturn {
    amount
        .to_long()?
        .ok_or_type_err("argument must be int")?
        .checked_mul(12)
        .and_then(|m| i32::try_from(m).ok())
        .and_then(DateDelta::from_months)
        .ok_or_value_err("value out of bounds")?
        .to_obj(State::for_mod(module).date_delta_type)
}

pub(crate) unsafe fn months(module: *mut PyObject, amount: *mut PyObject) -> PyReturn {
    i32::try_from(amount.to_long()?.ok_or_type_err("argument must be int")?)
        .ok()
        .and_then(DateDelta::from_months)
        .ok_or_value_err("value out of bounds")?
        .to_obj(State::for_mod(module).date_delta_type)
}

pub(crate) unsafe fn weeks(module: *mut PyObject, amount: *mut PyObject) -> PyReturn {
    amount
        .to_long()?
        .ok_or_type_err("argument must be int")?
        .checked_mul(7)
        .and_then(|d| i32::try_from(d).ok())
        .and_then(DateDelta::from_days)
        .ok_or_value_err("value out of bounds")?
        .to_obj(State::for_mod(module).date_delta_type)
}

pub(crate) unsafe fn days(module: *mut PyObject, amount: *mut PyObject) -> PyReturn {
    i32::try_from(amount.to_long()?.ok_or_type_err("argument must be int")?)
        .ok()
        .and_then(DateDelta::from_days)
        .ok_or_value_err("value out of bounds")?
        .to_obj(State::for_mod(module).date_delta_type)
}

unsafe fn richcmp(a_obj: *mut PyObject, b_obj: *mut PyObject, op: c_int) -> PyReturn {
    Ok(if Py_TYPE(b_obj) == Py_TYPE(a_obj) {
        let a = DateDelta::extract(a_obj);
        let b = DateDelta::extract(b_obj);
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
    hashmask(DateDelta::extract(slf).pyhash())
}

unsafe fn __neg__(slf: *mut PyObject) -> PyReturn {
    (-DateDelta::extract(slf)).to_obj(Py_TYPE(slf))
}

unsafe extern "C" fn __bool__(slf: *mut PyObject) -> c_int {
    (!DateDelta::extract(slf).is_zero()).into()
}

unsafe fn __repr__(slf: *mut PyObject) -> PyReturn {
    format!("DateDelta({})", DateDelta::extract(slf)).to_py()
}

unsafe fn __str__(slf: *mut PyObject) -> PyReturn {
    format!("{}", DateDelta::extract(slf)).to_py()
}

unsafe fn __mul__(obj_a: *mut PyObject, obj_b: *mut PyObject) -> PyReturn {
    // These checks are needed because the args could be reversed!
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
    let delta = DateDelta::extract(delta_obj);
    // FUTURE: optimize zero delta case
    i32::try_from(factor)
        .ok()
        .and_then(|f| delta.checked_mul(f))
        .ok_or_value_err("Multiplication factor or result out of bounds")?
        .to_obj(Py_TYPE(delta_obj))
}

unsafe fn __add__(obj_a: *mut PyObject, obj_b: *mut PyObject) -> PyReturn {
    _add_method(obj_a, obj_b, false)
}

unsafe fn __sub__(obj_a: *mut PyObject, obj_b: *mut PyObject) -> PyReturn {
    _add_method(obj_a, obj_b, true)
}

#[inline]
unsafe fn _add_method(obj_a: *mut PyObject, obj_b: *mut PyObject, negate: bool) -> PyReturn {
    let type_a = Py_TYPE(obj_a);
    let type_b = Py_TYPE(obj_b);

    // The easy case: both are DateDelta
    if type_a == type_b {
        let a = DateDelta::extract(obj_a);
        let mut b = DateDelta::extract(obj_b);
        if negate {
            b = -b;
        }
        a.checked_add(b)
            .map_err(|e| match e {
                InitError::TooBig => value_err!("Addition result out of bounds"),
                InitError::MixedSign => value_err!("Mixed sign in DateDelta"),
            })?
            .to_obj(type_a)
    } else {
        let mod_a = PyType_GetModule(type_a);
        let mod_b = PyType_GetModule(type_b);
        if mod_a == mod_b {
            let state = State::for_mod(mod_a);
            if type_b == state.time_delta_type {
                let mut b = TimeDelta::extract(obj_b);
                if negate {
                    b = -b;
                }
                DateTimeDelta::new(DateDelta::extract(obj_a), b)
                    .ok_or_value_err("Mixed sign in DateTimeDelta")?
            } else if type_b == state.datetime_delta_type {
                let mut b = DateTimeDelta::extract(obj_b);
                if negate {
                    b = -b;
                }
                b.checked_add(DateTimeDelta {
                    ddelta: DateDelta::extract(obj_a),
                    tdelta: TimeDelta::ZERO,
                })
                .map_err(|e| match e {
                    InitError::TooBig => value_err!("Addition result out of bounds"),
                    InitError::MixedSign => value_err!("Mixed sign in DateTimeDelta"),
                })?
            } else {
                Err(type_err!(
                    "unsupported operand type(s) for +/-: {} and {}",
                    (type_a as *mut PyObject).repr(),
                    (type_b as *mut PyObject).repr()
                ))?
            }
            .to_obj(state.datetime_delta_type)
        } else {
            return Ok(newref(Py_NotImplemented()));
        }
    }
}

unsafe fn __abs__(slf: *mut PyObject) -> PyReturn {
    let DateDelta { months, days } = DateDelta::extract(slf);
    // Optimization: don't allocate a new object if the delta is already positive
    if months >= 0 && days >= 0 {
        Ok(newref(slf))
    } else {
        DateDelta {
            // No overflow is possible due to the ranges
            months: -months,
            days: -days,
        }
        .to_obj(Py_TYPE(slf))
    }
}

static mut SLOTS: &[PyType_Slot] = &[
    slotmethod!(Py_tp_new, __new__),
    slotmethod!(Py_tp_richcompare, richcmp),
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
        pfunc: doc::DATEDELTA.as_ptr() as *mut c_void,
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

// parse the prefix of an ISO8601 duration, e.g. `P`, `-P`, `+P`,
pub(crate) fn parse_prefix(s: &mut &[u8]) -> Option<bool> {
    debug_assert!(s.len() >= 2);
    match s[0] {
        b'P' => {
            let result = Some(false);
            *s = &s[1..];
            result
        }
        b'-' if s[1] == b'P' => {
            let result = Some(true);
            *s = &s[2..];
            result
        }
        b'+' if s[1] == b'P' => {
            let result = Some(false);
            *s = &s[2..];
            result
        }
        _ => None,
    }
}

#[derive(Debug, PartialEq, Eq, PartialOrd, Ord, Copy, Clone)]
pub(crate) enum Unit {
    Years,
    Months,
    Weeks,
    Days,
}

fn finish_parsing_component(s: &mut &[u8], mut value: i32) -> Option<(i32, Unit)> {
    // We limit parsing to a number of digits to prevent overflow
    for i in 1..min(s.len(), 7) {
        match s[i] {
            c if c.is_ascii_digit() => value = value * 10 + i32::from(c - b'0'),
            b'D' => {
                *s = &s[i + 1..];
                return Some((value, Unit::Days));
            }
            b'W' => {
                *s = &s[i + 1..];
                return Some((value, Unit::Weeks));
            }
            b'M' => {
                *s = &s[i + 1..];
                return Some((value, Unit::Months));
            }
            b'Y' => {
                *s = &s[i + 1..];
                return Some((value, Unit::Years));
            }
            _ => {
                return None;
            }
        }
    }
    None
}

// parse a component of a ISO8601 duration, e.g. `6Y`, `56M`, `2W`, `0D`
pub(crate) fn parse_component(s: &mut &[u8]) -> Option<(i32, Unit)> {
    if s.len() >= 2 && s[0].is_ascii_digit() {
        finish_parsing_component(s, (s[0] - b'0').into())
    } else {
        None
    }
}

unsafe fn parse_common_iso(cls: *mut PyObject, s_obj: *mut PyObject) -> PyReturn {
    let s = &mut s_obj.to_utf8()?.ok_or_type_err("argument must be str")?;
    let raise = || value_err!("Invalid format: {}", s_obj.repr());
    if s.len() < 3 {
        // at least `P0D`
        Err(raise())?
    }
    let mut months = 0;
    let mut days = 0;
    let mut prev_unit: Option<Unit> = None;

    let negated = parse_prefix(s).ok_or_else(raise)?;

    while !s.is_empty() {
        let (value, unit) = parse_component(s).ok_or_else(raise)?;
        match (unit, prev_unit.replace(unit)) {
            // NOTE: overflows are prevented by limiting the number
            // of digits that are parsed.
            (Unit::Years, None) => {
                months += value * 12;
            }
            (Unit::Months, None | Some(Unit::Years)) => {
                months += value;
            }
            (Unit::Weeks, None | Some(Unit::Years | Unit::Months)) => {
                days += value * 7;
            }
            (Unit::Days, _) => {
                days += value;
                if s.is_empty() {
                    break;
                }
                // i.e. there's more after the days component
                Err(raise())?;
            }
            _ => {
                // i.e. the order of the components is wrong
                Err(raise())?;
            }
        }
    }

    // i.e. there must be at least one component (`P` alone is invalid)
    if prev_unit.is_none() {
        Err(raise())?;
    }

    if negated {
        months = -months;
        days = -days;
    }
    DateDelta::from_same_sign(months, days)
        .ok_or_value_err("DateDelta out of range")?
        .to_obj(cls.cast())
}

unsafe fn in_months_days(slf: *mut PyObject, _: *mut PyObject) -> PyReturn {
    let DateDelta { months, days } = DateDelta::extract(slf);
    (steal!(months.to_py()?), steal!(days.to_py()?)).to_py()
}

unsafe fn in_years_months_days(slf: *mut PyObject, _: *mut PyObject) -> PyReturn {
    let DateDelta { months, days } = DateDelta::extract(slf);
    let years = months / 12;
    let months = months % 12;
    (
        steal!(years.to_py()?),
        steal!(months.to_py()?),
        steal!(days.to_py()?),
    )
        .to_py()
}

unsafe fn __reduce__(slf: *mut PyObject, _: *mut PyObject) -> PyReturn {
    let DateDelta { months, days } = DateDelta::extract(slf);
    (
        State::for_type(Py_TYPE(slf)).unpickle_date_delta,
        steal!((steal!(months.to_py()?), steal!(days.to_py()?)).to_py()?),
    )
        .to_py()
}

pub(crate) unsafe fn unpickle(module: *mut PyObject, args: &[*mut PyObject]) -> PyReturn {
    if args.len() == 2 {
        DateDelta {
            months: args[0].to_long()?.ok_or_type_err("Invalid pickle data")? as _,
            days: args[1].to_long()?.ok_or_type_err("Invalid pickle data")? as _,
        }
        .to_obj(State::for_mod(module).date_delta_type)
    } else {
        Err(type_err!("Invalid pickle data"))
    }
}

static mut METHODS: &[PyMethodDef] = &[
    method!(identity2 named "__copy__", c""),
    method!(identity2 named "__deepcopy__", c"", METH_O),
    method!(format_common_iso, doc::DATEDELTA_FORMAT_COMMON_ISO),
    method!(
        parse_common_iso,
        doc::DATEDELTA_PARSE_COMMON_ISO,
        METH_O | METH_CLASS
    ),
    method!(in_months_days, doc::DATEDELTA_IN_MONTHS_DAYS),
    method!(in_years_months_days, doc::DATEDELTA_IN_YEARS_MONTHS_DAYS),
    method!(__reduce__, c""),
    PyMethodDef::zeroed(),
];

type_spec!(DateDelta, SLOTS);
