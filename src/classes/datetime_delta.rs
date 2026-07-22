use core::ffi::{CStr, c_int, c_void};
use pyo3_ffi::*;
use std::ptr::null_mut as NULL;

pub(crate) use crate::domain::datetime_delta::DateTimeDelta;

use crate::{
    classes::{
        date_delta::{DateDelta, InitError},
        time_delta::{
            MAX_HOURS, MAX_MICROSECONDS, MAX_MILLISECONDS, MAX_MINUTES, MAX_SECS, TimeDelta,
        },
    },
    common::scalar::*,
    docstrings as doc,
    py::*,
    pymodule::State,
};

impl DateTimeDelta {
    pub(crate) fn pyhash(self) -> Py_hash_t {
        hash_combine(self.ddelta.pyhash(), self.tdelta.pyhash())
    }
}

impl PyPayload for DateTimeDelta {}

#[inline]
pub(crate) fn handle_exact_unit(
    value: PyObj,
    max: u64,
    name: &str,
    factor: i128,
) -> PyResult<i128> {
    if let Some(int) = value.cast_allow_subclass::<PyInt>() {
        let i = int.to_i64()?;
        (i.unsigned_abs() <= max)
            .then(|| i as i128 * factor)
            .ok_or_range_err()
    } else if let Some(py_float) = value.cast_allow_subclass::<PyFloat>() {
        let f = py_float.to_f64()?;
        (f.abs() <= max as f64)
            .then_some((f * factor as f64) as i128)
            .ok_or_range_err()
    } else {
        raise_value_err(format!("{name} must be an integer or float"))?
    }
}

// Also return UnitSet
#[inline]
pub(crate) fn set_units_from_kwargs(
    key: PyObj,
    value: PyObj,
    months: &mut i32,
    days: &mut i32,
    nanos: &mut i128,
    state: &State,
    eq: StrEqFn,
) -> PyResult<bool> {
    if eq(key, *state.str_years) {
        *months = value
            .cast_allow_subclass::<PyInt>()
            .ok_or_value_err("years must be an integer")?
            .to_long()?
            .checked_mul(12)
            .and_then(|y| y.try_into().ok())
            .and_then(|y| months.checked_add(y))
            .ok_or_range_err()?;
    } else if eq(key, *state.str_months) {
        *months = value
            .cast_allow_subclass::<PyInt>()
            .ok_or_value_err("months must be an integer")?
            .to_long()?
            .try_into()
            .ok()
            .and_then(|m| months.checked_add(m))
            .ok_or_range_err()?;
    } else if eq(key, *state.str_weeks) {
        *days = value
            .cast_allow_subclass::<PyInt>()
            .ok_or_value_err("weeks must be an integer")?
            .to_long()?
            .checked_mul(7)
            .and_then(|d| d.try_into().ok())
            .and_then(|d| days.checked_add(d))
            .ok_or_range_err()?;
    } else if eq(key, *state.str_days) {
        *days = value
            .cast_allow_subclass::<PyInt>()
            .ok_or_value_err("days must be an integer")?
            .to_long()?
            .try_into()
            .ok()
            .and_then(|d| days.checked_add(d))
            .ok_or_range_err()?;
    } else if eq(key, *state.str_hours) {
        *nanos += handle_exact_unit(value, MAX_HOURS, "hours", NS_PER_HOUR as i128)?;
    } else if eq(key, *state.str_minutes) {
        *nanos += handle_exact_unit(value, MAX_MINUTES, "minutes", NS_PER_MINUTE as i128)?;
    } else if eq(key, *state.str_seconds) {
        *nanos += handle_exact_unit(value, MAX_SECS, "seconds", 1_000_000_000)?;
    } else if eq(key, *state.str_milliseconds) {
        *nanos += handle_exact_unit(value, MAX_MILLISECONDS, "milliseconds", 1_000_000)?;
    } else if eq(key, *state.str_microseconds) {
        *nanos += handle_exact_unit(value, MAX_MICROSECONDS, "microseconds", 1_000)?;
    } else if eq(key, *state.str_nanoseconds) {
        *nanos = value
            .cast_allow_subclass::<PyInt>()
            .ok_or_value_err("nanoseconds must be an integer")?
            .to_i128()?
            .checked_add(*nanos)
            .ok_or_range_err()?;
    } else {
        return Ok(false);
    }
    Ok(true)
}

pub(crate) const SINGLETONS: &[(&CStr, DateTimeDelta); 1] = &[(c"ZERO", DateTimeDelta::ZERO)];

#[inline(never)]
fn __new__(cls: PyClass<DateTimeDelta>, args: PyTuple, kwargs: Option<PyDict>) -> PyReturn {
    let nargs = args.len();
    let nkwargs = kwargs.map_or(0, |k| k.len());

    let mut months: i32 = 0;
    let mut days: i32 = 0;
    let mut nanos: i128 = 0;
    let state = cls.state();
    warn_with_class(
        *state.warn_deprecation,
        c"DateTimeDelta is deprecated; use ItemizedDelta instead.",
        1,
    )?;
    match (nargs, nkwargs) {
        (1, 0) => parse_iso_inner(cls, args.iter().next().unwrap()),
        (0, 0) => DateTimeDelta {
            ddelta: DateDelta {
                months: DeltaMonths::ZERO,
                days: DeltaDays::ZERO,
            },
            tdelta: TimeDelta {
                secs: DeltaSeconds::ZERO,
                subsec: SubSecNanos::MIN,
            },
        }
        .to_obj(cls), // OPTIMIZE: return the singleton
        (0, _) => {
            handle_kwargs(
                "DateTimeDelta",
                // SAFETY: if nkwargs > 0, kwargs is Some
                kwargs.unwrap().iteritems(),
                |key, value, eq| {
                    set_units_from_kwargs(key, value, &mut months, &mut days, &mut nanos, state, eq)
                },
            )?;
            if months >= 0 && days >= 0 && nanos >= 0 || months <= 0 && days <= 0 && nanos <= 0 {
                DateTimeDelta {
                    ddelta: DeltaMonths::new(months)
                        .zip(DeltaDays::new(days))
                        .map(|(m, d)| DateDelta { months: m, days: d })
                        .ok_or_range_err()?,
                    tdelta: TimeDelta::from_nanos(nanos).ok_or_range_err()?,
                }
                .to_obj(cls)
            } else {
                raise_value_err("mixed sign in DateTimeDelta")?
            }
        }
        _ => {
            raise_value_err("DateTimeDelta() takes either 1 positional argument, or only keywords")?
        }
    }
}

fn __richcmp__(cls: PyClass<DateTimeDelta>, a: DateTimeDelta, b_obj: PyObj, op: c_int) -> PyReturn {
    match b_obj.extract(cls) {
        Some(b) => match op {
            pyo3_ffi::Py_EQ => (a == b).to_py(),
            pyo3_ffi::Py_NE => (a != b).to_py(),
            _ => not_implemented(),
        },
        None => not_implemented(),
    }
}

extern "C" fn __hash__(slf: PyObj) -> Py_hash_t {
    let (_, d) =
        // SAFETY: first argument guaranteed to be self type
        unsafe { slf.assume_heaptype::<DateTimeDelta>() };
    hashmask(d.pyhash())
}

fn __neg__(cls: PyClass<DateTimeDelta>, d: DateTimeDelta) -> PyReturn {
    (-d).to_obj(cls)
}

extern "C" fn __bool__(slf: PyObj) -> c_int {
    let (_, DateTimeDelta { ddelta, tdelta }) =
        // SAFETY: first argument guaranteed to be self type
        unsafe { slf.assume_heaptype::<DateTimeDelta>() };
    (!(ddelta.is_zero() && tdelta.is_zero())).into()
}

fn __repr__(_: PyType, d: DateTimeDelta) -> PyReturn {
    format!("DateTimeDelta(\"{d}\")").to_py()
}

fn __str__(_: PyType, d: DateTimeDelta) -> PyReturn {
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

    // SAFETY: one operand is a DateTimeDelta and the other is an int.
    let (delta_type, delta) = unsafe { delta_obj.assume_heaptype::<DateTimeDelta>() };
    i32::try_from(factor)
        .ok()
        .and_then(|f| delta.mul(f))
        .ok_or_range_err()?
        .to_obj(delta_type)
}

fn __add__(a_obj: PyObj, b_obj: PyObj) -> PyReturn {
    add_method(a_obj, b_obj, false)
}

fn __sub__(obj_a: PyObj, obj_b: PyObj) -> PyReturn {
    add_method(obj_a, obj_b, true)
}

#[inline(never)]
fn add_method(obj_a: PyObj, obj_b: PyObj, negate: bool) -> PyReturn {
    binary_operation::<DateTimeDelta>(obj_a, obj_b, if negate { "-" } else { "+" }, |operands| {
        let (cls, slf, mut other) = match operands {
            BinaryCall::SameType { cls, slf, other } => (cls, slf, *other),
            BinaryCall::ExtTypes { cls, slf, other } => {
                let state = cls.state();
                let other = match_type!(
                    other,
                    *state.date_delta_type => |ddelta| {
                        DateTimeDelta {
                            ddelta,
                            tdelta: TimeDelta::ZERO,
                        }
                    },
                    *state.time_delta_type => |tdelta| {
                        DateTimeDelta {
                            ddelta: DateDelta::ZERO,
                            tdelta,
                        }
                    },
                    _ => { return Ok(None) },
                );
                (cls, slf, other)
            }
            BinaryCall::OtherTypes => return Ok(None),
        };
        if negate {
            other = -other;
        }
        Ok(Some(
            slf.add(other)
                .map_err(|e| {
                    value_err(match e {
                        InitError::TooBig => "Addition result out of bounds",
                        InitError::MixedSign => "mixed sign in DateTimeDelta",
                    })
                })?
                .to_obj(cls)?,
        ))
    })
}

fn __abs__(cls: PyClass<DateTimeDelta>, slf: PyRef<'_, DateTimeDelta>) -> PyReturn {
    if slf.ddelta.months.get() >= 0 && slf.ddelta.days.get() >= 0 && !slf.tdelta.is_negative() {
        Ok(slf.newref())
    } else {
        DateTimeDelta {
            ddelta: slf.ddelta.abs(),
            tdelta: slf.tdelta.abs(),
        }
        .to_obj(cls)
    }
}

#[allow(static_mut_refs)]
static mut SLOTS: &[PyType_Slot] = &[
    slotmethod!(DateTimeDelta, Py_tp_new, __new__),
    slotmethod!(DateTimeDelta, Py_tp_richcompare, __richcmp__),
    slotmethod!(DateTimeDelta, Py_nb_negative, __neg__, 1),
    slotmethod!(DateTimeDelta, Py_tp_repr, __repr__, 1),
    slotmethod!(DateTimeDelta, Py_tp_str, __str__, 1),
    IDENTITY_SLOT,
    slotmethod!(DateTimeDelta, Py_nb_absolute, __abs__, 1),
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

fn format_iso(_: PyType, d: DateTimeDelta) -> PyReturn {
    d.fmt_iso().to_py()
}

fn parse_iso(cls: PyClass<DateTimeDelta>, arg: PyObj) -> PyReturn {
    warn_with_class(
        *cls.state().warn_deprecation,
        c"DateTimeDelta is deprecated; use ItemizedDelta instead.",
        1,
    )?;
    parse_iso_inner(cls, arg)
}

fn parse_iso_inner(cls: PyClass<DateTimeDelta>, arg: PyObj) -> PyReturn {
    let binding = arg
        .cast_allow_subclass::<PyStr>()
        // NOTE: this exception message also needs to make sense when
        // called through the constructor
        .ok_or_type_err("when parsing from ISO format, the argument must be str")?;

    let s = binding.as_utf8()?;
    let err = || format!("Invalid format or out of range: {arg}");
    DateTimeDelta::parse_iso(s)
        .ok_or_else_value_err(err)?
        .to_obj(cls)
}

fn in_months_days_secs_nanos(
    _: PyType,
    DateTimeDelta {
        ddelta: DateDelta { months, days },
        tdelta: TimeDelta { secs, subsec },
    }: DateTimeDelta,
) -> PyReturn {
    let mut secs = secs.get();
    let nanos = if secs < 0 && subsec.get() > 0 {
        secs += 1;
        subsec.get() - 1_000_000_000
    } else {
        subsec.get()
    };
    [
        months.get().to_py()?,
        days.get().to_py()?,
        secs.to_py()?,
        nanos.to_py()?,
    ]
    .into_pytuple()
}

fn date_part(cls: PyClass<DateTimeDelta>, slf: DateTimeDelta) -> PyReturn {
    warn_with_class(
        *cls.state().warn_deprecation,
        c"DateTimeDelta.date_part() is deprecated.",
        1,
    )?;
    slf.ddelta.to_obj(*cls.state().date_delta_type)
}

fn time_part(cls: PyClass<DateTimeDelta>, slf: DateTimeDelta) -> PyReturn {
    slf.tdelta.to_obj(*cls.state().time_delta_type)
}

fn __reduce__(
    cls: PyClass<DateTimeDelta>,
    DateTimeDelta {
        ddelta: DateDelta { months, days },
        tdelta: TimeDelta { secs, subsec },
    }: DateTimeDelta,
) -> PyReturn {
    [
        cls.state().unpickle_datetime_delta.newref(),
        // We don't do our own bit packing because the numbers are usually small
        // and Python's pickle protocol handles them more efficiently.
        [
            months.get().to_py()?,
            days.get().to_py()?,
            secs.get().to_py()?,
            subsec.get().to_py()?,
        ]
        .into_pytuple()?,
    ]
    .into_pytuple()
}

pub(crate) fn unpickle(state: &State, args: &[PyObj]) -> PyReturn {
    match args {
        &[months, days, secs, nanos] => DateTimeDelta {
            ddelta: DateDelta {
                months: DeltaMonths::new_unchecked(
                    months
                        .cast_exact::<PyInt>()
                        .ok_or_type_err("invalid pickle data")?
                        .to_long()? as _,
                ),
                days: DeltaDays::new_unchecked(
                    days.cast_exact::<PyInt>()
                        .ok_or_type_err("invalid pickle data")?
                        .to_long()? as _,
                ),
            },
            tdelta: TimeDelta {
                secs: DeltaSeconds::new_unchecked(
                    secs.cast_exact::<PyInt>()
                        .ok_or_type_err("invalid pickle data")?
                        .to_long()? as _,
                ),
                subsec: SubSecNanos::new_unchecked(
                    nanos
                        .cast_exact::<PyInt>()
                        .ok_or_type_err("invalid pickle data")?
                        .to_long()? as _,
                ),
            },
        }
        .to_obj(*state.datetime_delta_type),
        _ => raise_type_err("invalid pickle data")?,
    }
}

static mut METHODS: &[PyMethodDef] = &[
    COPY_METHOD,
    DEEPCOPY_METHOD,
    method0!(DateTimeDelta, format_iso, doc::DATETIMEDELTA_FORMAT_ISO),
    method0!(DateTimeDelta, date_part, doc::DATETIMEDELTA_DATE_PART),
    method0!(DateTimeDelta, time_part, doc::DATETIMEDELTA_TIME_PART),
    classmethod1!(DateTimeDelta, parse_iso, doc::DATETIMEDELTA_PARSE_ISO),
    method0!(DateTimeDelta, __reduce__, c""),
    method0!(
        DateTimeDelta,
        in_months_days_secs_nanos,
        doc::DATETIMEDELTA_IN_MONTHS_DAYS_SECS_NANOS
    ),
    classmethod_kwargs!(
        DateTimeDelta,
        __get_pydantic_core_schema__,
        doc::PYDANTIC_SCHEMA
    ),
    PyMethodDef::zeroed(),
];

pub(crate) static mut SPEC: PyType_Spec =
    type_spec::<DateTimeDelta>(c"whenever.DateTimeDelta", unsafe { SLOTS });
