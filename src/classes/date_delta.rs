use core::ffi::{CStr, c_int, c_void};
use pyo3_ffi::*;
use std::ptr::null_mut as NULL;

pub(crate) use crate::domain::date_delta::{DateDelta, InitError};

use crate::{
    classes::{datetime_delta::DateTimeDelta, time_delta::TimeDelta},
    common::{scalar::*, shift::parse_calendar_shift_kwargs},
    docstrings as doc,
    domain::shift::CalendarShift,
    py::*,
    pymodule::State,
};

impl DateDelta {
    pub(crate) fn python_hash(self) -> Py_hash_t {
        #[cfg(target_pointer_width = "64")]
        {
            self.months.get() as Py_hash_t | ((self.days.get() as Py_hash_t) << 32)
        }
        #[cfg(target_pointer_width = "32")]
        {
            hash_combine(self.months.get() as Py_hash_t, self.days.get() as Py_hash_t)
        }
    }
}

impl PyPayload for DateDelta {}

pub(crate) const SINGLETONS: &[(&CStr, DateDelta); 1] = &[(c"ZERO", DateDelta::ZERO)];

fn __new__(cls: PyClass<DateDelta>, args: PyTuple, kwargs: Option<PyDict>) -> PyReturn {
    let state = cls.state();
    warn_with_class(
        *state.warn_deprecation,
        c"DateDelta is deprecated; use ItemizedDateDelta instead.",
        1,
    )?;
    match args.len() {
        0 => {}
        1 if kwargs.map_or(0, |s| s.len()) == 0 => {
            return parse_iso_inner(cls, args.iter().next().unwrap());
        }
        _ => {
            return raise_type_err(
                "DateDelta() takes at either 1 positional argument or only keyword arguments",
            );
        }
    }
    match kwargs {
        None => DateDelta::ZERO,
        Some(kwarg_dict) => {
            let CalendarShift { months, days } =
                parse_calendar_shift_kwargs("DateDelta", kwarg_dict.iteritems(), state)?;
            DateDelta::new(months, days).ok_or_value_err("mixed sign in DateDelta")?
        }
    }
    .to_obj(cls)
}

pub(crate) fn years(state: &State, amount: PyObj) -> PyReturn {
    warn_with_class(
        *state.warn_deprecation,
        c"years() is deprecated; use ItemizedDateDelta instead.",
        1,
    )?;
    amount
        .expect_int("argument")?
        .to_long()?
        .checked_mul(12)
        .and_then(DeltaMonths::from_long)
        .map(DateDelta::from_months)
        .ok_or_range_err()?
        .to_obj(*state.date_delta_type)
}

pub(crate) fn months(state: &State, amount: PyObj) -> PyReturn {
    warn_with_class(
        *state.warn_deprecation,
        c"months() is deprecated; use ItemizedDateDelta instead.",
        1,
    )?;
    DeltaMonths::from_long(amount.expect_int("argument")?.to_long()?)
        .map(DateDelta::from_months)
        .ok_or_range_err()?
        .to_obj(*state.date_delta_type)
}

pub(crate) fn weeks(state: &State, amount: PyObj) -> PyReturn {
    warn_with_class(
        *state.warn_deprecation,
        c"weeks() is deprecated; use ItemizedDateDelta instead.",
        1,
    )?;
    amount
        .expect_int("argument")?
        .to_long()?
        .checked_mul(7)
        .and_then(DeltaDays::from_long)
        .map(DateDelta::from_days)
        .ok_or_range_err()?
        .to_obj(*state.date_delta_type)
}

pub(crate) fn days(state: &State, amount: PyObj) -> PyReturn {
    warn_with_class(
        *state.warn_deprecation,
        c"days() is deprecated; use ItemizedDateDelta instead.",
        1,
    )?;
    DeltaDays::from_long(amount.expect_int("argument")?.to_long()?)
        .map(DateDelta::from_days)
        .ok_or_range_err()?
        .to_obj(*state.date_delta_type)
}

fn __richcmp__(cls: PyClass<DateDelta>, a: DateDelta, b_obj: PyObj, op: c_int) -> PyReturn {
    match b_obj.extract(cls) {
        Some(b) => match op {
            pyo3_ffi::Py_EQ => a == b,
            pyo3_ffi::Py_NE => a != b,
            _ => return not_implemented(),
        }
        .to_py(),
        None => not_implemented(),
    }
}

fn __neg__(cls: PyClass<DateDelta>, d: DateDelta) -> PyReturn {
    (-d).to_obj(cls)
}

fn __repr__(_: PyType, d: DateDelta) -> PyReturn {
    format!("DateDelta(\"{d}\")").to_py()
}

fn __str__(_: PyType, d: DateDelta) -> PyReturn {
    d.fmt_iso().to_py()
}

fn __mul__(a: PyObj, b: PyObj) -> PyReturn {
    // These checks are needed because the args could be reversed.
    let (delta_obj, factor) = if let Some(i) = b.cast_allow_subclass::<PyInt>() {
        (a, i.to_long()?)
    } else if let Some(i) = a.cast_allow_subclass::<PyInt>() {
        (b, i.to_long()?)
    } else {
        return not_implemented();
    };

    if factor == 1 {
        return Ok(delta_obj.newref());
    }

    // SAFETY: one operand is a DateDelta and the other is an int.
    let (delta_type, delta) = unsafe { delta_obj.assume_heaptype::<DateDelta>() };
    i32::try_from(factor)
        .ok()
        .and_then(|f| delta.mul(f))
        .ok_or_range_err()?
        .to_obj(delta_type)
}

fn __add__(obj_a: PyObj, obj_b: PyObj) -> PyReturn {
    add_method(obj_a, obj_b, false)
}

fn __sub__(obj_a: PyObj, obj_b: PyObj) -> PyReturn {
    add_method(obj_a, obj_b, true)
}

#[inline(never)]
fn add_method(obj_a: PyObj, obj_b: PyObj, negate: bool) -> PyReturn {
    binary_operation::<DateDelta>(obj_a, obj_b, if negate { "-" } else { "+" }, |operands| {
        match operands {
            BinaryCall::SameType { cls, slf, other } => {
                let mut other = *other;
                if negate {
                    other = -other;
                }
                Ok(Some(
                    slf.add(other)
                        .map_err(|e| {
                            value_err(match e {
                                InitError::TooBig => "Addition result out of bounds",
                                InitError::MixedSign => "mixed sign in DateDelta",
                            })
                        })?
                        .to_obj(cls)?,
                ))
            }
            BinaryCall::ExtTypes { cls, slf, other } => {
                let state = cls.state();
                let result = match_type!(
                    other,
                    *state.time_delta_type => |mut tdelta| {
                        if negate {
                            tdelta = -tdelta;
                        }
                        warn_with_class(
                            *state.warn_deprecation,
                            c"DateTimeDelta is deprecated; use ItemizedDelta instead.",
                            1,
                        )?;
                        DateTimeDelta::new(*slf, tdelta)
                            .ok_or_value_err("mixed sign in delta")?
                    },
                    *state.datetime_delta_type => |mut dtdelta| {
                        if negate {
                            dtdelta = -dtdelta;
                        }
                        dtdelta
                            .add(DateTimeDelta {
                                date: *slf,
                                time: TimeDelta::ZERO,
                            })
                            .map_err(|e| {
                                value_err(match e {
                                    InitError::TooBig => "Addition result out of bounds",
                                    InitError::MixedSign => "mixed sign in DateTimeDelta",
                                })
                            })?
                    },
                    _ => { return Ok(None) },
                );
                Ok(Some(result.to_obj(*state.datetime_delta_type)?))
            }
            BinaryCall::OtherTypes => Ok(None),
        }
    })
}

fn __abs__(cls: PyClass<DateDelta>, slf: PyRef<'_, DateDelta>) -> PyReturn {
    if slf.months.get() >= 0 && slf.days.get() >= 0 {
        Ok(slf.newref())
    } else {
        DateDelta {
            months: -slf.months,
            days: -slf.days,
        }
        .to_obj(cls)
    }
}

extern "C" fn __hash__(slf: PyObj) -> Py_hash_t {
    hashmask(
        // SAFETY: self argument is always the DateDelta type
        unsafe { slf.assume_heaptype::<DateDelta>() }
            .1
            .python_hash(),
    )
}

extern "C" fn __bool__(slf: PyObj) -> c_int {
    // SAFETY: self argument is always the DateDelta type
    (!unsafe { slf.assume_heaptype::<DateDelta>() }.1.is_zero()).into()
}

#[allow(static_mut_refs)]
static mut SLOTS: &[PyType_Slot] = &[
    slotmethod!(DateDelta, Py_tp_new, __new__),
    slotmethod!(DateDelta, Py_tp_richcompare, __richcmp__),
    slotmethod!(DateDelta, Py_nb_negative, __neg__, 1),
    slotmethod!(DateDelta, Py_tp_repr, __repr__, 1),
    slotmethod!(DateDelta, Py_tp_str, __str__, 1),
    IDENTITY_SLOT,
    slotmethod!(DateDelta, Py_nb_absolute, __abs__, 1),
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

fn format_iso(_: PyType, slf: DateDelta) -> PyReturn {
    slf.fmt_iso().to_py()
}

fn parse_iso(cls: PyClass<DateDelta>, arg: PyObj) -> PyReturn {
    warn_with_class(
        *cls.state().warn_deprecation,
        c"DateDelta is deprecated; use ItemizedDateDelta instead.",
        1,
    )?;
    parse_iso_inner(cls, arg)
}

fn parse_iso_inner(cls: PyClass<DateDelta>, arg: PyObj) -> PyReturn {
    let py_str = arg
        .cast_allow_subclass::<PyStr>()
        // NOTE: this exception message also needs to make sense when
        // called through the constructor
        .ok_or_type_err("when parsing from ISO format, the argument must be str")?;
    let s = py_str.as_utf8()?;
    let err = || format!("Invalid format: {arg}");
    DateDelta::parse_iso(s)
        .ok_or_else_value_err(err)?
        .to_obj(cls)
}

fn in_months_days(_: PyType, DateDelta { months, days }: DateDelta) -> PyReturn {
    [months.get().to_py()?, days.get().to_py()?].into_pytuple()
}

// FUTURE: maybe also return the sign?
fn in_years_months_days(_: PyType, DateDelta { months, days }: DateDelta) -> PyReturn {
    let years = months.get() / 12;
    let months = months.get() % 12;
    [years.to_py()?, months.to_py()?, days.get().to_py()?].into_pytuple()
}

fn __reduce__(cls: PyClass<DateDelta>, DateDelta { months, days }: DateDelta) -> PyReturn {
    [
        cls.state().unpickle_date_delta.newref(),
        [months.get().to_py()?, days.get().to_py()?].into_pytuple()?,
    ]
    .into_pytuple()
}

pub(crate) fn unpickle(state: &State, args: &[PyObj]) -> PyReturn {
    match args {
        &[months_obj, days_obj] => {
            let months = DeltaMonths::new_unchecked(
                months_obj
                    .cast_exact::<PyInt>()
                    .ok_or_type_err("invalid pickle data")?
                    .to_long()? as _,
            );
            let days = DeltaDays::new_unchecked(
                days_obj
                    .cast_exact::<PyInt>()
                    .ok_or_type_err("invalid pickle data")?
                    .to_long()? as _,
            );
            DateDelta::new(months, days)
                .ok_or_value_err("invalid pickle data")?
                .to_obj(*state.date_delta_type)
        }
        _ => raise_type_err("invalid pickle data")?,
    }
}

static mut METHODS: &[PyMethodDef] = &[
    COPY_METHOD,
    DEEPCOPY_METHOD,
    method0!(DateDelta, format_iso, doc::DATEDELTA_FORMAT_ISO),
    classmethod1!(DateDelta, parse_iso, doc::DATEDELTA_PARSE_ISO),
    method0!(DateDelta, in_months_days, doc::DATEDELTA_IN_MONTHS_DAYS),
    method0!(
        DateDelta,
        in_years_months_days,
        doc::DATEDELTA_IN_YEARS_MONTHS_DAYS
    ),
    method0!(DateDelta, __reduce__, c""),
    classmethod_kwargs!(
        DateDelta,
        __get_pydantic_core_schema__,
        doc::PYDANTIC_SCHEMA
    ),
    PyMethodDef::zeroed(),
];

pub(crate) static mut SPEC: PyType_Spec =
    type_spec::<DateDelta>(c"whenever.DateDelta", unsafe { SLOTS });
