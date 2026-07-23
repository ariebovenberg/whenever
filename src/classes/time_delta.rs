use core::ffi::{CStr, c_int, c_void};
use pyo3_ffi::*;
use std::ptr::null_mut as NULL;

pub(crate) use crate::domain::time_delta::{
    DeltaIncrement, TimeDelta, parse_all_components, parse_prefix,
};

use crate::{
    classes::{
        date_delta::{DateDelta, InitError},
        datetime_delta::{DateTimeDelta, handle_exact_unit},
        instant::Instant,
        offset_datetime::OffsetDateTime,
        plain_datetime::{plain_since_inner, resolve_local_relative_to, total_calendar_plain},
        zoned_datetime::{ZonedDateTime, zoned_since_in_units, zoned_target},
    },
    common::{
        math::{
            self, CalendarIncrement, DifferenceUnitSet, ExactUnit, ExactUnitSet, SinceUntilKwargs,
            TotalUnit,
        },
        round,
        scalar::*,
    },
    docstrings as doc,
    py::*,
    pymodule::State,
};

impl TimeDelta {
    pub(crate) fn from_py_unchecked(delta: PyTimeDelta) -> Self {
        Self {
            secs: delta.whole_seconds().unwrap(),
            subsec: delta.subsec(),
        }
    }

    pub(crate) const fn pyhash(self) -> Py_hash_t {
        #[cfg(target_pointer_width = "64")]
        {
            hash_combine(self.subsec.get() as Py_hash_t, self.secs.get() as Py_hash_t)
        }
        #[cfg(target_pointer_width = "32")]
        {
            hash_combine(
                self.subsec.get() as Py_hash_t,
                hash_combine(
                    self.secs.get() as Py_hash_t,
                    (self.secs.get() >> 32) as Py_hash_t,
                ),
            )
        }
    }

    pub(crate) fn from_py(d: PyTimeDelta) -> Option<Self> {
        Some(TimeDelta {
            secs: d.whole_seconds()?,
            subsec: d.subsec(),
        })
    }
}

impl PyPayload for TimeDelta {}

pub(crate) const MAX_SECS: u64 = (Year::MAX.get() as u64) * 366 * 24 * S_PER_HOUR as u64;
pub(crate) const MAX_HOURS: u64 = MAX_SECS / S_PER_HOUR as u64;
pub(crate) const MAX_MINUTES: u64 = MAX_SECS / 60;
pub(crate) const MAX_MILLISECONDS: u64 = MAX_SECS * 1_000;
pub(crate) const MAX_MICROSECONDS: u64 = MAX_SECS * 1_000_000;

pub(crate) const SINGLETONS: &[(&CStr, TimeDelta); 3] = &[
    (
        c"ZERO",
        TimeDelta {
            secs: DeltaSeconds::ZERO,
            subsec: SubSecNanos::MIN,
        },
    ),
    (c"MIN", TimeDelta::MIN),
    (c"MAX", TimeDelta::MAX),
];

#[inline]
pub(crate) fn set_timedelta_from_kwargs(
    key: PyObj,
    value: PyObj,
    delta: &mut TimeDelta,
    units: &mut ExactUnitSet,
    eq: StrEqFn,
    state: &State,
) -> PyResult<bool> {
    let unit = if eq(key, *state.str_weeks) {
        ExactUnit::Weeks
    } else if eq(key, *state.str_days) {
        ExactUnit::Days
    } else if eq(key, *state.str_hours) {
        ExactUnit::Hours
    } else if eq(key, *state.str_minutes) {
        ExactUnit::Minutes
    } else if eq(key, *state.str_seconds) {
        ExactUnit::Seconds
    } else if eq(key, *state.str_milliseconds) {
        ExactUnit::Milliseconds
    } else if eq(key, *state.str_microseconds) {
        ExactUnit::Microseconds
    } else if eq(key, *state.str_nanoseconds) {
        ExactUnit::Nanoseconds
    } else {
        return Ok(false);
    };
    units.insert(unit);
    *delta = delta.add(unit.parse_py_number(value)?).ok_or_range_err()?;
    Ok(true)
}

pub(crate) fn timedelta_from_kwargs<K>(
    fname: &'static str,
    kwargs: K,
    state: &State,
) -> PyResult<TimeDelta>
where
    K: IntoIterator<Item = (PyObj, PyObj)>,
{
    let mut result = TimeDelta::ZERO;
    let mut suppress_24h_warning = false;
    let mut units = ExactUnitSet::EMPTY;

    handle_kwargs(fname, kwargs, |key, value, eq| {
        if eq(key, *state.str_days_assumed_24h_ok) {
            suppress_24h_warning = value.is_truthy()?;
            Ok(true)
        } else {
            set_timedelta_from_kwargs(key, value, &mut result, &mut units, eq, state)
        }
    })?;

    if !suppress_24h_warning
        && (units.contains(ExactUnit::Days) || units.contains(ExactUnit::Weeks))
    {
        warn_with_class(
            *state.warn_days_not_always_24h,
            doc::DAYS_NOT_ALWAYS_24H_MSG,
            1,
        )?;
    }

    Ok(result)
}

fn __new__(cls: PyClass<TimeDelta>, args: PyTuple, kwargs: Option<PyDict>) -> PyReturn {
    let nkwargs = kwargs.map_or(0, |k| k.len());
    let state = cls.state();

    match (args.len(), nkwargs) {
        (1, 0) => {
            let arg = args.iter().next().unwrap();
            if PyStr::isinstance(arg) {
                parse_iso(cls, arg)
            } else if arg.cast_allow_subclass::<PyTimeDelta>().is_some() {
                let d = arg
                    .cast_exact::<PyTimeDelta>()
                    .ok_or_type_err("argument must be datetime.timedelta exactly")?;
                TimeDelta::from_py(d).ok_or_range_err()?.to_obj(cls)
            } else {
                raise_type_err("TimeDelta() requires an ISO 8601 string or datetime.timedelta")
            }
        }
        (0, 0) => TimeDelta::ZERO.to_obj(cls),
        (0, _) => {
            timedelta_from_kwargs("TimeDelta", kwargs.unwrap().iteritems(), state)?.to_obj(cls)
        }
        _ => raise_type_err("TimeDelta() takes no positional arguments"),
    }
}

pub(crate) fn hours(state: &State, arg: PyObj) -> PyReturn {
    TimeDelta::from_nanos_unchecked(handle_exact_unit(
        arg,
        MAX_HOURS,
        "hours",
        NS_PER_HOUR as i128,
    )?)
    .to_obj(*state.time_delta_type)
}

pub(crate) fn minutes(state: &State, arg: PyObj) -> PyReturn {
    TimeDelta::from_nanos_unchecked(handle_exact_unit(
        arg,
        MAX_MINUTES,
        "minutes",
        NS_PER_MINUTE as i128,
    )?)
    .to_obj(*state.time_delta_type)
}

pub(crate) fn seconds(state: &State, arg: PyObj) -> PyReturn {
    TimeDelta::from_nanos_unchecked(handle_exact_unit(
        arg,
        MAX_SECS,
        "seconds",
        1_000_000_000_i128,
    )?)
    .to_obj(*state.time_delta_type)
}

pub(crate) fn milliseconds(state: &State, arg: PyObj) -> PyReturn {
    TimeDelta::from_nanos_unchecked(handle_exact_unit(
        arg,
        MAX_MILLISECONDS,
        "milliseconds",
        1_000_000_i128,
    )?)
    .to_obj(*state.time_delta_type)
}

pub(crate) fn microseconds(state: &State, arg: PyObj) -> PyReturn {
    TimeDelta::from_nanos_unchecked(handle_exact_unit(
        arg,
        MAX_MICROSECONDS,
        "microseconds",
        1_000_i128,
    )?)
    .to_obj(*state.time_delta_type)
}

pub(crate) fn nanoseconds(state: &State, arg: PyObj) -> PyReturn {
    TimeDelta::from_nanos(
        arg.cast_allow_subclass::<PyInt>()
            .ok_or_value_err("nanoseconds must be an integer")?
            .to_i128()?,
    )
    .ok_or_range_err()?
    .to_obj(*state.time_delta_type)
}

fn __richcmp__(cls: PyClass<TimeDelta>, a: TimeDelta, arg: PyObj, op: c_int) -> PyReturn {
    match arg.extract(cls) {
        Some(b) => CompareOp::from_ffi(op).apply(a, b).to_py(),
        None => not_implemented(),
    }
}

extern "C" fn __hash__(slf: PyObj) -> Py_hash_t {
    // SAFETY: we know self is passed to this method
    hashmask(unsafe { slf.assume_heaptype::<TimeDelta>().1 }.pyhash()) as Py_hash_t
}

fn __neg__(cls: PyClass<TimeDelta>, slf: TimeDelta) -> PyReturn {
    (-slf).to_obj(cls)
}

extern "C" fn __bool__(slf: PyObj) -> c_int {
    // SAFETY: self argument is always the self type
    (!unsafe { slf.assume_heaptype::<TimeDelta>() }.1.is_zero()).into()
}

fn __repr__(_: PyType, slf: TimeDelta) -> PyReturn {
    format!("TimeDelta(\"{slf}\")").to_py()
}

fn __str__(cls: PyType, slf: TimeDelta) -> PyReturn {
    format_iso(cls, slf)
}

fn __mul__(obj_a: PyObj, obj_b: PyObj) -> PyReturn {
    if let Some(py_int) = obj_b.cast_allow_subclass::<PyInt>() {
        mul_int(obj_a, py_int.to_i128()?)
    } else if let Some(py_int) = obj_a.cast_allow_subclass::<PyInt>() {
        mul_int(obj_b, py_int.to_i128()?)
    } else if let Some(py_float) = obj_b.cast_allow_subclass::<PyFloat>() {
        mul_float(obj_a, py_float.to_f64()?)
    } else if let Some(py_float) = obj_a.cast_allow_subclass::<PyFloat>() {
        mul_float(obj_b, py_float.to_f64()?)
    } else {
        not_implemented()
    }
}

#[inline(never)]
fn mul_int(delta_obj: PyObj, factor: i128) -> PyReturn {
    if factor == 1 {
        Ok(delta_obj.newref())
    } else {
        // SAFETY: one of the arguments is always the self type (the other is int)
        let (cls, delta) = unsafe { delta_obj.assume_heaptype::<TimeDelta>() };
        delta
            .total_nanos()
            .checked_mul(factor)
            .and_then(TimeDelta::from_nanos)
            .ok_or_range_err()?
            .to_obj(cls)
    }
}

#[inline(never)]
fn mul_float(delta_obj: PyObj, factor: f64) -> PyReturn {
    if factor == 1.0 {
        Ok(delta_obj.newref())
    } else {
        // SAFETY: one of the arguments is always the self type (the other is float)
        let (cls, delta) = unsafe { delta_obj.assume_heaptype::<TimeDelta>() };
        TimeDelta::from_nanos_f64(delta.to_nanos_f64() * factor)
            .ok_or_range_err()?
            .to_obj(cls)
    }
}

fn __truediv__(a_obj: PyObj, b_obj: PyObj) -> PyReturn {
    binary_operation::<TimeDelta>(a_obj, b_obj, "/", |operands| {
        if let Some(py_int) = b_obj.cast_allow_subclass::<PyInt>() {
            let factor = py_int.to_i128()?;
            // SAFETY: the first operand is a TimeDelta and the second is an int.
            let (cls, delta) = unsafe { a_obj.assume_heaptype::<TimeDelta>() };
            if factor == 1 {
                return Ok(Some(a_obj.newref()));
            } else if factor == 0 {
                raise(exc_zero_division_error(), "Division by zero")?
            }
            let nanos = delta.total_nanos();
            // SAFETY: division by integer is never bigger than the original value.
            Ok(Some(
                TimeDelta::from_nanos_unchecked(
                    // NOTE: try integer division if possible to avoid precision loss.
                    if nanos % factor == 0 {
                        nanos / factor
                    } else {
                        (nanos as f64 / factor as f64).round() as i128
                    },
                )
                .to_obj(cls)?,
            ))
        } else if let Some(py_float) = b_obj.cast_allow_subclass::<PyFloat>() {
            // SAFETY: the first operand is a TimeDelta and the second is a float.
            let (cls, delta) = unsafe { a_obj.assume_heaptype::<TimeDelta>() };
            let factor = py_float.to_f64()?;
            if factor == 1.0 {
                return Ok(Some(a_obj.newref()));
            } else if factor == 0.0 {
                raise(exc_zero_division_error(), "Division by zero")?
            }
            Ok(Some(
                TimeDelta::from_nanos_f64(delta.to_nanos_f64() / factor)
                    .ok_or_range_err()?
                    .to_obj(cls)?,
            ))
        } else if let BinaryCall::SameType { slf, other, .. } = operands {
            if other.is_zero() {
                raise(exc_zero_division_error(), "Division by zero")?
            }
            Ok(Some(
                (slf.total_nanos() as f64 / other.total_nanos() as f64).to_py()?,
            ))
        } else {
            Ok(None)
        }
    })
}

fn __floordiv__(a_obj: PyObj, b_obj: PyObj) -> PyReturn {
    binary_operation::<TimeDelta>(a_obj, b_obj, "//", |operands| {
        let BinaryCall::SameType { slf, other, .. } = operands else {
            return Ok(None);
        };
        if other.is_zero() {
            raise(exc_zero_division_error(), "Division by zero")?
        }
        // NOTE: we can't avoid using i128 *in general*, because the divisor
        //       may be 1 nanosecond and the dividend TimeDelta.MAX
        let slf = slf.total_nanos();
        let other = other.total_nanos();
        let mut result = slf / other;
        // Adjust for "correct" (Python style) floor division with mixed signs
        if slf.signum() != other.signum() && slf % other != 0 {
            result -= 1;
        }
        Ok(Some(result.to_py()?))
    })
}

fn __mod__(a_obj: PyObj, b_obj: PyObj) -> PyReturn {
    binary_operation::<TimeDelta>(a_obj, b_obj, "%", |operands| {
        let BinaryCall::SameType { cls, slf, other } = operands else {
            return Ok(None);
        };

        let slf = slf.total_nanos();
        let other = other.total_nanos();
        if other == 0 {
            raise(exc_zero_division_error(), "Division by zero")?
        }
        let mut result = slf % other;
        // Adjust for "correct" (Python style) floor division with mixed signs
        if slf.signum() != other.signum() && result != 0 {
            result += other;
        }
        // SAFETY: remainder is always smaller than the divisor
        Ok(Some(TimeDelta::from_nanos_unchecked(result).to_obj(cls)?))
    })
}

fn __add__(a_obj: PyObj, b_obj: PyObj) -> PyReturn {
    add_operator(a_obj, b_obj, false)
}

fn __sub__(a_obj: PyObj, b_obj: PyObj) -> PyReturn {
    add_operator(a_obj, b_obj, true)
}

#[inline(never)]
fn add_operator(a_obj: PyObj, b_obj: PyObj, negate: bool) -> PyReturn {
    binary_operation::<TimeDelta>(a_obj, b_obj, if negate { "-" } else { "+" }, |operands| {
        match operands {
            BinaryCall::SameType { cls, slf, other } => Ok(Some(
                slf.add(other.negate_if(negate))
                    .ok_or_range_err()?
                    .to_obj(cls)?,
            )),
            BinaryCall::ExtTypes { cls, slf, other } => {
                let state = cls.state();
                if let Some(mut ddelta) = other.extract(*state.date_delta_type) {
                    if negate {
                        ddelta = -ddelta;
                    }
                    warn_with_class(
                        *state.warn_deprecation,
                        c"DateTimeDelta is deprecated; use ItemizedDelta instead.",
                        1,
                    )?;
                    Ok(Some(
                        DateTimeDelta::new(ddelta, *slf)
                            .ok_or_value_err("mixed sign of delta components")?
                            .to_obj(*state.datetime_delta_type)?,
                    ))
                } else if let Some(mut dtdelta) = other.extract(*state.datetime_delta_type) {
                    if negate {
                        dtdelta = -dtdelta;
                    }
                    Ok(Some(
                        dtdelta
                            .add(DateTimeDelta {
                                date: DateDelta::ZERO,
                                time: *slf,
                            })
                            .map_err(|e| {
                                value_err(match e {
                                    InitError::TooBig => "Result out of range",
                                    InitError::MixedSign => "mixed sign of delta components",
                                })
                            })?
                            .to_obj(*state.datetime_delta_type)?,
                    ))
                } else if negate {
                    Ok(None)
                } else {
                    match_type!(
                        other,
                        *state.plain_datetime_type => |dt| {
                            warn_with_class(
                                *state.warn_naive_arithmetic,
                                doc::PLAIN_SHIFT_UNAWARE_MSG,
                                1,
                            )?;
                            Ok(Some(
                                dt.shift(*slf)
                                    .ok_or_range_err()?
                                    .to_obj(*state.plain_datetime_type)?,
                            ))
                        },
                        *state.instant_type => |inst| {
                            Ok(Some(
                                inst.shift(*slf)
                                    .ok_or_range_err()?
                                    .to_obj(*state.instant_type)?,
                            ))
                        },
                        *state.offset_datetime_type => |odt| {
                            warn_with_class(
                                *state.warn_potentially_stale_offset,
                                doc::OFFSET_SHIFT_STALE_MSG,
                                1,
                            )?;
                            Ok(Some(
                                odt.to_plain()
                                    .shift(*slf)
                                    .and_then(|dt| dt.assume_offset(odt.offset))
                                    .ok_or_range_err()?
                                    .to_obj(*state.offset_datetime_type)?,
                            ))
                        },
                        ref *state.zoned_datetime_type => |zdt| {
                            Ok(Some(zdt.shift(
                                slf.to_shift(),
                                None,
                                state,
                                *state.zoned_datetime_type,
                            )?))
                        },
                        _ => { Ok(None) },
                    )
                }
            }
            BinaryCall::OtherTypes => Ok(None),
        }
    })
}

fn __abs__(cls: PyClass<TimeDelta>, slf: PyRef<'_, TimeDelta>) -> PyReturn {
    if slf.is_negative() {
        (-*slf).to_obj(cls)
    } else {
        Ok(slf.newref())
    }
}

#[allow(static_mut_refs)]
static mut SLOTS: &[PyType_Slot] = &[
    slotmethod!(TimeDelta, Py_tp_new, __new__),
    slotmethod!(TimeDelta, Py_tp_richcompare, __richcmp__),
    slotmethod!(TimeDelta, Py_nb_negative, __neg__, 1),
    slotmethod!(TimeDelta, Py_tp_repr, __repr__, 1),
    slotmethod!(TimeDelta, Py_tp_str, __str__, 1),
    IDENTITY_SLOT,
    slotmethod!(Py_nb_multiply, __mul__, 2),
    slotmethod!(Py_nb_true_divide, __truediv__, 2),
    slotmethod!(Py_nb_add, __add__, 2),
    slotmethod!(Py_nb_subtract, __sub__, 2),
    slotmethod!(TimeDelta, Py_nb_absolute, __abs__, 1),
    slotmethod!(Py_nb_floor_divide, __floordiv__, 2),
    slotmethod!(Py_nb_remainder, __mod__, 2),
    PyType_Slot {
        slot: Py_tp_doc,
        pfunc: doc::TIMEDELTA.as_ptr() as *mut c_void,
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

fn __reduce__(cls: PyClass<TimeDelta>, slf: TimeDelta) -> PyReturn {
    let TimeDelta { secs, subsec } = slf;
    let data = pack![secs.get(), subsec.get()];
    [
        cls.state().unpickle_time_delta.newref(),
        [data.to_py()?].into_pytuple()?,
    ]
    .into_pytuple()
}

pub(crate) fn unpickle(state: &State, arg: PyObj) -> PyReturn {
    let py_bytes = arg
        .cast_exact::<PyBytes>()
        .ok_or_type_err("invalid pickle data")?;
    let mut data = py_bytes.as_bytes();
    if data.len() != 12 {
        raise_value_err("invalid pickle data")?;
    }
    TimeDelta {
        secs: DeltaSeconds::new_unchecked(unpack_one!(data, i64)),
        subsec: SubSecNanos::new_unchecked(unpack_one!(data, i32)),
    }
    .to_obj(*state.time_delta_type)
}

fn in_nanoseconds(cls: PyClass<TimeDelta>, slf: TimeDelta) -> PyReturn {
    warn_with_class(
        *cls.state().warn_deprecation,
        c"in_nanoseconds is deprecated, use total('nanoseconds') instead",
        1,
    )?;
    slf.total_nanos().to_py()
}

fn in_microseconds(cls: PyClass<TimeDelta>, slf: TimeDelta) -> PyReturn {
    warn_with_class(
        *cls.state().warn_deprecation,
        c"in_microseconds is deprecated, use total('microseconds') instead",
        1,
    )?;
    let TimeDelta { secs, subsec } = slf;
    (secs.get() as f64 * 1e6 + subsec.get() as f64 * 1e-3).to_py()
}

fn in_milliseconds(cls: PyClass<TimeDelta>, slf: TimeDelta) -> PyReturn {
    warn_with_class(
        *cls.state().warn_deprecation,
        c"in_milliseconds is deprecated, use total('milliseconds') instead",
        1,
    )?;
    let TimeDelta { secs, subsec } = slf;
    (secs.get() as f64 * 1e3 + subsec.get() as f64 * 1e-6).to_py()
}

fn in_seconds(cls: PyClass<TimeDelta>, slf: TimeDelta) -> PyReturn {
    warn_with_class(
        *cls.state().warn_deprecation,
        c"in_seconds is deprecated, use total('seconds') instead",
        1,
    )?;
    let TimeDelta { secs, subsec } = slf;
    (secs.get() as f64 + subsec.get() as f64 * 1e-9).to_py()
}

fn in_minutes(cls: PyClass<TimeDelta>, slf: TimeDelta) -> PyReturn {
    warn_with_class(
        *cls.state().warn_deprecation,
        c"in_minutes is deprecated, use total('minutes') instead",
        1,
    )?;
    let TimeDelta { secs, subsec } = slf;
    (secs.get() as f64 / 60.0 + subsec.get() as f64 * 1e-9 / 60.0).to_py()
}

fn in_hours(cls: PyClass<TimeDelta>, slf: TimeDelta) -> PyReturn {
    warn_with_class(
        *cls.state().warn_deprecation,
        c"in_hours is deprecated, use total('hours') instead",
        1,
    )?;
    let TimeDelta { secs, subsec } = slf;
    (secs.get() as f64 / 3600.0 + subsec.get() as f64 * 1e-9 / 3600.0).to_py()
}

fn in_days_of_24h(cls: PyClass<TimeDelta>, slf: TimeDelta) -> PyReturn {
    warn_with_class(
        *cls.state().warn_deprecation,
        c"in_days_of_24h is deprecated, use total('days') instead",
        1,
    )?;
    let TimeDelta { secs, subsec } = slf;
    (secs.get() as f64 / S_PER_DAY as f64 + subsec.get() as f64 * 1e-9 / S_PER_DAY as f64).to_py()
}

fn from_py_timedelta(cls: PyClass<TimeDelta>, arg: PyObj) -> PyReturn {
    warn_with_class(
        *cls.state().warn_deprecation,
        c"from_py_timedelta() is deprecated. Use TimeDelta() constructor instead.",
        1,
    )?;
    if let Some(d) = arg.cast_exact::<PyTimeDelta>() {
        TimeDelta::from_py(d).ok_or_range_err()?.to_obj(cls)
    } else {
        raise_type_err("argument must be datetime.timedelta exactly")
    }
}

fn to_stdlib(cls: PyClass<TimeDelta>, slf: TimeDelta) -> PyReturn {
    let TimeDelta { subsec, secs } = slf;
    let &PyDateTime_CAPI {
        Delta_FromDelta,
        DeltaType,
        ..
    } = cls.state().py_api()?;
    // SAFETY: calling C API with valid arguments
    unsafe {
        Delta_FromDelta(
            secs.get().div_euclid(S_PER_DAY.into()) as _,
            secs.get().rem_euclid(S_PER_DAY.into()) as _,
            (subsec.get() / NS_PER_MICROSEC as i32) as _,
            0,
            DeltaType,
        )
    }
    .own()
}

fn py_timedelta(cls: PyClass<TimeDelta>, slf: TimeDelta) -> PyReturn {
    warn_with_class(
        *cls.state().warn_deprecation,
        c"py_timedelta() is deprecated. Use to_stdlib() instead.",
        1,
    )?;
    to_stdlib(cls, slf)
}

fn in_hrs_mins_secs_nanos(_: PyType, slf: TimeDelta) -> PyReturn {
    let TimeDelta { secs, subsec } = slf;
    let secs = secs.get();
    let (secs, nanos) = if secs >= 0 {
        (secs, subsec.get())
    } else if subsec.get() == 0 {
        (secs, 0)
    } else {
        (secs + 1, subsec.get() - NS_PER_SEC as i32)
    };
    [
        (secs / S_PER_HOUR as i64).to_py()?,
        (secs % S_PER_HOUR as i64 / 60).to_py()?,
        (secs % 60).to_py()?,
        nanos.to_py()?,
    ]
    .into_pytuple()
}

fn format_iso(_: PyType, slf: TimeDelta) -> PyReturn {
    slf.fmt_iso().to_py()
}

fn parse_iso(cls: PyClass<TimeDelta>, arg: PyObj) -> PyReturn {
    let py_str = arg
        .cast_allow_subclass::<PyStr>()
        // NOTE: this exception message also needs to make sense when
        // called through the constructor
        .ok_or_type_err("when parsing from ISO format, the argument must be str")?;
    let s = &mut py_str.as_utf8()?;
    let err = || format!("Invalid format: {arg}");

    let negate = (s.len() >= 4)
        .then(|| parse_prefix(s))
        .flatten()
        .ok_or_else_value_err(err)?;

    let (nanos, is_empty) = parse_all_components(s).ok_or_else_value_err(err)?;

    // i.e. there must be at least one component (`PT` alone is invalid)
    if is_empty {
        raise_value_err(err())?;
    }
    TimeDelta::from_nanos(i128::try_from(nanos).ok().ok_or_range_err()?)
        .ok_or_range_err()?
        .negate_if(negate)
        .to_obj(cls)
}

fn round(
    cls: PyClass<TimeDelta>,
    slf: TimeDelta,
    args: &[PyObj],
    kwargs: &mut IterKwargs,
) -> PyReturn {
    let round::DeltaArgs { increment, mode } = round::DeltaArgs::parse(cls.state(), args, kwargs)?;
    slf.round(increment, mode.to_abs_euclid(slf.is_negative()))
        .ok_or_range_err()?
        .to_obj(cls)
}

fn add(
    cls: PyClass<TimeDelta>,
    slf: TimeDelta,
    args: &[PyObj],
    kwargs: &mut IterKwargs,
) -> PyReturn {
    add_method(cls, slf, args, kwargs, false)
}

fn subtract(
    cls: PyClass<TimeDelta>,
    slf: TimeDelta,
    args: &[PyObj],
    kwargs: &mut IterKwargs,
) -> PyReturn {
    add_method(cls, slf, args, kwargs, true)
}

#[inline(never)]
fn add_method(
    cls: PyClass<TimeDelta>,
    slf: TimeDelta,
    args: &[PyObj],
    kwargs: &mut IterKwargs,
    negate: bool,
) -> PyReturn {
    let other = match (args.first(), kwargs.len()) {
        (Some(_), n) if n > 0 => raise_type_err("cannot mix positional and keyword arguments")?,
        (Some(arg), _) => arg.extract(cls).ok_or_type_err(if negate {
            "subtract() argument must be a whenever.TimeDelta"
        } else {
            "add() argument must be a whenever.TimeDelta"
        })?,
        (None, 0) => return slf.to_obj(cls),
        (None, _) => {
            timedelta_from_kwargs(if negate { "subtract" } else { "add" }, kwargs, cls.state())?
        }
    }
    .negate_if(negate);
    slf.add(other).ok_or_range_err()?.to_obj(cls)
}

#[inline(never)]
fn in_units(
    cls: PyClass<TimeDelta>,
    slf: TimeDelta,
    args: &[PyObj],
    kwargs: &mut IterKwargs,
) -> PyReturn {
    let state = cls.state();
    let units = DifferenceUnitSet::from_py(handle_one_arg("in_units", args)?, state)?;

    // Parse optional round kwargs
    let mut round_mode = round::Mode::Trunc;
    let mut round_increment = math::DifferenceIncrement::MIN;
    let mut relative_to_arg = None;
    let mut suppress_24h_warning = false;

    handle_kwargs("in_units", kwargs, |key, value, eq| {
        if eq(key, *state.str_round_mode) {
            round_mode =
                round::Mode::from_py_named("rounding mode", value, &state.round_mode_strs)?;
        } else if eq(key, *state.str_round_increment) {
            round_increment = math::DifferenceIncrement::from_py(value)?;
        } else if eq(key, *state.str_relative_to) {
            relative_to_arg = Some(value);
        } else if eq(key, *state.str_days_assumed_24h_ok) {
            suppress_24h_warning = value.is_truthy()?;
        } else {
            return Ok(false);
        }
        Ok(true)
    })?;
    let neg = slf.is_negative();
    let has_cal_or_date = units.has_calendar() || units.has_days_or_weeks();

    if let Some(arg) = relative_to_arg {
        // ZonedDateTime: full DST-aware path.
        if let Some(zdt) = arg.extract_ref(*state.zoned_datetime_type) {
            let shifted_inst = zdt.to_instant().shift(slf).ok_or_range_err()?;
            let shifted = shifted_inst.to_offset_in(&zdt.tz).ok_or_range_err()?;
            let result = zoned_since_in_units(
                shifted,
                shifted_inst,
                zdt,
                zoned_target(shifted.date, shifted_inst, zdt, neg).ok_or_range_err()?,
                units,
                round_mode,
                round_increment,
                neg,
            )
            .ok_or_range_err()?;
            return result.to_obj(state);
        }

        // PlainDateTime/OffsetDateTime: treat local time as UTC (no DST).
        // Emit appropriate warnings only when calendar or day/week units are involved.
        let b_dt = resolve_local_relative_to(arg, state, has_cal_or_date, has_cal_or_date)?;

        // Compute the shifted datetime by treating b_dt as UTC anchor.
        let a_inst = b_dt.assume_utc().shift(slf).ok_or_range_err()?;
        let a_dt = a_inst.to_offset(Offset::ZERO).ok_or_range_err()?.to_plain();
        plain_since_inner(
            state,
            a_dt,
            b_dt,
            SinceUntilKwargs::InUnits(units, round_mode, round_increment),
            false,
        )
    } else {
        if units.has_days_or_weeks() && !suppress_24h_warning {
            warn_with_class(
                *state.warn_days_not_always_24h,
                doc::DAYS_NOT_ALWAYS_24H_MSG,
                1,
            )?;
        }
        if let Some(exact) = units.to_exact_assuming_24h_days() {
            let result = slf
                .in_exact_units(exact, round_increment, round_mode.to_abs_euclid(neg))
                .ok_or_range_err()?;
            result.to_obj(state)
        } else {
            raise_type_err("years and months units require a `relative_to` argument")
        }
    }
}

#[inline(never)]
fn total(
    cls: PyClass<TimeDelta>,
    slf: TimeDelta,
    args: &[PyObj],
    kwargs: &mut IterKwargs,
) -> PyReturn {
    let state = cls.state();
    let unit = TotalUnit::from_py(handle_one_arg("total", args)?, state)?;

    let mut relative_to_arg = None;
    let mut suppress_24h_warning = false;
    handle_kwargs("total", kwargs, |key, value, eq| {
        if eq(key, *state.str_relative_to) {
            relative_to_arg = Some(value);
        } else if eq(key, *state.str_days_assumed_24h_ok) {
            suppress_24h_warning = value.is_truthy()?;
        } else {
            return Ok(false);
        }
        Ok(true)
    })?;

    let calendar_unit = match unit.to_exact(relative_to_arg.is_none()) {
        Ok(ExactUnit::Nanoseconds) => {
            // Special case for nanoseconds: always return an int
            return slf.total_nanos().to_py();
        }
        Ok(u) => {
            if (u == ExactUnit::Weeks || u == ExactUnit::Days) && !suppress_24h_warning {
                warn_with_class(
                    *state.warn_days_not_always_24h,
                    doc::DAYS_NOT_ALWAYS_24H_MSG,
                    1,
                )?;
            }
            return (slf.to_nanos_f64() / u.in_nanos() as f64).to_py();
        }
        // FUTURE: fast early exit for zero
        Err(calendar_unit) => calendar_unit,
    };

    let arg = relative_to_arg
        .ok_or_type_err("for calendar units, a `relative_to` argument must be passed")?;

    // ZonedDateTime: full DST-aware path via zoned_target.
    if let Some(zdt) = arg.extract_ref(*state.zoned_datetime_type) {
        let shifted_inst = zdt.to_instant().shift(slf).ok_or_range_err()?;
        let shifted = shifted_inst.to_offset_in(&zdt.tz).ok_or_range_err()?;
        return total_calendar(slf.is_negative(), calendar_unit, zdt, shifted, shifted_inst);
    }

    // PlainDateTime/OffsetDateTime: treat local time as UTC for the calendar
    // diff, emitting appropriate warnings. Same approach as Python's
    // `assume_tz("UTC")` trick (to_tz("UTC") would be wrong: it re-interprets
    // the instant in UTC rather than keeping the local date as the anchor).
    let b_dt = resolve_local_relative_to(arg, state, true, true)?;

    let neg = slf.is_negative();
    let a_inst = b_dt.assume_utc().shift(slf).ok_or_range_err()?;
    let a_dt = a_inst.to_offset(Offset::ZERO).ok_or_range_err()?.to_plain();
    let target_date = match (neg, b_dt.with_date(a_dt.date).cmp(&a_dt)) {
        (false, std::cmp::Ordering::Greater) => a_dt.date.yesterday(),
        (true, std::cmp::Ordering::Less) => a_dt.date.tomorrow(),
        _ => Some(a_dt.date),
    }
    .ok_or_range_err()?;
    total_calendar_plain(neg, calendar_unit, a_inst, b_dt, target_date)
}

#[inline(never)]
pub(crate) fn total_calendar(
    neg: bool,
    unit: math::CalendarUnit,
    relative_to: &ZonedDateTime,
    shifted: OffsetDateTime,
    shifted_inst: Instant,
) -> PyReturn {
    let target_date =
        zoned_target(shifted.date, shifted_inst, relative_to, neg).ok_or_range_err()?;

    let (trunc_amount, trunc_date, expand_date) = math::date_diff_single_unit(
        target_date,
        relative_to.date,
        CalendarIncrement::MIN,
        unit,
        neg,
    )
    .ok_or_range_err()?;

    let trunc_odt = relative_to.with_date(trunc_date.into()).ok_or_range_err()?;
    let expand_odt = relative_to
        .with_date(expand_date.into())
        .ok_or_range_err()?;

    let r = shifted_inst.diff(trunc_odt.to_instant()).abs();
    let e = expand_odt.to_instant().diff(trunc_odt.to_instant());

    (trunc_amount as f64 + r.to_nanos_f64() / e.to_nanos_f64()).to_py()
}

static mut METHODS: &[PyMethodDef] = &[
    COPY_METHOD,
    DEEPCOPY_METHOD,
    method0!(TimeDelta, __reduce__, c""),
    method0!(TimeDelta, format_iso, doc::TIMEDELTA_FORMAT_ISO),
    classmethod1!(TimeDelta, parse_iso, doc::TIMEDELTA_PARSE_ISO),
    method0!(TimeDelta, in_nanoseconds, doc::TIMEDELTA_IN_NANOSECONDS),
    method0!(TimeDelta, in_microseconds, doc::TIMEDELTA_IN_MICROSECONDS),
    method0!(TimeDelta, in_milliseconds, doc::TIMEDELTA_IN_MILLISECONDS),
    method0!(TimeDelta, in_seconds, doc::TIMEDELTA_IN_SECONDS),
    method0!(TimeDelta, in_minutes, doc::TIMEDELTA_IN_MINUTES),
    method0!(TimeDelta, in_hours, doc::TIMEDELTA_IN_HOURS),
    method0!(TimeDelta, in_days_of_24h, doc::TIMEDELTA_IN_DAYS_OF_24H),
    classmethod1!(
        TimeDelta,
        from_py_timedelta,
        doc::TIMEDELTA_FROM_PY_TIMEDELTA
    ),
    method0!(TimeDelta, to_stdlib, doc::TIMEDELTA_TO_STDLIB),
    method0!(TimeDelta, py_timedelta, doc::TIMEDELTA_PY_TIMEDELTA),
    method0!(
        TimeDelta,
        in_hrs_mins_secs_nanos,
        doc::TIMEDELTA_IN_HRS_MINS_SECS_NANOS
    ),
    method_kwargs!(TimeDelta, round, doc::TIMEDELTA_ROUND),
    method_kwargs!(TimeDelta, add, doc::TIMEDELTA_ADD),
    method_kwargs!(TimeDelta, subtract, doc::TIMEDELTA_SUBTRACT),
    method_kwargs!(TimeDelta, in_units, doc::TIMEDELTA_IN_UNITS),
    method_kwargs!(TimeDelta, total, doc::TIMEDELTA_TOTAL),
    classmethod_kwargs!(
        TimeDelta,
        __get_pydantic_core_schema__,
        doc::PYDANTIC_SCHEMA
    ),
    PyMethodDef::zeroed(),
];

pub(crate) static mut SPEC: PyType_Spec =
    type_spec::<TimeDelta>(c"whenever.TimeDelta", unsafe { SLOTS });

#[cfg(test)]
mod tests {
    use super::*;

    fn td(secs: i64, nanos: i32) -> TimeDelta {
        TimeDelta {
            secs: DeltaSeconds::new(secs).unwrap(),
            subsec: SubSecNanos::new_unchecked(nanos),
        }
    }

    fn td_secs(s: i64) -> TimeDelta {
        td(s, 0)
    }

    fn inc(secs: u64, nanos: i32) -> DeltaIncrement {
        DeltaIncrement {
            secs,
            subsec: SubSecNanos::new_unchecked(nanos),
        }
    }

    fn sec() -> DeltaIncrement {
        inc(1, 0)
    }

    fn ten_sec() -> DeltaIncrement {
        inc(10, 0)
    }

    fn abs(mode: round::Mode, negative: bool) -> round::AbsMode {
        mode.to_abs_euclid(negative)
    }

    // --- Sub-second rounding (increment < 1s) ---

    #[test]
    fn round_subsec_floor() {
        // 1.7s → floor to 1s
        assert_eq!(
            td(1, 700_000_000).round(sec(), abs(round::Mode::Floor, false)),
            Some(td_secs(1))
        );
    }

    #[test]
    fn round_subsec_ceil() {
        // 1.7s → ceil to 2s
        assert_eq!(
            td(1, 700_000_000).round(sec(), abs(round::Mode::Ceil, false)),
            Some(td_secs(2))
        );
    }

    #[test]
    fn round_subsec_trunc_positive() {
        // 1.7s → trunc (towards 0) = 1s
        assert_eq!(
            td(1, 700_000_000).round(sec(), abs(round::Mode::Trunc, false)),
            Some(td_secs(1))
        );
    }

    #[test]
    fn round_subsec_trunc_negative() {
        // -1.3s (secs=-2, subsec=700_000_000) → trunc (towards 0) = -1s
        assert_eq!(
            td(-2, 700_000_000).round(sec(), abs(round::Mode::Trunc, true)),
            Some(td_secs(-1))
        );
    }

    #[test]
    fn round_subsec_expand_positive() {
        // 1.7s → expand (away from 0) = 2s
        assert_eq!(
            td(1, 700_000_000).round(sec(), abs(round::Mode::Expand, false)),
            Some(td_secs(2))
        );
    }

    #[test]
    fn round_subsec_expand_negative() {
        // -1.3s → expand (away from 0) = -2s
        assert_eq!(
            td(-2, 700_000_000).round(sec(), abs(round::Mode::Expand, true)),
            Some(td_secs(-2))
        );
    }

    // --- Half-way tie-breaking with sub-second ---

    #[test]
    fn round_subsec_half_even_tie() {
        // 1.5s → half_even: quotient=1 (odd), round up to 2
        assert_eq!(
            td(1, 500_000_000).round(sec(), abs(round::Mode::HalfEven, false)),
            Some(td_secs(2))
        );
        // 2.5s → half_even: quotient=2 (even), round down to 2
        assert_eq!(
            td(2, 500_000_000).round(sec(), abs(round::Mode::HalfEven, false)),
            Some(td_secs(2))
        );
    }

    #[test]
    fn round_subsec_half_ceil_tie() {
        // 1.5s → half_ceil: round up (towards +∞) = 2s
        assert_eq!(
            td(1, 500_000_000).round(sec(), abs(round::Mode::HalfCeil, false)),
            Some(td_secs(2))
        );
        // -1.5s (secs=-2, subsec=500_000_000) → half_ceil: round up (towards +∞) = -1s
        assert_eq!(
            td(-2, 500_000_000).round(sec(), abs(round::Mode::HalfCeil, true)),
            Some(td_secs(-1))
        );
    }

    #[test]
    fn round_subsec_half_floor_tie() {
        // 1.5s → half_floor: round down = 1s
        assert_eq!(
            td(1, 500_000_000).round(sec(), abs(round::Mode::HalfFloor, false)),
            Some(td_secs(1))
        );
        // -1.5s → half_floor: round down (towards -∞) = -2s
        assert_eq!(
            td(-2, 500_000_000).round(sec(), abs(round::Mode::HalfFloor, true)),
            Some(td_secs(-2))
        );
    }

    #[test]
    fn round_subsec_half_trunc_tie() {
        // 1.5s → half_trunc: ties towards 0 = 1s
        assert_eq!(
            td(1, 500_000_000).round(sec(), abs(round::Mode::HalfTrunc, false)),
            Some(td_secs(1))
        );
        // -1.5s → half_trunc: ties towards 0 = -1s
        assert_eq!(
            td(-2, 500_000_000).round(sec(), abs(round::Mode::HalfTrunc, true)),
            Some(td_secs(-1))
        );
    }

    #[test]
    fn round_subsec_half_expand_tie() {
        // 1.5s → half_expand: ties away from 0 = 2s
        assert_eq!(
            td(1, 500_000_000).round(sec(), abs(round::Mode::HalfExpand, false)),
            Some(td_secs(2))
        );
        // -1.5s → half_expand: ties away from 0 = -2s
        assert_eq!(
            td(-2, 500_000_000).round(sec(), abs(round::Mode::HalfExpand, true)),
            Some(td_secs(-2))
        );
    }

    // --- Whole-second rounding (increment >= 1s) ---

    #[test]
    fn round_wholesec_trunc_positive() {
        // 45s → trunc to 10s = 40s
        assert_eq!(
            td_secs(45).round(ten_sec(), abs(round::Mode::Trunc, false)),
            Some(td_secs(40))
        );
    }

    #[test]
    fn round_wholesec_trunc_negative() {
        // -45s → trunc to 10s = -40s (towards zero)
        assert_eq!(
            td_secs(-45).round(ten_sec(), abs(round::Mode::Trunc, true)),
            Some(td_secs(-40))
        );
    }

    #[test]
    fn round_wholesec_expand_positive() {
        // 41s → expand to 10s = 50s
        assert_eq!(
            td_secs(41).round(ten_sec(), abs(round::Mode::Expand, false)),
            Some(td_secs(50))
        );
    }

    #[test]
    fn round_wholesec_expand_negative() {
        // -41s → expand to 10s = -50s (away from zero)
        assert_eq!(
            td_secs(-41).round(ten_sec(), abs(round::Mode::Expand, true)),
            Some(td_secs(-50))
        );
    }

    #[test]
    fn round_wholesec_half_trunc_tie() {
        // 45s → half_trunc to 10s = 40s (tie towards zero)
        assert_eq!(
            td_secs(45).round(ten_sec(), abs(round::Mode::HalfTrunc, false)),
            Some(td_secs(40))
        );
        // -45s → half_trunc to 10s = -40s
        assert_eq!(
            td_secs(-45).round(ten_sec(), abs(round::Mode::HalfTrunc, true)),
            Some(td_secs(-40))
        );
    }

    #[test]
    fn round_wholesec_half_expand_tie() {
        // 45s → half_expand to 10s = 50s (tie away from zero)
        assert_eq!(
            td_secs(45).round(ten_sec(), abs(round::Mode::HalfExpand, false)),
            Some(td_secs(50))
        );
        // -45s → half_expand to 10s = -50s
        assert_eq!(
            td_secs(-45).round(ten_sec(), abs(round::Mode::HalfExpand, true)),
            Some(td_secs(-50))
        );
    }

    #[test]
    fn round_zero() {
        // Zero should remain zero for all modes
        for mode in [
            round::Mode::Floor,
            round::Mode::Ceil,
            round::Mode::Trunc,
            round::Mode::Expand,
            round::Mode::HalfEven,
            round::Mode::HalfCeil,
            round::Mode::HalfFloor,
            round::Mode::HalfTrunc,
            round::Mode::HalfExpand,
        ] {
            assert_eq!(
                td_secs(0).round(sec(), mode.to_abs_euclid(false)),
                Some(td_secs(0))
            );
        }
    }

    #[test]
    fn round_exact_value() {
        // Already at increment boundary → unchanged for all modes
        for mode in [
            round::Mode::Floor,
            round::Mode::Ceil,
            round::Mode::Trunc,
            round::Mode::Expand,
            round::Mode::HalfEven,
            round::Mode::HalfCeil,
            round::Mode::HalfFloor,
            round::Mode::HalfTrunc,
            round::Mode::HalfExpand,
        ] {
            assert_eq!(
                td_secs(30).round(ten_sec(), mode.to_abs_euclid(false)),
                Some(td_secs(30))
            );
            assert_eq!(
                td_secs(-30).round(ten_sec(), mode.to_abs_euclid(true)),
                Some(td_secs(-30))
            );
        }
    }

    #[test]
    fn round_large_increment() {
        // increment = 1<<65 ns (> i64::MAX), trunc mode
        let large_inc = inc(36_893_488_147, 419_103_232);
        // A value smaller than the increment should round to zero
        assert_eq!(
            td_secs(3600).round(large_inc, abs(round::Mode::Trunc, false)),
            Some(td_secs(0))
        );
        // A value exactly equal to the increment should be unchanged
        assert_eq!(
            td(36_893_488_147, 419_103_232).round(large_inc, abs(round::Mode::Trunc, false)),
            Some(td(36_893_488_147, 419_103_232))
        );
    }
}
