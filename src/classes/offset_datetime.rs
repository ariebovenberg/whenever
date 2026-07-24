use core::ffi::{CStr, c_int, c_long, c_void};
use core::ptr::null_mut as NULL;
use pyo3_ffi::*;

pub(crate) use crate::domain::offset_datetime::OffsetDateTime;

use crate::classes::plain_datetime::DateTimeBoundaryUnit;
use crate::{
    classes::{date::Date, instant::Instant, plain_datetime, time::Time, time_delta::TimeDelta},
    common::{
        fmt::{self, Suffix},
        instant::{extract_instant, parse_instant_arg},
        pattern, pickle, rfc2822, round_args as round,
        shift_args::{parse_datetime_shift_arg, parse_datetime_shift_kwargs},
    },
    docstrings as doc,
    domain::{difference::DifferenceSpec, scalar::*},
    py::*,
    pymodule::State,
};

impl OffsetDateTime {
    pub(crate) fn to_stdlib_datetime(
        self,
        &PyDateTime_CAPI {
            DateTime_FromDateAndTime,
            DateTimeType,
            TimeZone_FromTimeZone,
            Delta_FromDelta,
            DeltaType,
            ..
        }: &PyDateTime_CAPI,
    ) -> PyResult<Owned<PyDateTime>> {
        let OffsetDateTime {
            date: Date { year, month, day },
            time:
                Time {
                    hour,
                    minute,
                    second,
                    subsec,
                },
            offset,
            ..
        } = self;
        // SAFETY: calling CPython API with valid arguments
        let delta = unsafe {
            Delta_FromDelta(
                // Important that we normalize so seconds >= 0
                offset.get().div_euclid(S_PER_DAY),
                offset.get().rem_euclid(S_PER_DAY),
                0,
                0,
                DeltaType,
            )
        }
        .own()?;
        let tz = unsafe { TimeZone_FromTimeZone(delta.as_ptr(), NULL()) }.own()?;
        unsafe {
            DateTime_FromDateAndTime(
                year.get().into(),
                month.get().into(),
                day.into(),
                hour.into(),
                minute.into(),
                second.into(),
                (subsec.get() / 1_000) as _,
                tz.as_ptr(),
                DateTimeType,
            )
        }
        .own()
        // SAFETY: safe to assume result of C API function is the proper type
        .map(|d| unsafe { d.cast_unchecked::<PyDateTime>() })
    }

    pub(crate) fn from_stdlib_datetime(dt: PyDateTime) -> PyResult<Self> {
        let date = Date::from_stdlib_date(dt.date());
        let time = Time::from_stdlib_datetime(dt);
        date.at(time)
            .assume_offset(Offset::from_stdlib_datetime(dt)?)
            .ok_or_range_err()
    }
}

impl Offset {
    /// Get the offset from a Python datetime
    pub(crate) fn from_stdlib_datetime(dt: PyDateTime) -> PyResult<Self> {
        Ok({
            let offset = dt.utcoffset()?;
            if let Some(py_delta) = (*offset).cast_exact::<PyTimeDelta>() {
                if py_delta.microseconds_component() != 0 {
                    raise_value_err("sub-second offset precision not supported")?
                }
                // SAFETY: Python datetime offsets are limited to +/- 24 hours
                Offset::new_unchecked(
                    py_delta.days_component() * S_PER_DAY + py_delta.seconds_component(),
                )
            } else if offset.is_none() {
                raise_value_err("datetime is naive")?
            } else {
                raise_value_err("datetime utcoffset() returned non-delta value")?
            }
        })
    }

    pub(crate) fn from_py(obj: PyObj, tdelta_cls: PyClass<TimeDelta>) -> PyResult<Self> {
        if let Some(py_int) = obj.cast_exact::<PyInt>() {
            Offset::from_hours(py_int.to_long()?)
                .ok_or_value_err("offset must be between -24 and 24 hours")
        } else if let Some(TimeDelta { secs, subsec }) = obj.extract(tdelta_cls) {
            if subsec.get() == 0 {
                Offset::from_i64(secs.get())
                    .ok_or_value_err("offset must be between -24 and 24 hours")
            } else {
                raise_value_err("offset must be a whole number of seconds")?
            }
        } else {
            raise_type_err(format!(
                "offset must be an integer or TimeDelta instance, got {obj}"
            ))?
        }
    }
}

impl PyPayload for OffsetDateTime {}

fn __new__(cls: PyClass<OffsetDateTime>, args: PyTuple, kwargs: Option<PyDict>) -> PyReturn {
    if args.len() == 1 && kwargs.map_or(0, |d| d.len()) == 0 {
        let arg = args.iter().next().unwrap();
        if PyStr::isinstance(arg) {
            return parse_iso(cls, arg);
        }
        if let Some(dt) = arg.cast_allow_subclass::<PyDateTime>() {
            return OffsetDateTime::from_stdlib_datetime(dt)?.to_obj(cls);
        }
        return raise_type_err("OffsetDateTime() requires an ISO 8601 string or datetime.datetime");
    }
    let mut year: c_long = 0;
    let mut month: c_long = 0;
    let mut day: c_long = 0;
    let mut hour: c_long = 0;
    let mut minute: c_long = 0;
    let mut second: c_long = 0;
    let mut nanosecond: c_long = 0;
    let mut offset: *mut PyObject = NULL();

    parse_args_kwargs!(
        args,
        kwargs,
        c"lll|lll$lO:OffsetDateTime",
        year,
        month,
        day,
        hour,
        minute,
        second,
        nanosecond,
        offset
    );

    let offset_obj = offset
        .borrow_opt()
        .ok_or_type_err("missing required keyword argument: 'offset'")?;
    let offset = Offset::from_py(offset_obj, *cls.state().time_delta_type)?;
    Date::from_longs(year, month, day)
        .ok_or_value_err("invalid date")?
        .at(Time::from_longs(hour, minute, second, nanosecond).ok_or_value_err("invalid time")?)
        .assume_offset(offset)
        .ok_or_range_err()?
        .to_obj(cls)
}

fn __repr__(_: PyType, OffsetDateTime { date, time, offset }: OffsetDateTime) -> PyReturn {
    PyAsciiStrBuilder::format((
        b"OffsetDateTime(\"",
        date.iso_format(false),
        b' ',
        time.iso_format(fmt::Precision::Auto, false),
        offset.iso_format(false),
        b"\")",
    ))
}

fn __str__(_: PyType, OffsetDateTime { date, time, offset }: OffsetDateTime) -> PyReturn {
    PyAsciiStrBuilder::format((
        date.iso_format(false),
        b'T',
        time.iso_format(fmt::Precision::Auto, false),
        offset.iso_format(false),
    ))
}

fn __richcmp__(
    cls: PyClass<OffsetDateTime>,
    a: OffsetDateTime,
    b_obj: PyObj,
    op: c_int,
) -> PyReturn {
    let inst_a = a.to_instant();
    let Some(inst_b) = extract_instant(b_obj, cls.state()) else {
        return not_implemented();
    };
    CompareOp::from_ffi(op).apply(inst_a, inst_b).to_py()
}

pub(crate) extern "C" fn __hash__(slf: PyObj) -> Py_hash_t {
    hashmask(
        // SAFETY: self type is always passed to __hash__
        unsafe { slf.assume_heaptype::<OffsetDateTime>() }
            .1
            .to_instant()
            .python_hash(),
    )
}

fn __add__(obj_a: PyObj, obj_b: PyObj) -> PyReturn {
    binary_operation::<OffsetDateTime>(obj_a, obj_b, "+", |operands| {
        let BinaryCall::ExtTypes { cls, slf, other } = operands else {
            return Ok(None);
        };
        let state = cls.state();
        let Some(tdelta) = other.extract(*state.time_delta_type) else {
            return Ok(None);
        };
        offset_stale_warning(state, doc::OFFSET_SHIFT_STALE_MSG)?;
        Ok(Some(slf.shift(tdelta).ok_or_range_err()?.to_obj(cls)?))
    })
}

fn __sub__(obj_a: PyObj, obj_b: PyObj) -> PyReturn {
    binary_operation::<OffsetDateTime>(obj_a, obj_b, "-", |operands| {
        let (cls, slf, other) = match operands {
            BinaryCall::SameType { cls, slf, other } => {
                return Ok(Some(
                    slf.to_instant()
                        .diff(other.to_instant())
                        .to_obj(*cls.state().time_delta_type)?,
                ));
            }
            BinaryCall::ExtTypes { cls, slf, other } => (cls, slf, other),
            BinaryCall::OtherTypes => return Ok(None),
        };
        let state = cls.state();
        if let Some(tdelta) = other.extract(*state.time_delta_type) {
            offset_stale_warning(state, doc::OFFSET_SHIFT_STALE_MSG)?;
            return Ok(Some(
                slf.shift(-tdelta).ok_or_range_err()?.to_obj(slf.class())?,
            ));
        }
        let Some(inst_b) = extract_instant(other, state) else {
            return Ok(None);
        };
        Ok(Some(
            slf.to_instant()
                .diff(inst_b)
                .to_obj(*state.time_delta_type)?,
        ))
    })
}

#[allow(static_mut_refs)]
static mut SLOTS: &[PyType_Slot] = &[
    slotmethod!(OffsetDateTime, Py_tp_new, __new__),
    slotmethod!(OffsetDateTime, Py_tp_str, __str__, 1),
    slotmethod!(OffsetDateTime, Py_tp_repr, __repr__, 1),
    slotmethod!(OffsetDateTime, Py_tp_richcompare, __richcmp__),
    slotmethod!(Py_nb_add, __add__, 2),
    slotmethod!(Py_nb_subtract, __sub__, 2),
    PyType_Slot {
        slot: Py_tp_doc,
        pfunc: doc::OFFSETDATETIME.as_ptr() as *mut c_void,
    },
    PyType_Slot {
        slot: Py_tp_hash,
        pfunc: __hash__ as *mut c_void,
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
        slot: Py_tp_dealloc,
        pfunc: generic_dealloc as *mut c_void,
    },
    PyType_Slot {
        slot: 0,
        pfunc: NULL(),
    },
];

fn exact_eq(cls: PyClass<OffsetDateTime>, slf: OffsetDateTime, obj_b: PyObj) -> PyReturn {
    if let Some(odt) = obj_b.extract(cls) {
        (slf == odt).to_py()
    } else {
        raise_type_err("can't compare different types")?
    }
}

pub(crate) fn to_instant(cls: PyClass<OffsetDateTime>, slf: OffsetDateTime) -> PyReturn {
    slf.to_instant().to_obj(*cls.state().instant_type)
}

fn to_fixed_offset(cls: PyClass<OffsetDateTime>, slf: OffsetDateTime, args: &[PyObj]) -> PyReturn {
    match *args {
        [] => slf.to_obj(cls),
        [offset_obj] => slf
            .to_instant()
            .to_offset(Offset::from_py(offset_obj, *cls.state().time_delta_type)?)
            .ok_or_range_err()?
            .to_obj(cls),
        _ => raise_type_err("to_fixed_offset() takes at most 1 argument"),
    }
}

fn to_tz(cls: PyClass<OffsetDateTime>, slf: OffsetDateTime, tz_obj: PyObj) -> PyReturn {
    let state = cls.state();
    slf.to_instant()
        .into_zoned_obj(state.tz_store.obj_get(tz_obj)?, *state.zoned_datetime_type)
}

fn to_system_tz(cls: PyClass<OffsetDateTime>, slf: OffsetDateTime) -> PyReturn {
    let state = cls.state();
    slf.to_instant()
        .into_zoned_obj(state.tz_store.get_system_tz()?, *state.zoned_datetime_type)
}

fn assume_tz(
    cls: PyClass<OffsetDateTime>,
    slf: OffsetDateTime,
    args: &[PyObj],
    kwargs: &mut IterKwargs,
) -> PyReturn {
    let state = cls.state();
    let &[tz_obj] = args else {
        raise_type_err(format!(
            "assume_tz() takes 1 positional argument but {} were given",
            args.len()
        ))?
    };

    // Parse offset_mismatch kwarg
    let mut mismatch_obj: Option<PyObj> = None;
    handle_kwargs("assume_tz", kwargs, |key, value, eq| {
        if eq(key, *state.str_offset_mismatch) {
            mismatch_obj = Some(value);
        } else {
            return Ok(false);
        }
        Ok(true)
    })?;

    let mismatch = match mismatch_obj {
        None => OffsetMismatch::Raise,
        Some(v) => OffsetMismatch::from_py(v, state)?,
    };

    let tz = state.tz_store.obj_get(tz_obj)?;

    // Compute what offset the timezone has at this instant
    let instant = slf.to_instant();
    let actual_offset = tz.offset_for_instant(instant.epoch);

    if matches!(mismatch, OffsetMismatch::KeepInstant) || actual_offset == slf.offset {
        // Offsets match (or we're keeping the instant): create ZDT from instant
        return instant.into_zoned_obj(tz, *state.zoned_datetime_type);
    }

    match mismatch {
        OffsetMismatch::Raise => raise(
            *state.exc_invalid_offset,
            format!(
                "Offset mismatch: timezone '{}' has offset {actual_offset}, but offset {} was expected",
                tz.key.as_deref().unwrap_or("(unknown)"),
                slf.offset,
            ),
        ),
        OffsetMismatch::KeepLocal => slf
            .to_plain()
            .resolve_compatible(&tz)
            .ok_or_range_err()?
            .into_zoned_obj_unchecked(tz, *state.zoned_datetime_type),
        OffsetMismatch::KeepInstant => unreachable!(),
    }
}

enum OffsetMismatch {
    Raise,
    KeepInstant,
    KeepLocal,
}

impl OffsetMismatch {
    fn from_py(obj: PyObj, state: &State) -> PyResult<Self> {
        match_interned_str("offset_mismatch", obj, |v, eq| {
            Some(if eq(v, *state.str_raise) {
                Self::Raise
            } else if eq(v, *state.str_keep_instant) {
                Self::KeepInstant
            } else if eq(v, *state.str_keep_local) {
                Self::KeepLocal
            } else {
                None?
            })
        })
    }
}

pub(crate) fn unpickle(state: &State, arg: PyObj) -> PyReturn {
    pickle::decode_offset(arg.expect_bytes()?)
        .ok_or_value_err(pickle::INVALID_DATA)?
        .to_obj(*state.offset_datetime_type)
}

fn to_stdlib(cls: PyClass<OffsetDateTime>, slf: OffsetDateTime) -> PyReturn {
    slf.to_stdlib_datetime(cls.state().py_api()?)
        .map(Owned::into_obj)
}

fn py_datetime(cls: PyClass<OffsetDateTime>, slf: OffsetDateTime) -> PyReturn {
    warn_with_class(
        *cls.state().warn_deprecation,
        c"py_datetime() is deprecated. Use to_stdlib() instead.",
        1,
    )?;
    to_stdlib(cls, slf)
}

fn date(cls: PyClass<OffsetDateTime>, OffsetDateTime { date, .. }: OffsetDateTime) -> PyReturn {
    date.to_obj(*cls.state().date_type)
}

fn time(cls: PyClass<OffsetDateTime>, OffsetDateTime { time, .. }: OffsetDateTime) -> PyReturn {
    time.to_obj(*cls.state().time_type)
}

fn day_of_year(_: PyClass<OffsetDateTime>, slf: OffsetDateTime) -> PyReturn {
    slf.date.day_of_year().to_py()
}

fn days_in_month(_: PyClass<OffsetDateTime>, slf: OffsetDateTime) -> PyReturn {
    slf.date.days_in_month().to_py()
}

fn days_in_year(_: PyClass<OffsetDateTime>, slf: OffsetDateTime) -> PyReturn {
    slf.date.days_in_year().to_py()
}

fn in_leap_year(_: PyClass<OffsetDateTime>, slf: OffsetDateTime) -> PyReturn {
    slf.date.is_in_leap_year().to_py()
}

fn start_of(
    cls: PyClass<OffsetDateTime>,
    slf: OffsetDateTime,
    args: &[PyObj],
    kwargs: &mut IterKwargs,
) -> PyReturn {
    let state = cls.state();
    let stale_offset_ok = handle_one_kwarg("start_of", *state.str_stale_offset_ok, kwargs)?;
    if !match stale_offset_ok {
        Some(value) => value.is_truthy()?,
        None => false,
    } {
        offset_stale_warning(state, doc::OFFSET_START_END_OF_STALE_MSG)?;
    }
    slf.to_plain()
        .start_of_unit(DateTimeBoundaryUnit::from_py(
            handle_one_arg("start_of", args)?,
            state,
        )?)
        .ok_or_range_err()?
        .assume_offset(slf.offset)
        .ok_or_range_err()?
        .to_obj(cls)
}

fn end_of(
    cls: PyClass<OffsetDateTime>,
    slf: OffsetDateTime,
    args: &[PyObj],
    kwargs: &mut IterKwargs,
) -> PyReturn {
    let state = cls.state();
    let stale_offset_ok = handle_one_kwarg("end_of", *state.str_stale_offset_ok, kwargs)?;
    if !match stale_offset_ok {
        Some(value) => value.is_truthy()?,
        None => false,
    } {
        offset_stale_warning(state, doc::OFFSET_START_END_OF_STALE_MSG)?;
    }
    slf.to_plain()
        .end_of_unit(DateTimeBoundaryUnit::from_py(
            handle_one_arg("end_of", args)?,
            state,
        )?)
        .ok_or_range_err()?
        .assume_offset(slf.offset)
        .ok_or_range_err()?
        .to_obj(cls)
}

fn offset_stale_warning(state: &State, msg: &CStr) -> PyResult<()> {
    warn_with_class(*state.warn_potentially_stale_offset, msg, 1)
}

/// Check for deprecated `ignore_dst` and new `stale_offset_ok`
/// kwargs in a kwargs iterator that only has these optional kwargs remaining,
/// and emit stale offset warning.
fn check_ignore_dst_and_stale_offset(
    fname: &str,
    kwargs: &mut IterKwargs,
    state: &State,
    stale_msg: &CStr,
) -> PyResult<()> {
    let mut suppress = false;
    handle_kwargs(fname, kwargs, |key, value, eq| {
        if eq(key, *state.str_ignore_dst) {
            warn_with_class(*state.warn_deprecation, doc::IGNORE_DST_DEPRECATED_MSG, 1)?;
        } else if eq(key, *state.str_stale_offset_ok) {
            suppress = value.is_truthy()?;
        } else {
            return Ok(false);
        }
        Ok(true)
    })?;
    if !suppress {
        offset_stale_warning(state, stale_msg)?;
    }
    Ok(())
}

fn replace_date(
    cls: PyClass<OffsetDateTime>,
    OffsetDateTime { time, offset, .. }: OffsetDateTime,
    args: &[PyObj],
    kwargs: &mut IterKwargs,
) -> PyReturn {
    let state = cls.state();
    check_ignore_dst_and_stale_offset(
        "replace_date",
        kwargs,
        state,
        doc::OFFSET_REPLACE_STALE_MSG,
    )?;
    let &[arg] = args else {
        raise_type_err("replace_date() takes exactly 1 positional argument")?
    };
    if let Some(date) = arg.extract(*state.date_type) {
        date.at(time)
            .assume_offset(offset)
            .ok_or_range_err()?
            .to_obj(cls)
    } else {
        raise_type_err("date must be a whenever.Date instance")
    }
}

fn replace_time(
    cls: PyClass<OffsetDateTime>,
    OffsetDateTime { date, offset, .. }: OffsetDateTime,
    args: &[PyObj],
    kwargs: &mut IterKwargs,
) -> PyReturn {
    let state = cls.state();
    check_ignore_dst_and_stale_offset(
        "replace_time",
        kwargs,
        state,
        doc::OFFSET_REPLACE_STALE_MSG,
    )?;
    let &[arg] = args else {
        raise_type_err("replace_time() takes exactly 1 positional argument")?
    };
    if let Some(time) = arg.extract(*state.time_type) {
        date.at(time)
            .assume_offset(offset)
            .ok_or_range_err()?
            .to_obj(cls)
    } else {
        raise_type_err("time must be a whenever.Time instance")
    }
}

fn format_iso(
    cls: PyClass<OffsetDateTime>,
    slf: OffsetDateTime,
    args: &[PyObj],
    kwargs: &mut IterKwargs,
) -> PyReturn {
    fmt::format_iso(
        slf.date,
        slf.time,
        cls.state(),
        args,
        kwargs,
        Suffix::Offset(slf.offset),
    )
}

fn parse_iso(cls: PyClass<OffsetDateTime>, arg: PyObj) -> PyReturn {
    OffsetDateTime::parse(
        arg.cast_allow_subclass::<PyStr>()
            // NOTE: this exception message also needs to make sense when
            // called through the constructor
            .ok_or_type_err("when parsing from ISO format, the argument must be str")?
            .as_utf8()?,
    )
    .ok_or_else_value_err(|| format!("Invalid format: {arg}"))?
    .to_obj(cls)
}

fn replace(
    cls: PyClass<OffsetDateTime>,
    slf: OffsetDateTime,
    args: &[PyObj],
    kwargs: &mut IterKwargs,
) -> PyReturn {
    if !args.is_empty() {
        raise_type_err("replace() takes no positional arguments")?
    }
    let state = cls.state();
    let mut components = slf.to_plain().components();
    let mut offset = slf.offset;
    let mut got_ignore_dst = false;
    let mut suppress_stale = false;

    handle_kwargs("replace", kwargs, |k, v, eq| {
        if eq(k, *state.str_ignore_dst) {
            got_ignore_dst = true;
        } else if eq(k, *state.str_stale_offset_ok) {
            suppress_stale = v.is_truthy()?;
        } else if eq(k, *state.str_offset) {
            offset = Offset::from_py(v, *state.time_delta_type)?;
        } else {
            return components.set_from_kwarg(k, v, state, eq);
        }
        Ok(true)
    })?;

    if got_ignore_dst {
        warn_with_class(*state.warn_deprecation, doc::IGNORE_DST_DEPRECATED_MSG, 1)?;
    }
    if !suppress_stale {
        offset_stale_warning(state, doc::OFFSET_REPLACE_STALE_MSG)?;
    }

    components
        .into_plain()?
        .assume_offset(offset)
        .ok_or_range_err()?
        .to_obj(cls)
}

fn now(cls: PyClass<OffsetDateTime>, args: &[PyObj], kwargs: &mut IterKwargs) -> PyReturn {
    let state = cls.state();
    let &[offset_obj] = args else {
        raise_type_err("now() takes exactly 1 positional argument")?
    };
    check_ignore_dst_and_stale_offset("now", kwargs, state, doc::OFFSET_NOW_STALE_MSG)?;
    let offset = Offset::from_py(offset_obj, *state.time_delta_type)?;
    state
        .now()?
        .to_offset(offset)
        .ok_or_raise(exc_os_error(), "Date is out of range")?
        .to_obj(cls)
}

fn from_py_datetime(cls: PyClass<OffsetDateTime>, arg: PyObj) -> PyReturn {
    let state = cls.state();
    warn_with_class(
        *state.warn_deprecation,
        c"from_py_datetime() is deprecated. Use OffsetDateTime() constructor instead.",
        1,
    )?;
    if let Some(py_dt) = arg.cast_allow_subclass::<PyDateTime>() {
        OffsetDateTime::from_stdlib_datetime(py_dt)?.to_obj(cls)
    } else {
        raise_type_err("argument must be a datetime.datetime instance")?
    }
}

pub(crate) fn to_plain(cls: PyClass<OffsetDateTime>, slf: OffsetDateTime) -> PyReturn {
    slf.to_plain().to_obj(*cls.state().plain_datetime_type)
}

pub(crate) fn timestamp(_: PyType, slf: OffsetDateTime) -> PyReturn {
    slf.to_instant().epoch.get().to_py()
}

pub(crate) fn timestamp_millis(_: PyType, slf: OffsetDateTime) -> PyReturn {
    slf.to_instant().timestamp_millis().to_py()
}

pub(crate) fn timestamp_nanos(_: PyType, slf: OffsetDateTime) -> PyReturn {
    slf.to_instant().timestamp_nanos().to_py()
}

fn add(
    cls: PyClass<OffsetDateTime>,
    slf: OffsetDateTime,
    args: &[PyObj],
    kwargs: &mut IterKwargs,
) -> PyReturn {
    shift_method(cls, slf, args, kwargs, false)
}

fn subtract(
    cls: PyClass<OffsetDateTime>,
    slf: OffsetDateTime,
    args: &[PyObj],
    kwargs: &mut IterKwargs,
) -> PyReturn {
    shift_method(cls, slf, args, kwargs, true)
}

#[inline(never)]
fn shift_method(
    cls: PyClass<OffsetDateTime>,
    slf: OffsetDateTime,
    args: &[PyObj],
    kwargs: &mut IterKwargs,
    negate: bool,
) -> PyReturn {
    let fname = if negate { "subtract" } else { "add" };
    let state = cls.state();
    let mut got_ignore_dst = false;
    let mut suppress_stale = false;

    let shift = match *args {
        [arg] => {
            for (key, value) in kwargs.by_ref() {
                if unicode_eq(key, *state.str_ignore_dst) {
                    got_ignore_dst = true;
                } else if unicode_eq(key, *state.str_stale_offset_ok) {
                    suppress_stale = value.is_truthy()?;
                } else {
                    raise_type_err(format!(
                        "{fname}() can't mix positional and keyword arguments"
                    ))?;
                }
            }
            parse_datetime_shift_arg(fname, arg, state)?
        }
        [] => parse_datetime_shift_kwargs(fname, kwargs, state, |k, v, eq| {
            if eq(k, *state.str_ignore_dst) {
                got_ignore_dst = true;
                Ok(true)
            } else if eq(k, *state.str_stale_offset_ok) {
                suppress_stale = v.is_truthy()?;
                Ok(true)
            } else {
                Ok(false)
            }
        })?,
        _ => raise_type_err(format!(
            "{}() takes at most 1 positional argument, got {}",
            fname,
            args.len()
        ))?,
    };

    if got_ignore_dst {
        warn_with_class(*state.warn_deprecation, doc::IGNORE_DST_DEPRECATED_MSG, 1)?;
    }
    if !suppress_stale {
        offset_stale_warning(state, doc::OFFSET_SHIFT_STALE_MSG)?;
    }

    let shift = shift.negate_if(negate);
    slf.shift_by(shift).ok_or_range_err()?.to_obj(cls)
}

fn difference(cls: PyClass<OffsetDateTime>, slf: OffsetDateTime, arg: PyObj) -> PyReturn {
    let state = cls.state();
    let other_inst = parse_instant_arg("difference", arg, state)?;

    slf.to_instant()
        .diff(other_inst)
        .to_obj(*state.time_delta_type)
}

fn __reduce__(cls: PyClass<OffsetDateTime>, slf: OffsetDateTime) -> PyReturn {
    let data = pickle::encode_offset(slf);
    [
        cls.state().unpickle_offset_datetime.newref(),
        [data.to_py()?].into_pytuple()?,
    ]
    .into_pytuple()
}

/// checks the args comply with (ts: ?, /, *, offset: ?, ignore_dst: ?, stale_offset_ok: ?)
fn check_from_timestamp_args_return_offset(
    fname: &str,
    args: &[PyObj],
    kwargs: &mut IterKwargs,
    state: &State,
) -> PyResult<Offset> {
    let mut got_ignore_dst = false;
    let mut suppress_stale = false;
    let mut offset = None;
    if args.len() != 1 {
        raise_type_err(format!(
            "{}() takes 1 positional argument but {} were given",
            fname,
            args.len()
        ))?
    }

    handle_kwargs("from_timestamp", kwargs, |key, value, eq| {
        if eq(key, *state.str_ignore_dst) {
            got_ignore_dst = true;
        } else if eq(key, *state.str_stale_offset_ok) {
            suppress_stale = value.is_truthy()?;
        } else if eq(key, *state.str_offset) {
            offset = Some(Offset::from_py(value, *state.time_delta_type)?);
        } else {
            return Ok(false);
        }
        Ok(true)
    })?;

    if got_ignore_dst {
        warn_with_class(*state.warn_deprecation, doc::IGNORE_DST_DEPRECATED_MSG, 1)?;
    }
    if !suppress_stale {
        offset_stale_warning(state, doc::OFFSET_FROM_TIMESTAMP_STALE_MSG)?;
    }

    offset.ok_or_type_err("missing required keyword argument: 'offset'")
}

fn from_timestamp(
    cls: PyClass<OffsetDateTime>,
    args: &[PyObj],
    kwargs: &mut IterKwargs,
) -> PyReturn {
    let state = cls.state();
    let offset = check_from_timestamp_args_return_offset("from_timestamp", args, kwargs, state)?;

    if let Some(py_int) = args[0].cast_allow_subclass::<PyInt>() {
        Instant::from_timestamp(py_int.to_i64()?)
    } else if let Some(py_float) = args[0].cast_allow_subclass::<PyFloat>() {
        Instant::from_timestamp_f64(py_float.to_f64()?)
    } else {
        raise_type_err("timestamp must be an integer or float")?
    }
    .ok_or_range_err()?
    .to_offset(offset)
    .ok_or_range_err()?
    .to_obj(cls)
}

fn from_timestamp_millis(
    cls: PyClass<OffsetDateTime>,
    args: &[PyObj],
    kwargs: &mut IterKwargs,
) -> PyReturn {
    let state = cls.state();
    let offset =
        check_from_timestamp_args_return_offset("from_timestamp_millis", args, kwargs, state)?;
    Instant::from_timestamp_millis(args[0].expect_int("timestamp")?.to_i64()?)
        .ok_or_range_err()?
        .to_offset(offset)
        .ok_or_range_err()?
        .to_obj(cls)
}

fn from_timestamp_nanos(
    cls: PyClass<OffsetDateTime>,
    args: &[PyObj],
    kwargs: &mut IterKwargs,
) -> PyReturn {
    let state = cls.state();
    let offset =
        check_from_timestamp_args_return_offset("from_timestamp_nanos", args, kwargs, state)?;
    Instant::from_timestamp_nanos(args[0].expect_int("timestamp")?.to_i128()?)
        .ok_or_range_err()?
        .to_offset(offset)
        .ok_or_range_err()?
        .to_obj(cls)
}

fn parse_strptime(
    cls: PyClass<OffsetDateTime>,
    args: &[PyObj],
    kwargs: &mut IterKwargs,
) -> PyReturn {
    let state = cls.state();
    warn_with_class(
        *state.warn_deprecation,
        c"parse_strptime() is deprecated; use parse() with a format pattern instead.",
        1,
    )?;
    let format_obj = match kwargs.next() {
        Some((key, value)) if kwargs.len() == 1 && unicode_eq(key, *state.str_format) => value,
        _ => raise_type_err("parse_strptime() requires exactly one keyword argument `format`")?,
    };
    let &[arg_obj] = args else {
        raise_type_err(format!(
            "parse_strptime() takes exactly 1 positional argument, got {}",
            args.len()
        ))?
    };

    let parsed = state
        .strptime
        .get()?
        .call_args([arg_obj, format_obj])?
        .cast_exact::<PyDateTime>()
        .ok_or_type_err("strptime() returned non-datetime")?;

    OffsetDateTime::from_stdlib_datetime(*parsed)?.to_obj(cls)
}

fn format_rfc2822(_: PyType, slf: OffsetDateTime) -> PyReturn {
    let fmt = rfc2822::format(slf);
    // SAFETY: we know the format is ASCII only
    unsafe { std::str::from_utf8_unchecked(&fmt[..]) }.to_py()
}

fn parse_rfc2822(cls: PyClass<OffsetDateTime>, arg: PyObj) -> PyReturn {
    let s = arg
        .cast_allow_subclass::<PyStr>()
        .ok_or_type_err("expected a string")?;
    let (date, time, offset) =
        rfc2822::parse(s.as_utf8()?).ok_or_else_value_err(|| format!("Invalid format: {arg}"))?;
    date.at(time)
        .assume_offset(offset)
        .ok_or_range_err()?
        .to_obj(cls)
}

fn round(
    cls: PyClass<OffsetDateTime>,
    slf: OffsetDateTime,
    args: &[PyObj],
    kwargs: &mut IterKwargs,
) -> PyReturn {
    let state = cls.state();
    let round::Args {
        increment,
        mode,
        got_ignore_dst,
        suppress_stale,
    } = round::Args::parse(args, kwargs, state, round::ArgsContext::Offset)?;
    if got_ignore_dst {
        warn_with_class(*state.warn_deprecation, doc::IGNORE_DST_DEPRECATED_MSG, 1)?;
    }
    if !suppress_stale {
        offset_stale_warning(state, doc::OFFSET_ROUND_STALE_MSG)?;
    }
    let round_nanos = match increment {
        round::RoundIncrement::Day => NS_PER_DAY,
        round::RoundIncrement::Exact(ns) => ns.get(),
    };
    let OffsetDateTime {
        mut date,
        time,
        offset,
    } = slf;
    let (time_rounded, next_day) = time.round(round_nanos, mode);
    if next_day == 1 {
        date = date.tomorrow().ok_or_range_err()?;
    }
    OffsetDateTime {
        date,
        time: time_rounded,
        offset,
    }
    .to_obj(cls)
}

fn since(
    cls: PyClass<OffsetDateTime>,
    slf: OffsetDateTime,
    args: &[PyObj],
    kwargs: &mut IterKwargs,
) -> PyReturn {
    offset_since(cls, slf, args, kwargs, false)
}

fn until(
    cls: PyClass<OffsetDateTime>,
    slf: OffsetDateTime,
    args: &[PyObj],
    kwargs: &mut IterKwargs,
) -> PyReturn {
    offset_since(cls, slf, args, kwargs, true)
}

#[inline(never)]
fn offset_since(
    cls: PyClass<OffsetDateTime>,
    slf: OffsetDateTime,
    args: &[PyObj],
    kwargs: &mut IterKwargs,
    flip: bool,
) -> PyReturn {
    let fname = if flip { "until" } else { "since" };
    let state = cls.state();

    let other = handle_one_arg(fname, args)?
        .extract(cls)
        .ok_or_type_err("argument must be a whenever.OffsetDateTime")?;

    let same_offset = slf.offset == other.offset;

    match DifferenceSpec::parse(fname, kwargs, state)? {
        DifferenceSpec::Total(unit) => {
            let (a, b) = if flip { (other, slf) } else { (slf, other) };
            // Single unit: return float
            match unit.to_exact(false) {
                Ok(u) => {
                    // Exact unit: absolute time difference.
                    // For nanoseconds (in_nanos == 1), return int to preserve full precision.
                    let nanos = a.to_instant().diff(b.to_instant()).total_nanos();
                    let unit_nanos = u.in_nanos();
                    if unit_nanos == 1 {
                        nanos.to_py()
                    } else {
                        (nanos as f64 / unit_nanos as f64).to_py()
                    }
                }
                Err(_) => {
                    // Calendar unit: requires same offset, delegate to plain float
                    if !same_offset {
                        return raise_value_err(
                            "Calendar units can only be used to compare OffsetDateTimes \
                             with the same offset",
                        );
                    }
                    // OffsetDateTime.since() never warns; same-offset calendar
                    // units are well-defined and exact units are always correct.
                    plain_datetime::plain_since_inner(
                        state,
                        a.to_plain(),
                        b.to_plain(),
                        DifferenceSpec::Total(unit),
                        false, // flip already applied above
                    )
                }
            }
        }
        DifferenceSpec::InUnits {
            units,
            mode,
            increment,
        } => {
            match (units.has_calendar(), same_offset) {
                // same offset: use the plain datetime rounding logic (days are always 24h)
                (true, true) => plain_datetime::plain_since_inner(
                    state,
                    slf.to_plain(),
                    other.to_plain(),
                    DifferenceSpec::InUnits {
                        units,
                        mode,
                        increment,
                    },
                    flip,
                ),
                (true, false) => raise_value_err(
                    "Calendar units can only be used to compare OffsetDateTimes \
                     with the same offset",
                ),
                _ => {
                    // Different offsets, exact units only: compute via TimeDelta
                    let (a, b) = if flip { (other, slf) } else { (slf, other) };
                    let diff = a.to_instant().diff(b.to_instant());
                    let abs_mode = mode.to_abs_euclid(diff.is_negative());
                    let result = diff
                        .in_exact_units(
                            // SAFETY: we've already checked there are only exact units
                            units.to_exact_assuming_24h_days().unwrap(),
                            increment,
                            abs_mode,
                        )
                        .ok_or_range_err()?;
                    result.to_obj(state)
                }
            }
        }
    }
}

fn format(_: PyClass<OffsetDateTime>, slf: OffsetDateTime, pattern_obj: PyObj) -> PyReturn {
    let pattern_pystr = pattern_obj
        .cast_exact::<PyStr>()
        .ok_or_type_err("format() argument must be str")?;
    let pattern_str = pattern_pystr.as_utf8()?;
    let pattern = pattern::CompiledPattern::compile(pattern_str).into_value_err()?;
    pattern.validate(pattern::CategorySet::DATE_TIME_OFFSET, "OffsetDateTime")?;
    pattern.warn_if_ambiguous_12h()?;
    pattern.format(&slf.to_plain().pattern_values().with_offset(slf.offset))
}

fn __format__(cls: PyClass<OffsetDateTime>, slf: OffsetDateTime, spec_obj: PyObj) -> PyReturn {
    if spec_obj.is_truthy()? {
        format(cls, slf, spec_obj)
    } else {
        __str__(cls.into(), slf)
    }
}

fn parse(cls: PyClass<OffsetDateTime>, args: &[PyObj], kwargs: &mut IterKwargs) -> PyReturn {
    let &[s_obj] = args else {
        raise_type_err(format!(
            "parse() takes exactly 1 positional argument ({} given)",
            args.len()
        ))?
    };
    let s_pystr = s_obj
        .cast_exact::<PyStr>()
        .ok_or_type_err("parse() argument must be str")?;
    let s = s_pystr.as_utf8()?;

    let fmt_obj = handle_one_kwarg("parse", *cls.state().str_format, kwargs)?.ok_or_else(|| {
        raise_type_err::<(), _>("parse() requires 'format' keyword argument").unwrap_err()
    })?;
    let fmt_pystr = fmt_obj
        .cast_exact::<PyStr>()
        .ok_or_type_err("format must be str")?;
    let fmt_bytes = fmt_pystr.as_utf8()?;

    let pattern = pattern::CompiledPattern::compile(fmt_bytes).into_value_err()?;
    pattern.validate(pattern::CategorySet::DATE_TIME_OFFSET, "OffsetDateTime")?;
    let parsed = pattern.parse(s).into_value_err()?;
    let offset = parsed
        .offset_secs
        .ok_or_value_err("OffsetDateTime.parse() pattern must include an offset field (x/X)")?;
    let date = parsed
        .date("Pattern must include year (YYYY/YY), month (MM/MMM/MMMM), and day (DD) fields")?;
    parsed.validate_weekday(date)?;
    let time = parsed.time()?;
    // offset is already validated (scalar::Offset) — no range check needed here.
    date.at(time)
        .assume_offset(offset)
        .ok_or_range_err()?
        .to_obj(cls)
}

static mut METHODS: &[PyMethodDef] = &[
    COPY_METHOD,
    DEEPCOPY_METHOD,
    method0!(OffsetDateTime, __reduce__, c""),
    classmethod_kwargs!(OffsetDateTime, now, doc::OFFSETDATETIME_NOW),
    method1!(OffsetDateTime, exact_eq, doc::EXACTTIME_EXACT_EQ),
    method0!(OffsetDateTime, to_stdlib, doc::BASICCONVERSIONS_TO_STDLIB),
    method0!(
        OffsetDateTime,
        py_datetime,
        doc::BASICCONVERSIONS_PY_DATETIME
    ),
    classmethod1!(
        OffsetDateTime,
        from_py_datetime,
        doc::BASICCONVERSIONS_FROM_PY_DATETIME
    ),
    method0!(
        OffsetDateTime,
        to_instant,
        doc::EXACTANDLOCALTIME_TO_INSTANT
    ),
    method0!(OffsetDateTime, to_plain, doc::EXACTANDLOCALTIME_TO_PLAIN),
    method1!(OffsetDateTime, to_tz, doc::EXACTTIME_TO_TZ),
    method_vararg!(
        OffsetDateTime,
        to_fixed_offset,
        doc::EXACTTIME_TO_FIXED_OFFSET
    ),
    method0!(OffsetDateTime, to_system_tz, doc::EXACTTIME_TO_SYSTEM_TZ),
    method_kwargs!(OffsetDateTime, assume_tz, doc::OFFSETDATETIME_ASSUME_TZ),
    method0!(OffsetDateTime, date, doc::LOCALTIME_DATE),
    method0!(OffsetDateTime, time, doc::LOCALTIME_TIME),
    method0!(OffsetDateTime, day_of_year, doc::LOCALTIME_DAY_OF_YEAR),
    method0!(OffsetDateTime, days_in_month, doc::LOCALTIME_DAYS_IN_MONTH),
    method0!(OffsetDateTime, days_in_year, doc::LOCALTIME_DAYS_IN_YEAR),
    method0!(OffsetDateTime, in_leap_year, doc::LOCALTIME_IN_LEAP_YEAR),
    method_kwargs!(OffsetDateTime, start_of, doc::OFFSETDATETIME_START_OF),
    method_kwargs!(OffsetDateTime, end_of, doc::OFFSETDATETIME_END_OF),
    method0!(
        OffsetDateTime,
        format_rfc2822,
        doc::OFFSETDATETIME_FORMAT_RFC2822
    ),
    classmethod1!(
        OffsetDateTime,
        parse_rfc2822,
        doc::OFFSETDATETIME_PARSE_RFC2822
    ),
    method_kwargs!(OffsetDateTime, format_iso, doc::OFFSETDATETIME_FORMAT_ISO),
    classmethod1!(OffsetDateTime, parse_iso, doc::OFFSETDATETIME_PARSE_ISO),
    method0!(OffsetDateTime, timestamp, doc::EXACTTIME_TIMESTAMP),
    method0!(
        OffsetDateTime,
        timestamp_millis,
        doc::EXACTTIME_TIMESTAMP_MILLIS
    ),
    method0!(
        OffsetDateTime,
        timestamp_nanos,
        doc::EXACTTIME_TIMESTAMP_NANOS
    ),
    classmethod_kwargs!(
        OffsetDateTime,
        from_timestamp,
        doc::OFFSETDATETIME_FROM_TIMESTAMP
    ),
    classmethod_kwargs!(
        OffsetDateTime,
        from_timestamp_millis,
        doc::OFFSETDATETIME_FROM_TIMESTAMP_MILLIS
    ),
    classmethod_kwargs!(
        OffsetDateTime,
        from_timestamp_nanos,
        doc::OFFSETDATETIME_FROM_TIMESTAMP_NANOS
    ),
    method_kwargs!(OffsetDateTime, replace, doc::OFFSETDATETIME_REPLACE),
    method_kwargs!(
        OffsetDateTime,
        replace_date,
        doc::OFFSETDATETIME_REPLACE_DATE
    ),
    method_kwargs!(
        OffsetDateTime,
        replace_time,
        doc::OFFSETDATETIME_REPLACE_TIME
    ),
    classmethod_kwargs!(
        OffsetDateTime,
        parse_strptime,
        doc::OFFSETDATETIME_PARSE_STRPTIME
    ),
    method_kwargs!(OffsetDateTime, add, doc::OFFSETDATETIME_ADD),
    method_kwargs!(OffsetDateTime, subtract, doc::OFFSETDATETIME_SUBTRACT),
    method1!(OffsetDateTime, difference, doc::EXACTTIME_DIFFERENCE),
    method_kwargs!(OffsetDateTime, round, doc::OFFSETDATETIME_ROUND),
    method_kwargs!(OffsetDateTime, since, doc::OFFSETDATETIME_SINCE),
    method_kwargs!(OffsetDateTime, until, doc::OFFSETDATETIME_UNTIL),
    method1!(OffsetDateTime, format, doc::OFFSETDATETIME_FORMAT),
    method1!(OffsetDateTime, __format__, c""),
    classmethod_kwargs!(OffsetDateTime, parse, doc::OFFSETDATETIME_PARSE),
    classmethod_kwargs!(
        OffsetDateTime,
        __get_pydantic_core_schema__,
        doc::PYDANTIC_SCHEMA
    ),
    PyMethodDef::zeroed(),
];

fn year(_: PyType, slf: OffsetDateTime) -> PyReturn {
    slf.date.year.get().to_py()
}

fn month(_: PyType, slf: OffsetDateTime) -> PyReturn {
    slf.date.month.get().to_py()
}

fn day(_: PyType, slf: OffsetDateTime) -> PyReturn {
    slf.date.day.to_py()
}

fn hour(_: PyType, slf: OffsetDateTime) -> PyReturn {
    slf.time.hour.to_py()
}

fn minute(_: PyType, slf: OffsetDateTime) -> PyReturn {
    slf.time.minute.to_py()
}

fn second(_: PyType, slf: OffsetDateTime) -> PyReturn {
    slf.time.second.to_py()
}

fn nanosecond(_: PyType, slf: OffsetDateTime) -> PyReturn {
    slf.time.subsec.get().to_py()
}

fn offset(cls: PyClass<OffsetDateTime>, slf: OffsetDateTime) -> PyReturn {
    slf.offset.to_delta().to_obj(*cls.state().time_delta_type)
}

static mut GETSETTERS: &[PyGetSetDef] = &[
    getter!(OffsetDateTime, year, doc::LOCALTIME_YEAR),
    getter!(OffsetDateTime, month, doc::LOCALTIME_MONTH),
    getter!(OffsetDateTime, day, doc::LOCALTIME_DAY),
    getter!(OffsetDateTime, hour, doc::LOCALTIME_HOUR),
    getter!(OffsetDateTime, minute, doc::LOCALTIME_MINUTE),
    getter!(OffsetDateTime, second, doc::LOCALTIME_SECOND),
    getter!(OffsetDateTime, nanosecond, doc::LOCALTIME_NANOSECOND),
    getter!(OffsetDateTime, offset, doc::EXACTANDLOCALTIME_OFFSET),
    PyGetSetDef {
        name: NULL(),
        get: None,
        set: None,
        doc: NULL(),
        closure: NULL(),
    },
];

pub(crate) static mut SPEC: PyType_Spec =
    type_spec::<OffsetDateTime>(c"whenever.OffsetDateTime", unsafe { SLOTS });
