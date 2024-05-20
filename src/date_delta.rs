use core::ffi::{c_int, c_long, c_void};
use core::{mem, ptr};
use pyo3_ffi::*;
use std::cmp::min;
use std::fmt;
use std::ops::Neg;
use std::ptr::null_mut as NULL;

use crate::common::*;
use crate::date::MAX_YEAR;
use crate::datetime_delta;
use crate::datetime_delta::DateTimeDelta;
use crate::time_delta::TimeDelta;
use crate::State;

#[derive(Debug, Eq, PartialEq, Copy, Clone)]
pub(crate) struct DateDelta {
    // invariant: these never have opposite signs
    pub(crate) months: i32,
    pub(crate) days: i32,
}

#[repr(C)]
pub(crate) struct PyDateDelta {
    _ob_base: PyObject,
    data: DateDelta,
}

pub(crate) enum InitError {
    TooBig,
    MixedSign,
}

impl DateDelta {
    pub(crate) fn extract(obj: *mut PyObject) -> DateDelta {
        unsafe { (*obj.cast::<PyDateDelta>()).data }
    }

    #[cfg(target_pointer_width = "32")]
    pub(crate) fn pyhash(self) -> Py_hash_t {
        hashmask(self.months as Py_hash_t ^ self.days as Py_hash_t)
    }

    #[cfg(target_pointer_width = "64")]
    pub(crate) fn pyhash(self) -> Py_hash_t {
        hashmask(self.months as Py_hash_t | (self.days as Py_hash_t) << 32)
    }

    pub(crate) fn new(months: i32, days: i32) -> Result<Self, InitError> {
        match (months.signum(), days.signum()) {
            (0, 0) => Ok(Self { months: 0, days: 0 }),
            (1, -1) | (-1, 1) => Err(InitError::MixedSign),
            (1 | 0, 1 | 0) => Ok(Self {
                months: (months < MAX_MONTHS)
                    .then_some(months)
                    .ok_or(InitError::TooBig)?,
                days: (days < MAX_DAYS).then_some(days).ok_or(InitError::TooBig)?,
            }),
            (-1 | 0, -1 | 0) => Ok(Self {
                months: (-months < MAX_MONTHS)
                    .then_some(months)
                    .ok_or(InitError::TooBig)?,
                days: (-days < MAX_DAYS)
                    .then_some(days)
                    .ok_or(InitError::TooBig)?,
            }),
            _ => unreachable!(),
        }
    }

    pub(crate) fn from_longs(months: c_long, days: c_long) -> Result<Self, InitError> {
        match (months.signum(), days.signum()) {
            (0, 0) => Ok(Self { months: 0, days: 0 }),
            (1, -1) | (-1, 1) => Err(InitError::MixedSign),
            (1 | 0, 1 | 0) => Ok(Self {
                months: (months < MAX_MONTHS as _)
                    .then_some(months as _)
                    .ok_or(InitError::TooBig)?,
                days: (days < MAX_DAYS as _)
                    .then_some(days as _)
                    .ok_or(InitError::TooBig)?,
            }),
            (-1 | 0, -1 | 0) => Ok(Self {
                months: (-months < MAX_MONTHS as _)
                    .then_some(months as _)
                    .ok_or(InitError::TooBig)?,
                days: (-days < MAX_DAYS as _)
                    .then_some(days as _)
                    .ok_or(InitError::TooBig)?,
            }),
            _ => unreachable!(),
        }
    }

    pub(crate) fn from_same_sign(months: i32, days: i32) -> Option<Self> {
        debug_assert!(months >= 0 && days >= 0 || months <= 0 && days <= 0);
        (months.abs() < MAX_MONTHS && days.abs() < MAX_DAYS).then_some(Self { months, days })
    }

    pub(crate) fn from_months(months: i32) -> Option<Self> {
        (months.abs() < MAX_MONTHS).then_some(Self { months, days: 0 })
    }

    pub(crate) fn from_days(days: i32) -> Option<Self> {
        (days.abs() < MAX_DAYS).then_some(Self { months: 0, days })
    }

    pub(crate) fn checked_mul(self, factor: i32) -> Option<Self> {
        let Self { months, days } = self;
        months
            .checked_mul(factor)
            .zip(days.checked_mul(factor))
            .and_then(|(months, days)| Self::from_same_sign(months, days))
    }

    pub(crate) fn checked_add(self, other: Self) -> Result<Self, InitError> {
        Self::new(self.months + other.months, self.days + other.days)
    }

    pub(crate) const fn is_zero(self) -> bool {
        self.months == 0 && self.days == 0
    }

    pub(crate) fn abs(self) -> Self {
        Self {
            months: self.months.abs(),
            days: self.days.abs(),
        }
    }

    pub(crate) const ZERO: Self = Self { months: 0, days: 0 };
}

impl Neg for DateDelta {
    type Output = Self;

    fn neg(self) -> Self {
        Self {
            months: -self.months,
            days: -self.days,
        }
    }
}

const MAX_MONTHS: i32 = (MAX_YEAR * 12) as i32;
const MAX_DAYS: i32 = (MAX_YEAR * 366) as i32;

pub(crate) const SINGLETONS: [(&str, DateDelta); 1] =
    [("ZERO\0", DateDelta { months: 0, days: 0 })];

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

pub(crate) fn format_components(delta: DateDelta, s: &mut String) -> () {
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

unsafe fn __new__(cls: *mut PyTypeObject, args: *mut PyObject, kwargs: *mut PyObject) -> PyReturn {
    let mut years: c_long = 0;
    let mut months: c_long = 0;
    let mut weeks: c_long = 0;
    let mut days: c_long = 0;

    // FUTURE: parse them manually, which is more efficient
    if PyArg_ParseTupleAndKeywords(
        args,
        kwargs,
        c_str!("|$llll:DateDelta"),
        vec![
            c_str!("years") as *mut _,
            c_str!("months") as *mut _,
            c_str!("weeks") as *mut _,
            c_str!("days") as *mut _,
            NULL(),
        ]
        .as_mut_ptr(),
        &mut years,
        &mut months,
        &mut weeks,
        &mut days,
    ) == 0
    {
        return Err(PyErrOccurred());
    }
    match years
        .checked_mul(12)
        .and_then(|m| m.checked_add(months))
        .zip(weeks.checked_mul(7).and_then(|d| d.checked_add(days)))
        .ok_or(InitError::TooBig)
        .and_then(|(m, d)| DateDelta::from_longs(m, d))
    {
        Ok(delta) => new_unchecked(cls, delta),
        Err(InitError::TooBig) => Err(value_error!("DateDelta out of bounds")),
        Err(InitError::MixedSign) => Err(value_error!("Mixed sign in DateDelta")),
    }
}

pub(crate) unsafe fn years(module: *mut PyObject, amount: *mut PyObject) -> PyReturn {
    new_unchecked(
        State::for_mod(module).date_delta_type,
        amount
            .to_long()?
            .ok_or_else(|| type_error!("argument must be int"))?
            .checked_mul(12)
            .and_then(|m| i32::try_from(m).ok())
            .and_then(DateDelta::from_months)
            .ok_or_else(|| value_error!("value out of bounds"))?,
    )
}

pub(crate) unsafe fn months(module: *mut PyObject, amount: *mut PyObject) -> PyReturn {
    new_unchecked(
        State::for_mod(module).date_delta_type,
        i32::try_from(
            amount
                .to_long()?
                .ok_or_else(|| type_error!("argument must be int"))?,
        )
        .ok()
        .and_then(DateDelta::from_months)
        .ok_or_else(|| value_error!("value out of bounds"))?,
    )
}

pub(crate) unsafe fn weeks(module: *mut PyObject, amount: *mut PyObject) -> PyReturn {
    new_unchecked(
        State::for_mod(module).date_delta_type,
        amount
            .to_long()?
            .ok_or_else(|| type_error!("argument must be int"))?
            .checked_mul(7)
            .and_then(|d| i32::try_from(d).ok())
            .and_then(DateDelta::from_days)
            .ok_or_else(|| value_error!("value out of bounds"))?,
    )
}

// TODO: test bounds errors
pub(crate) unsafe fn days(module: *mut PyObject, amount: *mut PyObject) -> PyReturn {
    new_unchecked(
        State::for_mod(module).date_delta_type,
        i32::try_from(
            amount
                .to_long()?
                .ok_or_else(|| type_error!("argument must be int"))?,
        )
        .ok()
        .and_then(DateDelta::from_days)
        .ok_or_else(|| value_error!("value out of bounds"))?,
    )
}

unsafe fn richcmp(a_obj: *mut PyObject, b_obj: *mut PyObject, op: c_int) -> PyReturn {
    Ok(newref(if Py_TYPE(b_obj) == Py_TYPE(a_obj) {
        let a = DateDelta::extract(a_obj);
        let b = DateDelta::extract(b_obj);
        match op {
            pyo3_ffi::Py_EQ => (a == b).to_py().unwrap(),
            pyo3_ffi::Py_NE => (a != b).to_py().unwrap(),
            _ => Py_NotImplemented(),
        }
    } else {
        Py_NotImplemented()
    }))
}

unsafe extern "C" fn __hash__(slf: *mut PyObject) -> Py_hash_t {
    DateDelta::extract(slf).pyhash()
}

unsafe fn __neg__(slf: *mut PyObject) -> PyReturn {
    new_unchecked(Py_TYPE(slf), -DateDelta::extract(slf))
}

unsafe extern "C" fn __bool__(slf: *mut PyObject) -> c_int {
    let DateDelta { months, days } = DateDelta::extract(slf);
    (months != 0 || days != 0).into()
}

unsafe fn __repr__(slf: *mut PyObject) -> PyReturn {
    format!("DateDelta({})", DateDelta::extract(slf)).to_py()
}

unsafe fn __str__(slf: *mut PyObject) -> PyReturn {
    format!("{}", DateDelta::extract(slf)).to_py()
}

unsafe fn __mul__(obj_a: *mut PyObject, obj_b: *mut PyObject) -> PyReturn {
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

unsafe fn __sub__(a_obj: *mut PyObject, b_obj: *mut PyObject) -> PyReturn {
    _add_method(a_obj, b_obj, true)
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
        new_unchecked(
            type_a,
            a.checked_add(b).map_err(|e| match e {
                InitError::TooBig => value_error!("Addition result out of bounds"),
                InitError::MixedSign => value_error!("Mixed sign in DateDelta"),
            })?,
        )
    } else {
        let mod_a = PyType_GetModule(type_a);
        let mod_b = PyType_GetModule(type_b);
        if mod_a == mod_b {
            // at this point we know that `a` is a DateDelta
            let state = State::for_mod(mod_a);
            let delta_a = DateDelta::extract(obj_a);
            let result = if type_b == state.time_delta_type {
                let mut b = TimeDelta::extract(obj_b);
                if negate {
                    b = -b;
                }
                DateTimeDelta::new(delta_a, b)
                    .ok_or_else(|| value_error!("Mixed sign in DateTimeDelta"))?
            } else if type_b == state.datetime_delta_type {
                let mut b = DateTimeDelta::extract(obj_b);
                if negate {
                    b = -b;
                }
                b.checked_add(DateTimeDelta {
                    ddelta: delta_a,
                    tdelta: TimeDelta::ZERO,
                })
                .map_err(|e| match e {
                    InitError::TooBig => value_error!("Addition result out of bounds"),
                    InitError::MixedSign => value_error!("Mixed sign in DateTimeDelta"),
                })?
            } else {
                return Err(type_error!(
                    "unsupported operand type(s) for +/-: %R and %R",
                    type_a,
                    type_b
                ));
            };
            datetime_delta::new_unchecked(state.datetime_delta_type, result)
        } else {
            return Ok(newref(Py_NotImplemented()));
        }
    }
}

unsafe fn __abs__(slf: *mut PyObject) -> PyReturn {
    let DateDelta { months, days } = DateDelta::extract(slf);
    if months >= 0 && days >= 0 {
        Ok(newref(slf))
    } else {
        new_unchecked(
            Py_TYPE(slf),
            DateDelta {
                months: -months,
                days: -days,
            },
        )
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
    // We limit parsing to 7 digits to prevent overflow
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

// parse a component of a ISO8601 duration, e.g. `6Y`, `-56M`, `+2W`, `0D`
pub(crate) fn parse_component(s: &mut &[u8]) -> Option<(i32, Unit)> {
    if s.len() >= 2 && s[0].is_ascii_digit() {
        finish_parsing_component(s, (s[0] - b'0').into())
    } else {
        None
    }
}

unsafe fn from_default_format(cls: *mut PyObject, s_obj: *mut PyObject) -> PyReturn {
    let s = &mut s_obj
        .to_utf8()?
        .ok_or_else(|| type_error!("argument must be str"))?;
    if s.len() < 3 {
        // at least `P0D`
        Err(value_error!("Invalid format: %R", s_obj))?
    }
    let mut months = 0;
    let mut days = 0;
    let mut prev_unit: Option<Unit> = None;

    let negated = parse_prefix(s).ok_or_else(|| value_error!("Invalid format: %R", s_obj))?;

    while !s.is_empty() {
        if let Some((value, unit)) = parse_component(s) {
            match (unit, prev_unit.replace(unit)) {
                // Note: overflows are prevented by limiting the number
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
                    Err(value_error!("Invalid format: %R", s_obj))?;
                }
                _ => {
                    // i.e. the order of the components is wrong
                    Err(value_error!("Invalid format: %R", s_obj))?;
                }
            }
        } else {
            // i.e. the component is invalid
            Err(value_error!("Invalid format: %R", s_obj))?;
        }
    }

    // i.e. there must be at least one component (`P` alone is invalid)
    if prev_unit.is_none() {
        Err(value_error!("Invalid date delta format: %R", s_obj))?;
    }

    if negated {
        months *= -1;
        days *= -1;
    }
    new_unchecked(cls.cast(), DateDelta { months, days })
}

unsafe fn in_months_days(slf: *mut PyObject, _: *mut PyObject) -> PyReturn {
    let DateDelta { months, days } = DateDelta::extract(slf);
    PyTuple_Pack(2, steal!(months.to_py()?), steal!(days.to_py()?)).as_result()
}

unsafe fn in_years_months_days(slf: *mut PyObject, _: *mut PyObject) -> PyReturn {
    let DateDelta { months, days } = DateDelta::extract(slf);
    let years = months / 12;
    let months = months % 12;
    PyTuple_Pack(
        3,
        steal!(years.to_py()?),
        steal!(months.to_py()?),
        steal!(days.to_py()?),
    )
    .as_result()
}

unsafe fn __reduce__(slf: *mut PyObject, _: *mut PyObject) -> PyReturn {
    let DateDelta { months, days } = DateDelta::extract(slf);
    PyTuple_Pack(
        2,
        State::for_type(Py_TYPE(slf)).unpickle_date_delta,
        steal!(PyTuple_Pack(2, steal!(months.to_py()?), steal!(days.to_py()?)).as_result()?),
    )
    .as_result()
}

pub(crate) unsafe fn unpickle(module: *mut PyObject, args: &[*mut PyObject]) -> PyReturn {
    if args.len() == 2 {
        new_unchecked(
            State::for_mod(module).date_delta_type,
            DateDelta {
                months: args[0]
                    .to_long()?
                    .ok_or_else(|| type_error!("Invalid pickle data"))?
                    as _,
                days: args[1]
                    .to_long()?
                    .ok_or_else(|| type_error!("Invalid pickle data"))? as _,
            },
        )
    } else {
        Err(type_error!("Invalid pickle data"))
    }
}

static mut METHODS: &[PyMethodDef] = &[
    method!(identity2 named "__copy__", ""),
    method!(identity2 named "__deepcopy__", "", METH_O),
    method!(default_format, ""),
    method!(default_format named "common_iso8601", "Return the ISO 8601 string representation"),
    method!(from_default_format, "", METH_O | METH_CLASS),
    method!(
        from_default_format named "from_common_iso8601",
        "Parse from the common ISO8601 period format",
        METH_O | METH_CLASS
    ),
    method!(
        in_months_days,
        "Return the date delta as a tuple of months and days"
    ),
    method!(
        in_years_months_days,
        "Return the date delta as a tuple of years, months, and days"
    ),
    method!(__reduce__, ""),
    PyMethodDef::zeroed(),
];

pub(crate) unsafe fn new_unchecked(type_: *mut PyTypeObject, d: DateDelta) -> PyReturn {
    let f: allocfunc = (*type_).tp_alloc.expect("tp_alloc is not set");
    let slf = f(type_, 0).cast::<PyDateDelta>();
    if slf.is_null() {
        return Err(PyErrOccurred());
    }
    ptr::addr_of_mut!((*slf).data).write(d);
    Ok(slf.cast::<PyObject>().as_mut().unwrap())
}

pub(crate) static mut SPEC: PyType_Spec = PyType_Spec {
    name: c_str!("whenever.DateDelta"),
    basicsize: mem::size_of::<PyDateDelta>() as _,
    itemsize: 0,
    flags: Py_TPFLAGS_DEFAULT as _,
    slots: unsafe { SLOTS as *const [_] as *mut _ },
};
