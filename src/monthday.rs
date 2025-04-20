use core::ffi::{c_int, c_long, c_void, CStr};
use core::ptr::null_mut as NULL;
use pyo3_ffi::*;
use std::fmt::{self, Display, Formatter};

use crate::common::math::*;
use crate::common::*;
use crate::date::{extract_2_digits, Date};
use crate::docstrings as doc;
use crate::State;

#[derive(Debug, Eq, PartialEq, Ord, PartialOrd, Copy, Clone)]
pub(crate) struct MonthDay {
    pub(crate) month: Month,
    pub(crate) day: u8,
}

pub(crate) const SINGLETONS: &[(&CStr, MonthDay); 2] = &[
    (c"MIN", MonthDay::new_unchecked(Month::January, 1)),
    (c"MAX", MonthDay::new_unchecked(Month::December, 31)),
];

const LEAP_YEAR: Year = Year::new_unchecked(4);

impl MonthDay {
    pub(crate) const unsafe fn hash(self) -> i32 {
        ((self.month as i32) << 8) | self.day as i32
    }

    pub(crate) fn from_longs(m: c_long, d: c_long) -> Option<Self> {
        let month = Month::from_long(m)?;
        if d >= 1 && d <= LEAP_YEAR.days_in_month(month) as _ {
            Some(MonthDay { month, day: d as _ })
        } else {
            None
        }
    }

    pub(crate) const fn new(month: Month, day: u8) -> Option<Self> {
        if day > 0 && day <= LEAP_YEAR.days_in_month(month) {
            Some(MonthDay { month, day })
        } else {
            None
        }
    }

    pub(crate) const fn new_unchecked(month: Month, day: u8) -> Self {
        debug_assert!(day > 0 && day <= LEAP_YEAR.days_in_month(month));
        MonthDay { month, day }
    }

    pub(crate) fn parse(s: &[u8]) -> Option<Self> {
        if &s[..2] != b"--" {
            return None;
        }
        if s.len() == 7 && s[4] == b'-' {
            MonthDay::new(
                extract_2_digits(s, 2).and_then(Month::new)?,
                extract_2_digits(s, 5)?,
            )
        } else if s.len() == 6 {
            MonthDay::new(
                extract_2_digits(s, 2).and_then(Month::new)?,
                extract_2_digits(s, 4)?,
            )
        } else {
            None
        }
    }
}

impl PyWrapped for MonthDay {}

impl Display for MonthDay {
    fn fmt(&self, f: &mut Formatter<'_>) -> fmt::Result {
        write!(f, "--{:02}-{:02}", self.month.get(), self.day)
    }
}

unsafe fn __new__(cls: *mut PyTypeObject, args: *mut PyObject, kwargs: *mut PyObject) -> PyReturn {
    let mut month: c_long = 0;
    let mut day: c_long = 0;
    parse_args_kwargs!(args, kwargs, c"ll:MonthDay", month, day);
    MonthDay::from_longs(month, day)
        .ok_or_value_err("Invalid month/day component value")?
        .to_obj(cls)
}

unsafe fn __repr__(slf: *mut PyObject) -> PyReturn {
    format!("MonthDay({})", MonthDay::extract(slf)).to_py()
}

unsafe extern "C" fn __hash__(slf: *mut PyObject) -> Py_hash_t {
    MonthDay::extract(slf).hash() as Py_hash_t
}

unsafe fn __richcmp__(a_obj: *mut PyObject, b_obj: *mut PyObject, op: c_int) -> PyReturn {
    Ok(if Py_TYPE(b_obj) == Py_TYPE(a_obj) {
        let a = MonthDay::extract(a_obj);
        let b = MonthDay::extract(b_obj);
        match op {
            pyo3_ffi::Py_LT => a < b,
            pyo3_ffi::Py_LE => a <= b,
            pyo3_ffi::Py_EQ => a == b,
            pyo3_ffi::Py_NE => a != b,
            pyo3_ffi::Py_GT => a > b,
            pyo3_ffi::Py_GE => a >= b,
            _ => unreachable!(),
        }
        .to_py()?
    } else {
        newref(Py_NotImplemented())
    })
}

#[allow(static_mut_refs)]
static mut SLOTS: &[PyType_Slot] = &[
    slotmethod!(Py_tp_new, __new__),
    slotmethod!(Py_tp_str, __str__, 1),
    slotmethod!(Py_tp_repr, __repr__, 1),
    slotmethod!(Py_tp_richcompare, __richcmp__),
    PyType_Slot {
        slot: Py_tp_doc,
        pfunc: doc::MONTHDAY.as_ptr() as *mut c_void,
    },
    PyType_Slot {
        slot: Py_tp_methods,
        pfunc: unsafe { METHODS.as_ptr() as *mut c_void },
    },
    PyType_Slot {
        slot: Py_tp_getset,
        pfunc: unsafe { GETSETTERS.as_ptr() as *mut c_void },
    },
    PyType_Slot {
        slot: Py_tp_hash,
        pfunc: __hash__ as *mut c_void,
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

unsafe fn __str__(slf: *mut PyObject) -> PyReturn {
    format!("{}", MonthDay::extract(slf)).to_py()
}

unsafe fn format_common_iso(slf: *mut PyObject, _: *mut PyObject) -> PyReturn {
    __str__(slf)
}

unsafe fn parse_common_iso(cls: *mut PyObject, s: *mut PyObject) -> PyReturn {
    MonthDay::parse(s.to_utf8()?.ok_or_type_err("argument must be str")?)
        .ok_or_else_value_err(|| format!("Invalid format: {}", s.repr()))?
        .to_obj(cls.cast())
}

unsafe fn __reduce__(slf: *mut PyObject, _: *mut PyObject) -> PyReturn {
    let MonthDay { month, day } = MonthDay::extract(slf);
    (
        State::for_obj(slf).unpickle_monthday,
        steal!((steal!(pack![month.get(), day].to_py()?),).to_py()?),
    )
        .to_py()
}

unsafe fn replace(
    slf: *mut PyObject,
    cls: *mut PyTypeObject,
    args: &[*mut PyObject],
    kwargs: &mut KwargIter,
) -> PyReturn {
    let &State {
        str_month, str_day, ..
    } = State::for_type(cls);
    if !args.is_empty() {
        raise_type_err("replace() takes no positional arguments")
    } else {
        let md = MonthDay::extract(slf);
        let mut month = md.month.get().into();
        let mut day = md.day.into();
        handle_kwargs("replace", kwargs, |key, value, eq| {
            if eq(key, str_month) {
                month = value
                    .to_long()?
                    .ok_or_type_err("month must be an integer")?;
            } else if eq(key, str_day) {
                day = value.to_long()?.ok_or_type_err("day must be an integer")?;
            } else {
                return Ok(false);
            }
            Ok(true)
        })?;
        MonthDay::from_longs(month, day)
            .ok_or_value_err("Invalid month/day components")?
            .to_obj(cls)
    }
}

unsafe fn in_year(slf: *mut PyObject, year_obj: *mut PyObject) -> PyReturn {
    let &State { date_type, .. } = State::for_obj(slf);
    let MonthDay { month, day } = MonthDay::extract(slf);
    let year = Year::from_long(
        year_obj
            .to_long()?
            .ok_or_type_err("year must be an integer")?,
    )
    .ok_or_value_err("year out of range")?;
    // OPTIMIZE: we don't need to check the validity of the month again
    Date::new(year, month, day)
        .ok_or_value_err("Invalid date components")?
        .to_obj(date_type)
}

unsafe fn is_leap(slf: *mut PyObject, _: *mut PyObject) -> PyReturn {
    let MonthDay { month, day } = MonthDay::extract(slf);
    (day == 29 && month == Month::February).to_py()
}

static mut METHODS: &[PyMethodDef] = &[
    method!(__reduce__, c""),
    method!(identity2 named "__copy__", c""),
    method!(identity2 named "__deepcopy__", c"", METH_O),
    method!(format_common_iso, doc::MONTHDAY_FORMAT_COMMON_ISO),
    method!(
        parse_common_iso,
        doc::MONTHDAY_PARSE_COMMON_ISO,
        METH_O | METH_CLASS
    ),
    method!(in_year, doc::MONTHDAY_IN_YEAR, METH_O),
    method!(is_leap, doc::MONTHDAY_IS_LEAP),
    method_kwargs!(replace, doc::MONTHDAY_REPLACE),
    PyMethodDef::zeroed(),
];

pub(crate) unsafe fn unpickle(module: *mut PyObject, arg: *mut PyObject) -> PyReturn {
    let mut packed = arg.to_bytes()?.ok_or_type_err("Invalid pickle data")?;
    if packed.len() != 2 {
        raise_value_err("Invalid pickle data")?
    }
    MonthDay {
        month: Month::new_unchecked(unpack_one!(packed, u8)),
        day: unpack_one!(packed, u8),
    }
    .to_obj(State::for_mod(module).monthday_type)
}

unsafe fn get_month(slf: *mut PyObject) -> PyReturn {
    MonthDay::extract(slf).month.get().to_py()
}

unsafe fn get_day(slf: *mut PyObject) -> PyReturn {
    MonthDay::extract(slf).day.to_py()
}

static mut GETSETTERS: &[PyGetSetDef] = &[
    getter!(
        get_month named "month",
        "The month component"
    ),
    getter!(
        get_day named "day",
        "The day component"
    ),
    PyGetSetDef {
        name: NULL(),
        get: None,
        set: None,
        doc: NULL(),
        closure: NULL(),
    },
];

pub(crate) static mut SPEC: PyType_Spec =
    type_spec::<MonthDay>(c"whenever.MonthDay", unsafe { SLOTS });
