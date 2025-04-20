use core::ffi::{c_int, c_long, c_void, CStr};
use core::ptr::null_mut as NULL;
use pyo3_ffi::*;
use std::fmt::{self, Display, Formatter};

use crate::common::math::*;
use crate::common::*;
use crate::date::{extract_2_digits, extract_year, Date};
use crate::docstrings as doc;
use crate::State;

#[derive(Debug, Eq, PartialEq, Ord, PartialOrd, Copy, Clone)]
pub(crate) struct YearMonth {
    pub(crate) year: Year,
    pub(crate) month: Month,
}

pub(crate) const SINGLETONS: &[(&CStr, YearMonth); 2] = &[
    (c"MIN", YearMonth::new_unchecked(1, 1)),
    (c"MAX", YearMonth::new_unchecked(9999, 12)),
];

impl YearMonth {
    pub(crate) const fn new(year: Year, month: Month) -> Self {
        YearMonth { year, month }
    }

    pub(crate) const fn new_unchecked(year: u16, month: u8) -> Self {
        debug_assert!(year != 0);
        debug_assert!(year <= Year::MAX.get() as _);
        debug_assert!(month >= 1 && month <= 12);
        YearMonth {
            year: Year::new_unchecked(year),
            month: Month::new_unchecked(month),
        }
    }
    pub(crate) fn from_longs(y: c_long, m: c_long) -> Option<Self> {
        Some(YearMonth {
            year: Year::from_long(y)?,
            month: Month::from_long(m)?,
        })
    }

    pub(crate) const unsafe fn hash(self) -> i32 {
        ((self.year.get() as i32) << 4) | self.month as i32
    }

    pub(crate) fn parse(s: &[u8]) -> Option<Self> {
        if s.len() == 7 && s[4] == b'-' {
            Some(YearMonth::new(
                extract_year(s, 0)?,
                extract_2_digits(s, 5).and_then(Month::new)?,
            ))
        } else if s.len() == 6 {
            Some(YearMonth::new(
                extract_year(s, 0)?,
                extract_2_digits(s, 4).and_then(Month::new)?,
            ))
        } else {
            None
        }
    }
}

impl PyWrapped for YearMonth {}

impl Display for YearMonth {
    fn fmt(&self, f: &mut Formatter<'_>) -> fmt::Result {
        write!(f, "{:04}-{:02}", self.year.get(), self.month.get())
    }
}

unsafe fn __new__(cls: *mut PyTypeObject, args: *mut PyObject, kwargs: *mut PyObject) -> PyReturn {
    let mut year: c_long = 0;
    let mut month: c_long = 0;
    parse_args_kwargs!(args, kwargs, c"ll:YearMonth", year, month);
    YearMonth::from_longs(year, month)
        .ok_or_value_err("Invalid year/month component value")?
        .to_obj(cls)
}

unsafe fn __repr__(slf: *mut PyObject) -> PyReturn {
    format!("YearMonth({})", YearMonth::extract(slf)).to_py()
}

unsafe extern "C" fn __hash__(slf: *mut PyObject) -> Py_hash_t {
    YearMonth::extract(slf).hash() as Py_hash_t
}

unsafe fn __richcmp__(a_obj: *mut PyObject, b_obj: *mut PyObject, op: c_int) -> PyReturn {
    Ok(if Py_TYPE(b_obj) == Py_TYPE(a_obj) {
        let a = YearMonth::extract(a_obj);
        let b = YearMonth::extract(b_obj);
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
        pfunc: doc::YEARMONTH.as_ptr() as *mut c_void,
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
    format!("{}", YearMonth::extract(slf)).to_py()
}

unsafe fn format_common_iso(slf: *mut PyObject, _: *mut PyObject) -> PyReturn {
    __str__(slf)
}

unsafe fn parse_common_iso(cls: *mut PyObject, s: *mut PyObject) -> PyReturn {
    YearMonth::parse(s.to_utf8()?.ok_or_type_err("argument must be str")?)
        .ok_or_else_value_err(|| format!("Invalid format: {}", s.repr()))?
        .to_obj(cls.cast())
}

unsafe fn __reduce__(slf: *mut PyObject, _: *mut PyObject) -> PyReturn {
    let YearMonth { year, month } = YearMonth::extract(slf);
    (
        State::for_obj(slf).unpickle_yearmonth,
        steal!((steal!(pack![year.get(), month.get()].to_py()?),).to_py()?),
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
        str_year,
        str_month,
        ..
    } = State::for_type(cls);
    if !args.is_empty() {
        raise_type_err("replace() takes no positional arguments")
    } else {
        let ym = YearMonth::extract(slf);
        let mut year = ym.year.get().into();
        let mut month = ym.month.get().into();
        handle_kwargs("replace", kwargs, |key, value, eq| {
            if eq(key, str_year) {
                year = value.to_long()?.ok_or_type_err("year must be an integer")?;
            } else if eq(key, str_month) {
                month = value
                    .to_long()?
                    .ok_or_type_err("month must be an integer")?;
            } else {
                return Ok(false);
            }
            Ok(true)
        })?;
        YearMonth::from_longs(year, month)
            .ok_or_value_err("Invalid year/month components")?
            .to_obj(cls)
    }
}

unsafe fn on_day(slf: *mut PyObject, day_obj: *mut PyObject) -> PyReturn {
    let &State { date_type, .. } = State::for_obj(slf);
    let YearMonth { year, month } = YearMonth::extract(slf);
    let day = day_obj
        .to_long()?
        .ok_or_type_err("day must be an integer")?
        .try_into()
        .ok()
        .ok_or_value_err("day out of range")?;
    // OPTIMIZE: we don't need to check the validity of the year and month again
    Date::new(year, month, day)
        .ok_or_value_err("Invalid date components")?
        .to_obj(date_type)
}

static mut METHODS: &[PyMethodDef] = &[
    method!(identity2 named "__copy__", c""),
    method!(identity2 named "__deepcopy__", c"", METH_O),
    method!(__reduce__, c""),
    method!(format_common_iso, doc::YEARMONTH_FORMAT_COMMON_ISO),
    method!(
        parse_common_iso,
        doc::YEARMONTH_PARSE_COMMON_ISO,
        METH_O | METH_CLASS
    ),
    method!(on_day, doc::YEARMONTH_ON_DAY, METH_O),
    method_kwargs!(replace, doc::YEARMONTH_REPLACE),
    PyMethodDef::zeroed(),
];

pub(crate) unsafe fn unpickle(module: *mut PyObject, arg: *mut PyObject) -> PyReturn {
    let mut packed = arg.to_bytes()?.ok_or_type_err("Invalid pickle data")?;
    if packed.len() != 3 {
        raise_value_err("Invalid pickle data")?
    }
    YearMonth {
        year: Year::new_unchecked(unpack_one!(packed, u16)),
        month: Month::new_unchecked(unpack_one!(packed, u8)),
    }
    .to_obj(State::for_mod(module).yearmonth_type)
}

unsafe fn get_year(slf: *mut PyObject) -> PyReturn {
    YearMonth::extract(slf).year.get().to_py()
}

unsafe fn get_month(slf: *mut PyObject) -> PyReturn {
    YearMonth::extract(slf).month.get().to_py()
}

static mut GETSETTERS: &[PyGetSetDef] = &[
    getter!(
        get_year named "year",
        "The year component"
    ),
    getter!(
        get_month named "month",
        "The month component"
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
    type_spec::<YearMonth>(c"whenever.YearMonth", unsafe { SLOTS });
