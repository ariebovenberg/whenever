use crate::{
    classes::{
        date::Date,
        instant::Instant,
        offset_datetime::{OffsetDateTime, OffsetMismatch},
        plain_datetime::{DateTimeBoundaryUnit, PlainDateTime},
        time::Time,
        time_delta::TimeDelta,
    },
    common::{
        compat::{RenamedKeyword, warn_deprecated},
        disambiguation::*,
        fmt,
        format_args::{self, Suffix},
        instant::{
            TimestampUnit, extract_instant, parse_instant_arg, parse_timestamp,
            parse_timestamp_millis, parse_timestamp_nanos,
        },
        parse::Scan,
        pattern, pickle, round_args as round,
        shift_args::{parse_datetime_shift_arg, parse_datetime_shift_kwargs},
    },
    docstrings as doc,
    domain::{
        difference::{self, CalendarIncrement, DifferenceSpec},
        local::{LocalMapping, ResolveError, ResolvePolicy},
        scalar::*,
        shift::DateTimeShift,
    },
    py::*,
    pymodule::State,
    tz::tzif::TimeZone,
};
use core::{
    ffi::{c_int, c_void},
    ptr::null_mut as NULL,
};
use pyo3_ffi::*;
use std::{ffi::CString, sync::Arc};

pub(crate) use crate::domain::zoned_datetime::{
    OffsetInIsoString, TzFormat, ZonedDateTime, read_offset_and_tzname, zoned_since_in_units,
    zoned_target,
};

impl ZonedDateTime {
    pub(crate) fn shift(
        &self,
        shift: DateTimeShift,
        dis: Option<Disambiguation>,
        state: &State,
        cls: PyClass<Self>,
    ) -> PyReturn {
        let DateTimeShift { calendar, time } = shift;
        let shifted_by_date = if !calendar.is_zero() {
            self.date
                .shift_by(calendar)
                .ok_or_range_err()?
                .at(self.time)
                .resolve_or_raise(
                    &self.tz,
                    dis.map_or(
                        ResolvePolicy::PreserveOffset(self.offset),
                        ResolvePolicy::Disambiguate,
                    ),
                    state,
                )?
        } else {
            self.to_fixed_offset()
        };

        shifted_by_date
            .to_instant()
            .shift(time)
            .ok_or_range_err()?
            .into_zoned_obj(self.tz.clone(), cls)
    }

    fn to_stdlib_datetime(&self, state: &State) -> PyReturn {
        // Get UTC date and time, then use ZoneInfo.fromutc() to preserve the instant if
        // ZoneInfo disagrees with our offset.
        let utc = self
            .to_plain()
            .shift_by_offset(-self.offset.as_offset_delta())
            // SAFETY: the UTC date and time are valid.
            .unwrap();
        let api = state.py_api()?;
        let tzinfo = match self.tz.key.as_ref() {
            Some(key) => state.zoneinfo_type.get()?.call1(*key.as_str().to_py()?),
            None => api.new_timezone(self.offset),
        }?;

        let dt = api.new_datetime(utc, Some(*tzinfo))?;
        tzinfo.getattr(c"fromutc")?.call1(*dt)
    }
}

impl PlainDateTime {
    pub(crate) fn resolve_with_disambiguation(
        self,
        tz: &TimeZone,
        disambiguation: Option<Disambiguation>,
        state: &State,
    ) -> PyResult<OffsetDateTime> {
        let mapping = tz.mapping_for_local(self.local_seconds());
        let disambiguation = match disambiguation {
            Some(d) => d,
            None => {
                if !matches!(mapping, LocalMapping::Unique { .. }) {
                    warn_with_class(
                        *state.warn_implicit_disambiguation,
                        doc::IMPLICIT_DISAMBIGUATION_MSG,
                        1,
                    )?;
                }
                Disambiguation::Compatible
            }
        };
        self.resolve_mapping_or_raise(
            mapping,
            ResolvePolicy::Disambiguate(disambiguation),
            tz,
            state,
        )
    }

    pub(crate) fn resolve_or_raise(
        self,
        tz: &TimeZone,
        policy: ResolvePolicy,
        state: &State,
    ) -> PyResult<OffsetDateTime> {
        self.resolve_mapping_or_raise(
            tz.mapping_for_local(self.local_seconds()),
            policy,
            tz,
            state,
        )
    }

    fn resolve_mapping_or_raise(
        self,
        mapping: LocalMapping,
        policy: ResolvePolicy,
        tz: &TimeZone,
        state: &State,
    ) -> PyResult<OffsetDateTime> {
        match mapping.resolve(self, policy) {
            Ok(resolved) => Ok(resolved),
            Err(ResolveError::Fold) => raise(
                *state.exc_repeated,
                format!(
                    "{} {} is repeated in {}",
                    self.date,
                    self.time,
                    tz_err_display(&tz.key)
                ),
            ),
            Err(ResolveError::Gap) => raise(
                *state.exc_skipped,
                format!(
                    "{} {} is skipped in {}",
                    self.date,
                    self.time,
                    tz_err_display(&tz.key)
                ),
            ),
            Err(ResolveError::OutOfRange) => raise_range_err(),
        }
    }
}

impl PyPayload for ZonedDateTime {}

impl Instant {
    /// Convert an instant to a zoned datetime, ready to be returned to Python.
    pub(crate) fn into_zoned_obj(self, tz: Arc<TimeZone>, cls: PyClass<ZonedDateTime>) -> PyReturn {
        self.in_timezone(tz).ok_or_range_err()?.to_obj(cls)
    }
}

impl OffsetDateTime {
    pub(crate) fn into_zoned_obj_unchecked(
        self,
        tz: Arc<TimeZone>,
        cls: PyClass<ZonedDateTime>,
    ) -> PyReturn {
        self.into_zoned_unchecked(tz).to_obj(cls)
    }
}

fn __new__(cls: PyClass<ZonedDateTime>, args: PyTuple, kwargs: Option<PyDict>) -> PyReturn {
    // Alternate constructor: one ISO 8601 string or stdlib datetime argument
    if args.len() == 1 {
        let arg = args.iter().next().unwrap();
        if PyStr::isinstance(arg) {
            let (dis, mismatch) = match kwargs {
                Some(d) => parse_iso_kwargs(d.iteritems(), "ZonedDateTime", false, cls.state())?,
                None => parse_iso_kwargs(
                    std::iter::empty::<(PyObj, PyObj)>(),
                    "ZonedDateTime",
                    false,
                    cls.state(),
                )?,
            };
            return parse_iso_inner(cls, arg, dis, mismatch);
        }
        if kwargs.map_or(0, |d| d.len()) == 0 {
            if let Some(dt) = arg.cast_allow_subclass::<PyDateTime>() {
                return from_stdlib_datetime_inner(cls, dt);
            }
            return raise_type_err(
                "ZonedDateTime() requires an ISO 8601 string or datetime.datetime",
            );
        }
    };

    let state = cls.state();
    let mut year: i64 = 0;
    let mut month: i64 = 0;
    let mut day: i64 = 0;
    let mut hour: i64 = 0;
    let mut minute: i64 = 0;
    let mut second: i64 = 0;
    let mut nanosecond: i64 = 0;
    let mut tz: *mut PyObject = NULL();
    let mut disambiguation: *mut PyObject = NULL();
    let mut disambiguate: *mut PyObject = NULL();

    let fmt = if IS_LP64 {
        c"lll|lll$lOOO:ZonedDateTime"
    } else {
        c"LLL|LLL$LOOO:ZonedDateTime"
    };
    parse_args_kwargs!(
        args,
        kwargs,
        fmt,
        year,
        month,
        day,
        hour,
        minute,
        second,
        nanosecond,
        tz,
        disambiguation,
        disambiguate
    );

    let tz = state.load_tz(
        tz.borrow_opt()
            .ok_or_type_err("`tz` argument is required")?,
    )?;
    let date = Date::from_i64_components(year, month, day).ok_or_value_err("invalid date")?;
    let time = Time::from_i64_components(hour, minute, second, nanosecond)
        .ok_or_value_err("invalid time")?;
    let mut dis_arg = DisambiguationArg::default();
    if let Some(value) = disambiguation.borrow_opt() {
        dis_arg.set_new(value);
    }
    if let Some(value) = disambiguate.borrow_opt() {
        dis_arg.set_old(value);
    }
    let dis = dis_arg.finish("ZonedDateTime", state)?;
    date.at(time)
        .resolve_with_disambiguation(&tz, dis, state)?
        .into_zoned_obj_unchecked(tz, cls)
}

extern "C" fn dealloc(arg: PyObj) {
    // SAFETY: in dealloc we have exclusive access. We must drop the Arc<TimeZone>
    // before freeing the memory, since generic_dealloc won't run Rust destructors.
    unsafe {
        let ptr = &raw mut (*(arg.as_ptr() as *mut PyObjectLayout<ZonedDateTime>)).data;
        std::ptr::drop_in_place(ptr);
    }
    generic_dealloc(arg)
}

fn __repr__(_: PyType, slf: &ZonedDateTime) -> PyReturn {
    let ZonedDateTime {
        date,
        time,
        offset,
        ref tz,
    } = *slf;
    PyAsciiStrBuilder::format((
        b"ZonedDateTime(\"",
        date.iso_format(false),
        b' ',
        time.iso_format(fmt::Precision::Auto, false),
        offset.iso_format(false),
        b'[',
        &tz.key
            .as_deref()
            .unwrap_or("<system timezone without ID>")
            .as_bytes(),
        b"]\")",
    ))
}

fn __str__(_: PyType, slf: &ZonedDateTime) -> PyReturn {
    let ZonedDateTime {
        date,
        time,
        offset,
        ref tz,
    } = *slf;
    PyAsciiStrBuilder::format((
        date.iso_format(false),
        b'T',
        time.iso_format(fmt::Precision::Auto, false),
        offset.iso_format(false),
        TzFormat { tz },
    ))
}

fn __richcmp__(
    cls: PyClass<ZonedDateTime>,
    a: &ZonedDateTime,
    b_obj: PyObj,
    op: c_int,
) -> PyReturn {
    let inst_a = a.to_instant();
    let Some(inst_b) = extract_instant(b_obj, cls.state()) else {
        return not_implemented();
    };
    CompareOp::from_ffi(op).apply(inst_a, inst_b).to_py()
}

extern "C" fn __hash__(arg: PyObj) -> Py_hash_t {
    // SAFETY: the first arg to this function is the self type
    let (_, slf) = unsafe { arg.assume_heaptype_ref::<ZonedDateTime>() };
    hashmask(slf.to_instant().python_hash())
}

fn __add__(a_obj: PyObj, b_obj: PyObj) -> PyReturn {
    binary_operation::<ZonedDateTime>(a_obj, b_obj, "+", |operands| {
        let BinaryCall::ExtTypes { cls, slf, other } = operands else {
            return Ok(None);
        };
        shift_operator(cls.state(), cls, &slf, other, false)
    })
}

fn __sub__(a_obj: PyObj, b_obj: PyObj) -> PyReturn {
    binary_operation::<ZonedDateTime>(a_obj, b_obj, "-", |operands| {
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
        if let Some(i) = extract_instant(other, state) {
            Ok(Some(
                slf.to_instant().diff(i).to_obj(*state.time_delta_type)?,
            ))
        } else {
            shift_operator(state, slf.class(), &slf, other, true)
        }
    })
}

fn shift_operator(
    state: &State,
    cls: PyClass<ZonedDateTime>,
    slf: &ZonedDateTime,
    arg: PyObj,
    negate: bool,
) -> PyResult<Option<Owned<PyObj>>> {
    let shift = if let Some(time) = arg.extract(*state.time_delta_type) {
        time.to_shift()
    } else {
        return Ok(None);
    };

    Ok(Some(slf.shift(
        shift.negate_if(negate),
        None,
        state,
        cls,
    )?))
}

#[allow(static_mut_refs)]
static mut SLOTS: &[PyType_Slot] = &[
    slotmethod!(ZonedDateTime, Py_tp_new, __new__),
    slotmethod!(ZonedDateTime, Py_tp_str, __str__, 1),
    slotmethod!(ZonedDateTime, Py_tp_repr, __repr__, 1),
    slotmethod!(ZonedDateTime, Py_tp_richcompare, __richcmp__),
    slotmethod!(Py_nb_add, __add__, 2),
    slotmethod!(Py_nb_subtract, __sub__, 2),
    PyType_Slot {
        slot: Py_tp_doc,
        pfunc: doc::ZONEDDATETIME.as_ptr() as *mut c_void,
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
        pfunc: dealloc as *mut c_void,
    },
    PyType_Slot {
        slot: 0,
        pfunc: NULL(),
    },
];

fn strict_eq(cls: PyClass<ZonedDateTime>, slf: &ZonedDateTime, obj_b: PyObj) -> PyReturn {
    if let Some(zdt) = obj_b.extract_ref(cls) {
        (slf == zdt).to_py()
    } else {
        raise_type_err("can't compare different types")?
    }
}

fn exact_eq(cls: PyClass<ZonedDateTime>, slf: &ZonedDateTime, obj_b: PyObj) -> PyReturn {
    warn_deprecated(
        cls.state(),
        c"exact_eq() is deprecated; use strict_eq() instead",
        1,
    )?;
    strict_eq(cls, slf, obj_b)
}

fn to_tz(cls: PyClass<ZonedDateTime>, slf: PyRef<'_, ZonedDateTime>, tz_obj: PyObj) -> PyReturn {
    let tz = cls.state().load_tz(tz_obj)?;
    // Cached timezones normally share an Arc. Avoid comparing every transition in that common case.
    if Arc::ptr_eq(&tz, &slf.tz) || *tz == *slf.tz {
        Ok(slf.newref())
    } else {
        slf.to_instant().into_zoned_obj(tz, cls)
    }
}

pub(crate) fn unpickle(state: &State, args: &[PyObj]) -> PyReturn {
    let &[data, tz_obj] = args else {
        raise_type_err(pickle::INVALID_DATA)?
    };
    let stored =
        pickle::decode_offset(data.expect_bytes()?).ok_or_value_err(pickle::INVALID_DATA)?;
    let tz = state.tz_store.obj_get(tz_obj)?;
    let result = stored.to_instant().in_timezone(tz).ok_or_range_err()?;
    if result.offset != stored.offset {
        let message = CString::new(format!(
            "the ZonedDateTime pickle stored {} {} with offset {} for timezone {:?}, but the current timezone rules map that instant to {} {} with offset {}; the instant was preserved and the local datetime and offset were updated",
            stored.date,
            stored.time,
            stored.offset,
            result.tz.key.as_deref().unwrap_or("<unknown>"),
            result.date,
            result.time,
            result.offset,
        ))
        .unwrap();
        warn_with_class(*state.warn_pickle_offset_mismatch, &message, 1)?;
    }
    result.to_obj(*state.zoned_datetime_type)
}

fn to_stdlib(cls: PyClass<ZonedDateTime>, slf: &ZonedDateTime) -> PyReturn {
    let state = cls.state();
    slf.to_stdlib_datetime(state)
}

fn to_instant(cls: PyClass<ZonedDateTime>, slf: &ZonedDateTime) -> PyReturn {
    slf.to_instant().to_obj(*cls.state().instant_type)
}

fn to_fixed_offset(cls: PyClass<ZonedDateTime>, slf: &ZonedDateTime, args: &[PyObj]) -> PyReturn {
    let state = cls.state();
    match handle_opt_arg("to_fixed_offset", args)? {
        None => slf.to_plain().assume_offset_unchecked(slf.offset),
        Some(arg) => slf
            .to_instant()
            .to_offset(Offset::from_py(arg, state)?)
            .ok_or_range_err()?,
    }
    .to_obj(*state.offset_datetime_type)
}

fn to_system_tz(cls: PyClass<ZonedDateTime>, slf: &ZonedDateTime) -> PyReturn {
    warn_deprecated(
        cls.state(),
        c"to_system_tz() is deprecated; use to_tz(SYSTEM_TZ) instead",
        1,
    )?;
    slf.to_instant()
        .into_zoned_obj(cls.state().tz_store.get_system_tz()?, cls)
}

fn date(cls: PyClass<ZonedDateTime>, slf: &ZonedDateTime) -> PyReturn {
    slf.date.to_obj(*cls.state().date_type)
}

fn time(cls: PyClass<ZonedDateTime>, slf: &ZonedDateTime) -> PyReturn {
    slf.time.to_obj(*cls.state().time_type)
}

fn day_of_year(_: PyClass<ZonedDateTime>, slf: &ZonedDateTime) -> PyReturn {
    slf.date.day_of_year().to_py()
}

fn days_in_month(_: PyClass<ZonedDateTime>, slf: &ZonedDateTime) -> PyReturn {
    slf.date.days_in_month().to_py()
}

fn days_in_year(_: PyClass<ZonedDateTime>, slf: &ZonedDateTime) -> PyReturn {
    slf.date.days_in_year().to_py()
}

fn in_leap_year(_: PyClass<ZonedDateTime>, slf: &ZonedDateTime) -> PyReturn {
    slf.date.is_in_leap_year().to_py()
}

fn start_of(cls: PyClass<ZonedDateTime>, slf: &ZonedDateTime, unit_obj: PyObj) -> PyReturn {
    let unit = DateTimeBoundaryUnit::from_py(unit_obj, cls.state())?;

    // Behavior differs:
    // 1. Calendar units always consume folds. A unit is only "started" once
    //    with the next "start of day/week/month/year".
    // 2. Other units consume folds under certain conditions, but not always.
    match unit {
        DateTimeBoundaryUnit::Date(_) | DateTimeBoundaryUnit::Day => slf
            .to_plain()
            .start_of_unit(unit)
            .ok_or_range_err()?
            .resolve_compatible(&slf.tz)
            .ok_or_range_err()?
            .into_zoned_obj_unchecked(slf.tz.clone(), cls),
        DateTimeBoundaryUnit::Time(_) => {
            let start_local = slf.to_plain().start_of_unit(unit).ok_or_range_err()?;
            match slf.tz.mapping_for_local(start_local.local_seconds()) {
                LocalMapping::Unique { offset } => start_local.assume_offset(offset),
                LocalMapping::Fold { before, after, .. } => {
                    // Use the 'later' part of the fold if we're already in it.
                    // Otherwise, use the earlier part.
                    start_local.assume_offset(if after == slf.offset { after } else { before })
                }
                LocalMapping::Gap {
                    transition, after, ..
                } => transition
                    .datetime(start_local.time.subsec)
                    .assume_offset(after),
            }
        }
        .ok_or_range_err()?
        .into_zoned_obj_unchecked(slf.tz.clone(), cls),
    }
}

fn end_of(cls: PyClass<ZonedDateTime>, slf: &ZonedDateTime, unit_obj: PyObj) -> PyReturn {
    let unit = DateTimeBoundaryUnit::from_py(unit_obj, cls.state())?;

    // Behavior differs:
    // 1. Calendar units always consume folds--so that it seamlessly lines up
    //    with the next "start of day/week/month/year".
    // 2. Other units consume folds under certain conditions, but not always.
    match unit {
        DateTimeBoundaryUnit::Date(_) | DateTimeBoundaryUnit::Day => slf
            // Calculate the start of the next unit, then step back one ns.
            .to_plain()
            .next_start_of_unit(unit)
            .ok_or_range_err()?
            .resolve_compatible(&slf.tz)
            .ok_or_range_err()?
            .to_instant()
            .shift(-TimeDelta::RESOLUTION)
            .unwrap()
            .into_zoned_obj(slf.tz.clone(), cls),
        DateTimeBoundaryUnit::Time(u) => {
            let end_local = slf.to_plain().end_of_unit(unit).ok_or_range_err()?;
            let local_seconds = end_local.local_seconds();
            match slf.tz.mapping_for_local(local_seconds) {
                LocalMapping::Unique { offset } => end_local.assume_offset(offset),
                LocalMapping::Fold {
                    transition,
                    before,
                    after,
                } => {
                    end_local.assume_offset(
                        // Use the 'later' part of the fold if...
                        if
                        // ...(a) we're already in that part of the fold...
                        after == slf.offset ||
                        // ...or (b) we're exactly at the end of the fold, and the fold is
                        // shorter than the unit.
                        (local_seconds.get() + 1 == transition.get()
                            && before.sub(after).get() < u.in_secs())
                        {
                            after
                        } else {
                            before
                        },
                    )
                }
                LocalMapping::Gap {
                    transition,
                    before,
                    after,
                } => transition
                    .saturating_add_i32(-after.sub(before).get() - 1)
                    .datetime(SubSecNanos::MAX)
                    .assume_offset(before),
            }
        }
        .ok_or_range_err()?
        .into_zoned_obj_unchecked(slf.tz.clone(), cls),
    }
}

fn replace_date(
    cls: PyClass<ZonedDateTime>,
    slf: &ZonedDateTime,
    args: &[PyObj],
    kwargs: &mut IterKwargs,
) -> PyReturn {
    let state = cls.state();

    let arg = handle_one_arg("replace_date", args)?;

    let dis = Disambiguation::from_only_kwarg(kwargs, "replace_date", state)?;
    let ZonedDateTime {
        time,
        offset,
        ref tz,
        ..
    } = *slf;
    arg.extract(*state.date_type)
        .ok_or_type_err("date must be a whenever.Date")?
        .at(time)
        .resolve_or_raise(
            tz,
            dis.map_or(
                ResolvePolicy::PreserveOffset(offset),
                ResolvePolicy::Disambiguate,
            ),
            state,
        )?
        .into_zoned_obj_unchecked(tz.clone(), cls)
}

fn replace_time(
    cls: PyClass<ZonedDateTime>,
    slf: &ZonedDateTime,
    args: &[PyObj],
    kwargs: &mut IterKwargs,
) -> PyReturn {
    let state = cls.state();
    let arg = handle_one_arg("replace_time", args)?;

    let dis = Disambiguation::from_only_kwarg(kwargs, "replace_time", state)?;
    let ZonedDateTime {
        date,
        offset,
        ref tz,
        ..
    } = *slf;
    arg.extract(*state.time_type)
        .ok_or_type_err("time must be a whenever.Time instance")?
        .on(date)
        .resolve_or_raise(
            tz,
            dis.map_or(
                ResolvePolicy::PreserveOffset(offset),
                ResolvePolicy::Disambiguate,
            ),
            state,
        )?
        .into_zoned_obj_unchecked(tz.clone(), cls)
}

fn format_iso(
    cls: PyClass<ZonedDateTime>,
    slf: &ZonedDateTime,
    args: &[PyObj],
    kwargs: &mut IterKwargs,
) -> PyReturn {
    format_args::format_datetime_iso(
        slf.date,
        slf.time,
        cls.state(),
        args,
        kwargs,
        Suffix::OffsetTz(slf.offset, slf.tz.key.as_deref()),
    )
}

fn parse_iso(cls: PyClass<ZonedDateTime>, args: &[PyObj], kwargs: &mut IterKwargs) -> PyReturn {
    let arg = handle_one_arg("parse_iso", args)?;
    let (dis, mismatch) = parse_iso_kwargs(kwargs, "parse_iso", true, cls.state())?;
    parse_iso_inner(cls, arg, dis, mismatch)
}

fn parse_iso_kwargs<K>(
    kwargs: K,
    fname: &str,
    allow_deprecated: bool,
    state: &State,
) -> PyResult<(Option<Disambiguation>, OffsetMismatch)>
where
    K: IntoIterator<Item = (PyObj, PyObj)>,
{
    let mut dis_arg = DisambiguationArg::default();
    let mut mismatch = OffsetMismatch::Raise;
    handle_kwargs(fname, kwargs, |k, v, eq| {
        if eq(k, *state.str_offset_mismatch) {
            mismatch = OffsetMismatch::from_py(v, state)?;
        } else if allow_deprecated {
            if !dis_arg.handle_kwarg(k, v, eq, state) {
                return Ok(false);
            }
        } else if eq(k, *state.str_disambiguation) {
            dis_arg.set_new(v);
        } else {
            return Ok(false);
        }
        Ok(true)
    })?;
    Ok((dis_arg.finish(fname, state)?, mismatch))
}

fn matching_local_offset(mapping: LocalMapping, parsed: Offset, exact: bool) -> Option<Offset> {
    let matches = |offset: Offset| {
        let seconds = offset.get();
        let comparable = if exact {
            seconds
        } else {
            seconds.signum() * ((seconds.abs() + 30) / 60 * 60)
        };
        (comparable == parsed.get()).then_some(offset)
    };
    match mapping {
        LocalMapping::Unique { offset } => matches(offset),
        LocalMapping::Fold { before, after, .. } => matches(before).or_else(|| matches(after)),
        LocalMapping::Gap { .. } => None,
    }
}

fn parse_iso_inner(
    cls: PyClass<ZonedDateTime>,
    arg: PyObj,
    dis: Option<Disambiguation>,
    mismatch: OffsetMismatch,
) -> PyReturn {
    let py_str = arg
        .cast_allow_subclass::<PyStr>()
        // NOTE: this exception message also needs to make sense when
        // called through the constructor
        .ok_or_type_err("when parsing from ISO format, the argument must be str")?;
    let mut s = Scan::new(py_str.as_utf8()?);
    let (dt, (offset, tzstr)) = PlainDateTime::read_iso(&mut s)
        .zip(read_offset_and_tzname(&mut s))
        .ok_or_else_value_err(|| format!("Invalid format: {arg}"))?;
    let state = cls.state();
    let tz = state.tz_store.get(tzstr)?;
    let (offset, exact) = match offset {
        OffsetInIsoString::MinutePrecision(offset) => (offset, false),
        OffsetInIsoString::SecondPrecision(offset) => (offset, true),
        OffsetInIsoString::Z => return dt.assume_utc().into_zoned_obj(tz, cls),
        OffsetInIsoString::Missing => {
            return dt
                .resolve_with_disambiguation(&tz, dis, state)?
                .into_zoned_obj_unchecked(tz, cls);
        }
    };
    let mapping = tz.mapping_for_local(dt.local_seconds());
    if let Some(actual) = matching_local_offset(mapping, offset, exact) {
        return dt
            .assume_offset(actual)
            .ok_or_range_err()?
            .into_zoned_obj_unchecked(tz, cls);
    }
    match mismatch {
        OffsetMismatch::Raise => raise(
            *state.exc_invalid_offset,
            format!("invalid offset for {tzstr}"),
        ),
        OffsetMismatch::KeepInstant => dt
            .assume_offset(offset)
            .ok_or_range_err()?
            .to_instant()
            .into_zoned_obj(tz, cls),
        OffsetMismatch::KeepLocal => dt
            .resolve_with_disambiguation(&tz, dis, state)?
            .into_zoned_obj_unchecked(tz, cls),
    }
}

fn replace(
    cls: PyClass<ZonedDateTime>,
    slf: &ZonedDateTime,
    args: &[PyObj],
    kwargs: &mut IterKwargs,
) -> PyReturn {
    handle_no_args("replace", args)?;
    let state = cls.state();
    let mut components = slf.to_plain().components();
    let offset = slf.offset;
    let tz = &slf.tz;
    let mut dis_arg = DisambiguationArg::default();
    let mut tz_new = None;
    let mut tz_changed = false;

    handle_kwargs("replace", kwargs, |k, v, eq| {
        if eq(k, *state.str_tz) {
            let tz_arg = state.load_tz(v)?;
            // If we change timezones, forget about trying to preserve the offset.
            // Just use compatible disambiguation.
            if !Arc::ptr_eq(tz, &tz_arg) && **tz != *tz_arg {
                tz_changed = true;
            }
            tz_new = Some(tz_arg);
        } else if !dis_arg.handle_kwarg(k, v, eq, state) {
            return components.set_from_kwarg(k, v, state, eq);
        }
        Ok(true)
    })?;

    let tz = tz_new.unwrap_or_else(|| tz.clone());
    let dis = dis_arg
        .finish("replace", state)?
        .or(tz_changed.then_some(Disambiguation::Compatible));
    components
        .into_plain()?
        .resolve_or_raise(
            &tz,
            dis.map_or(
                ResolvePolicy::PreserveOffset(offset),
                ResolvePolicy::Disambiguate,
            ),
            state,
        )?
        .into_zoned_obj_unchecked(tz, cls)
}

fn now(cls: PyClass<ZonedDateTime>, tz_obj: PyObj) -> PyReturn {
    let state = cls.state();
    state.now()?.into_zoned_obj(state.load_tz(tz_obj)?, cls)
}

fn now_in_system_tz(cls: PyClass<ZonedDateTime>) -> PyReturn {
    let state = cls.state();
    warn_deprecated(
        state,
        c"now_in_system_tz() is deprecated; use now(SYSTEM_TZ) instead",
        1,
    )?;
    state
        .now()?
        .into_zoned_obj(state.tz_store.get_system_tz()?, cls)
}

fn from_system_tz(cls: PyClass<ZonedDateTime>, args: PyTuple, kwargs: Option<PyDict>) -> PyReturn {
    let state = cls.state();
    warn_deprecated(
        state,
        c"from_system_tz() is deprecated; use ZonedDateTime(..., tz=SYSTEM_TZ) instead",
        1,
    )?;
    let mut year: i64 = 0;
    let mut month: i64 = 0;
    let mut day: i64 = 0;
    let mut hour: i64 = 0;
    let mut minute: i64 = 0;
    let mut second: i64 = 0;
    let mut nanosecond: i64 = 0;
    let mut disambiguate: *mut PyObject = NULL();

    let fmt = if IS_LP64 {
        c"lll|lll$lO:ZonedDateTime"
    } else {
        c"LLL|LLL$LO:ZonedDateTime"
    };
    parse_args_kwargs!(
        args,
        kwargs,
        fmt,
        year,
        month,
        day,
        hour,
        minute,
        second,
        nanosecond,
        disambiguate
    );

    let tz = state.tz_store.get_system_tz()?;
    let dis = disambiguate
        .borrow_opt()
        .map_or(Ok(Disambiguation::Compatible), |o| {
            Disambiguation::from_py(o, state)
        })?;
    Date::from_i64_components(year, month, day)
        .ok_or_value_err("invalid date")?
        .at(Time::from_i64_components(hour, minute, second, nanosecond)
            .ok_or_value_err("invalid time")?)
        .resolve_or_raise(&tz, ResolvePolicy::Disambiguate(dis), state)?
        .into_zoned_obj_unchecked(tz, cls)
}

fn from_stdlib_datetime_inner(cls: PyClass<ZonedDateTime>, dt: PyDateTime) -> PyReturn {
    let state = cls.state();
    let tzinfo = dt.tzinfo();
    // NOTE: it has to be exactly a `ZoneInfo`, since
    // we *know* that this corresponds to a TZ database entry.
    // Other types could be making up their own rules.
    if tzinfo.type_().as_ptr() != state.zoneinfo_type.get()?.as_ptr() {
        raise_value_err(format!(
            "tzinfo must be of type ZoneInfo (exactly), got {tzinfo}"
        ))?;
    }
    let key = tzinfo.getattr(c"key")?;
    if key.is_none() {
        raise_value_err(doc::ZONEINFO_NO_KEY_MSG)?;
    };

    let tz = state.tz_store.obj_get(*key)?;
    // We use the timestamp() to convert into a ZonedDateTime
    // Alternatives not chosen:
    // - resolve offset from date/time -> fold not respected, instant may be different
    // - reuse the offset -> invalid results for gaps
    // - reuse the fold -> our calculated offset might be different, theoretically
    // Thus, the most "safe" way is to use the timestamp. This 100% guarantees
    // we preserve the same moment in time.
    let epoch_float = dt
        .getattr(c"timestamp")?
        .call0()?
        .cast_exact::<PyFloat>()
        .ok_or_raise(
            exc_runtime_error(),
            "datetime.datetime.timestamp() returned non-float",
        )?
        .to_f64()?;
    Instant {
        epoch: EpochSecs::new(epoch_float.floor() as _).ok_or_range_err()?,
        // NOTE: we don't get the subsecond part from the timestamp,
        // since floating point precision might lead to inaccuracies.
        // Instead, we take it from the original datetime.
        // This is safe because IANA timezones always deal in whole seconds,
        // meaning the subsecond part is timezone-independent.
        subsec: SubSecNanos::new_unchecked(dt.microsecond() * 1_000),
    }
    .into_zoned_obj(tz, cls)
}

fn to_plain(cls: PyClass<ZonedDateTime>, slf: &ZonedDateTime) -> PyReturn {
    slf.to_plain().to_obj(*cls.state().plain_datetime_type)
}

fn timestamp(
    cls: PyClass<ZonedDateTime>,
    slf: &ZonedDateTime,
    args: &[PyObj],
    kwargs: &mut IterKwargs,
) -> PyReturn {
    handle_no_args("timestamp", args)?;
    let unit = handle_one_kwarg("timestamp", *cls.state().str_unit, kwargs)?
        .map(|v| TimestampUnit::from_py(v, cls.state()))
        .transpose()?
        .unwrap_or(TimestampUnit::Second);
    unit.timestamp(slf.to_instant()).to_py()
}

fn timestamp_millis(cls: PyClass<ZonedDateTime>, slf: &ZonedDateTime) -> PyReturn {
    warn_deprecated(
        cls.state(),
        c"timestamp_millis() is deprecated; use timestamp(unit='millisecond') instead",
        1,
    )?;
    slf.to_instant().timestamp_millis().to_py()
}

fn timestamp_nanos(cls: PyClass<ZonedDateTime>, slf: &ZonedDateTime) -> PyReturn {
    warn_deprecated(
        cls.state(),
        c"timestamp_nanos() is deprecated; use timestamp(unit='nanosecond') instead",
        1,
    )?;
    slf.to_instant().timestamp_nanos().to_py()
}

fn __reduce__(cls: PyClass<ZonedDateTime>, slf: &ZonedDateTime) -> PyReturn {
    let tz = &slf.tz;
    if tz.key.is_none() {
        return raise_value_err("cannot pickle ZonedDateTime with unknown timezone ID");
    }
    let data = pickle::encode_offset(slf.to_fixed_offset());
    let tz_key = tz
        .key
        .as_ref()
        .ok_or_value_err("cannot pickle ZonedDateTime without timezone ID")?;
    [
        cls.state().unpickle_zoned_datetime.newref(),
        [data.to_py()?, tz_key.as_str().to_py()?].into_pytuple()?,
    ]
    .into_pytuple()
}

/// checks the args comply with (ts, /, *, tz: str)
fn check_from_timestamp_args_return_tz(
    args: &[PyObj],
    kwargs: &mut IterKwargs,
    state: &State,
    fname: &str,
) -> PyResult<Arc<TimeZone>> {
    match (args, kwargs.next()) {
        (&[_], Some((key, value))) if kwargs.original_len() == 1 => {
            if unicode_eq(key, *state.str_tz) {
                state.tz_store.obj_get(value)
            } else {
                raise_unexpected_kwarg(fname, key)
            }
        }
        (&[_], None) => raise_type_err(format!(
            "{fname}() missing 1 required keyword-only argument: 'tz'"
        )),
        (&[], _) => raise_type_err(format!("{fname}() missing 1 required positional argument")),
        _ => raise_type_err(format!(
            "{}() expected 2 arguments, got {}",
            fname,
            args.len() + (kwargs.original_len() as usize)
        )),
    }
}

fn from_timestamp(
    cls: PyClass<ZonedDateTime>,
    args: &[PyObj],
    kwargs: &mut IterKwargs,
) -> PyReturn {
    let state = cls.state();
    warn_deprecated(
        state,
        c"ZonedDateTime.from_timestamp() is deprecated; use Instant.from_timestamp(...).to_tz(...) instead",
        1,
    )?;
    let tz = check_from_timestamp_args_return_tz(args, kwargs, state, "from_timestamp")?;

    parse_timestamp(args[0])?.into_zoned_obj(tz, cls)
}

fn from_timestamp_millis(
    cls: PyClass<ZonedDateTime>,
    args: &[PyObj],
    kwargs: &mut IterKwargs,
) -> PyReturn {
    let state = cls.state();
    warn_deprecated(
        state,
        c"ZonedDateTime.from_timestamp_millis() is deprecated; use Instant.from_timestamp(..., unit='millisecond').to_tz(...) instead",
        1,
    )?;
    let tz = check_from_timestamp_args_return_tz(args, kwargs, state, "from_timestamp_millis")?;
    parse_timestamp_millis(args[0])?.into_zoned_obj(tz, cls)
}

fn from_timestamp_nanos(
    cls: PyClass<ZonedDateTime>,
    args: &[PyObj],
    kwargs: &mut IterKwargs,
) -> PyReturn {
    let state = cls.state();
    warn_deprecated(
        state,
        c"ZonedDateTime.from_timestamp_nanos() is deprecated; use Instant.from_timestamp(..., unit='nanosecond').to_tz(...) instead",
        1,
    )?;
    let tz = check_from_timestamp_args_return_tz(args, kwargs, state, "from_timestamp_nanos")?;
    parse_timestamp_nanos(args[0])?.into_zoned_obj(tz, cls)
}

fn is_ambiguous(_: PyType, slf: &ZonedDateTime) -> PyReturn {
    matches!(
        slf.tz.mapping_for_local(slf.to_plain().local_seconds()),
        LocalMapping::Fold { .. }
    )
    .to_py()
}

fn next_transition(cls: PyClass<ZonedDateTime>, slf: &ZonedDateTime) -> PyReturn {
    match slf.tz.next_transition(slf.to_instant().epoch) {
        Some((epoch, offset)) => epoch
            .shift_by_offset(offset)
            .ok_or_range_err()?
            .datetime(SubSecNanos::MIN)
            .assume_offset_unchecked(offset)
            .into_zoned_obj_unchecked(slf.tz.clone(), cls),
        None => Ok(none()),
    }
}

fn prev_transition(cls: PyClass<ZonedDateTime>, slf: &ZonedDateTime) -> PyReturn {
    match slf.tz.prev_transition(slf.to_instant().epoch) {
        Some((epoch, offset)) => epoch
            .shift_by_offset(offset)
            .ok_or_range_err()?
            .datetime(SubSecNanos::MIN)
            .assume_offset_unchecked(offset)
            .into_zoned_obj_unchecked(slf.tz.clone(), cls),
        None => Ok(none()),
    }
}

fn dst_offset(cls: PyClass<ZonedDateTime>, slf: &ZonedDateTime) -> PyReturn {
    let state = cls.state();
    let meta = slf.tz.meta_for_instant(slf.to_instant().epoch);
    TimeDelta::from_nanos_unchecked(meta.dst_saving as i128 * 1_000_000_000)
        .to_obj(*state.time_delta_type)
}

fn tz_abbrev(_: PyType, slf: &ZonedDateTime) -> PyReturn {
    let meta = slf.tz.meta_for_instant(slf.to_instant().epoch);
    // SAFETY: TzAbbrev always contains valid ASCII bytes
    unsafe { std::str::from_utf8_unchecked(meta.abbrev.as_bytes()) }.to_py()
}

fn add(
    cls: PyClass<ZonedDateTime>,
    slf: &ZonedDateTime,
    args: &[PyObj],
    kwargs: &mut IterKwargs,
) -> PyReturn {
    shift_method(cls, slf, args, kwargs, false)
}

fn subtract(
    cls: PyClass<ZonedDateTime>,
    slf: &ZonedDateTime,
    args: &[PyObj],
    kwargs: &mut IterKwargs,
) -> PyReturn {
    shift_method(cls, slf, args, kwargs, true)
}

fn shift_method(
    cls: PyClass<ZonedDateTime>,
    slf: &ZonedDateTime,
    args: &[PyObj],
    kwargs: &mut IterKwargs,
    negate: bool,
) -> PyReturn {
    let fname = if negate { "subtract" } else { "add" };
    let state = cls.state();
    let mut dis_arg = DisambiguationArg::default();

    let shift = match handle_opt_arg(fname, args)? {
        Some(arg) => {
            handle_kwargs(fname, kwargs, |k, v, eq| {
                Ok(dis_arg.handle_kwarg(k, v, eq, state))
            })?;
            parse_datetime_shift_arg(fname, arg, state)?
        }
        None => parse_datetime_shift_kwargs(fname, kwargs, state, |k, v, eq| {
            Ok(dis_arg.handle_kwarg(k, v, eq, state))
        })?,
    };

    let dis = dis_arg.finish(fname, state)?;

    slf.shift(shift.negate_if(negate), dis, state, cls)
}

fn difference(cls: PyClass<ZonedDateTime>, slf: &ZonedDateTime, arg: PyObj) -> PyReturn {
    let state = cls.state();
    slf.to_instant()
        .diff(parse_instant_arg("difference", arg, state)?)
        .to_obj(*state.time_delta_type)
}

fn day_length(cls: PyClass<ZonedDateTime>, slf: &ZonedDateTime) -> PyReturn {
    let ZonedDateTime { date, ref tz, .. } = *slf;
    let day_start = date
        .at(Time::MIN)
        .resolve_compatible(tz)
        .ok_or_range_err()?
        .to_instant();
    let start_of_next_day = date
        .tomorrow()
        .ok_or_range_err()?
        .at(Time::MIN)
        .resolve_compatible(tz)
        .ok_or_range_err()?
        .to_instant();
    start_of_next_day
        .diff(day_start)
        .to_obj(*cls.state().time_delta_type)
}

fn round(
    cls: PyClass<ZonedDateTime>,
    slf: &ZonedDateTime,
    args: &[PyObj],
    kwargs: &mut IterKwargs,
) -> PyReturn {
    let round::Args {
        increment, mode, ..
    } = round::Args::parse(args, kwargs, cls.state(), round::ArgsContext::Standard)?;

    match increment {
        round::RoundIncrement::Day => slf.round_day(mode),
        round::RoundIncrement::Exact(ns) => {
            let ZonedDateTime {
                mut date,
                time,
                offset,
                ref tz,
            } = *slf;
            let (time_rounded, next_day) = time.round(ns.get(), mode);
            if next_day == 1 {
                date = date.tomorrow().ok_or_range_err()?;
            };
            date.at(time_rounded).resolve_preserving_offset(tz, offset)
        }
    }
    .ok_or_range_err()?
    .into_zoned_obj_unchecked(slf.tz.clone(), cls)
}

fn tz_err_display(k: &Option<String>) -> String {
    match k {
        Some(key) => format!("timezone '{key}'"),
        None => "the system timezone (with unknown ID)".to_string(),
    }
}

fn since(
    cls: PyClass<ZonedDateTime>,
    slf: &ZonedDateTime,
    args: &[PyObj],
    kwargs: &mut IterKwargs,
) -> PyReturn {
    zoned_since(cls, slf, args, kwargs, false)
}

fn until(
    cls: PyClass<ZonedDateTime>,
    slf: &ZonedDateTime,
    args: &[PyObj],
    kwargs: &mut IterKwargs,
) -> PyReturn {
    zoned_since(cls, slf, args, kwargs, true)
}

fn zoned_since_float(
    a: OffsetDateTime,
    b: &ZonedDateTime,
    target_date: Date,
    unit: difference::TotalUnit,
    neg: bool,
) -> PyReturn {
    match unit.to_exact() {
        Ok(u) => {
            // For nanoseconds (in_nanos == 1), return int to preserve full precision.
            let nanos = a.to_instant().diff(b.to_instant()).total_nanos();
            let unit_nanos = u.in_nanos();
            if unit_nanos == 1 {
                nanos.to_py()
            } else {
                (nanos as f64 / unit_nanos as f64).to_py()
            }
        }
        Err(calendar_unit) => {
            let (result, trunc_raw, expand_raw) = difference::date_diff_single_unit(
                target_date,
                b.date,
                CalendarIncrement::MIN,
                calendar_unit,
                neg,
            )
            .ok_or_range_err()?;
            let trunc = b
                .with_date(trunc_raw.into())
                .ok_or_range_err()?
                .to_instant();
            let expand = b
                .with_date(expand_raw.into())
                .ok_or_range_err()?
                .to_instant();
            // result is signed; take absolute value and restore sign at the end.
            // num/denom ratio is always positive (same sign).
            let num = a.to_instant().diff(trunc).total_nanos() as f64;
            let denom = expand.diff(trunc).total_nanos() as f64;
            let sign: f64 = if neg { -1.0 } else { 1.0 };
            ((result.abs() as f64 + num / denom) * sign).to_py()
        }
    }
}

fn zoned_since(
    cls: PyClass<ZonedDateTime>,
    slf: &ZonedDateTime,
    args: &[PyObj],
    kwargs: &mut IterKwargs,
    flip: bool,
) -> PyReturn {
    let fname = if flip { "until" } else { "since" };
    let state = cls.state();

    let other_obj = handle_one_arg(fname, args)?;
    let other = other_obj
        .extract_ref(cls)
        .ok_or_type_err("argument must be a whenever.ZonedDateTime")?;
    let kwargs = DifferenceSpec::parse(fname, kwargs, state)?;

    if kwargs.has_calendar() && !slf.same_tz(other) {
        raise_value_err(
            "Calendar units can only be used to compare ZonedDateTimes \
             with the same timezone",
        )?;
    }
    let (a, b) = if flip { (other, slf) } else { (slf, other) };
    let a_inst = a.to_instant();
    let neg = a_inst < b.to_instant();

    let target_date = zoned_target(a.date, a_inst, b, neg).ok_or_range_err()?;

    match kwargs {
        DifferenceSpec::Total(unit) => {
            zoned_since_float(a.to_fixed_offset(), b, target_date, unit, neg)
        }
        DifferenceSpec::InUnits {
            units,
            mode,
            increment,
        } => {
            let result = zoned_since_in_units(
                a.to_fixed_offset(),
                a_inst,
                b,
                target_date,
                units,
                mode,
                increment,
                neg,
            )
            .ok_or_range_err()?;
            result.to_obj(state)
        }
    }
}

fn format(cls: PyClass<ZonedDateTime>, slf: &ZonedDateTime, pattern_obj: PyObj) -> PyReturn {
    let pattern_pystr = pattern_obj
        .cast_exact::<PyStr>()
        .ok_or_type_err("format() argument must be str")?;
    let pattern_str = pattern_pystr.as_utf8()?;
    let pattern = pattern::CompiledPattern::compile(pattern_str).into_value_err()?;
    pattern.validate(
        pattern::CategorySet::DATE_TIME_OFFSET_TZ,
        "ZonedDateTime",
        *cls.state().warn_whenever,
        *cls.state().warn_deprecation,
    )?;
    let meta = slf.tz.meta_for_instant(slf.to_instant().epoch);
    // SAFETY: TzAbbrev always contains valid ASCII bytes
    let abbrev_str = unsafe { std::str::from_utf8_unchecked(meta.abbrev.as_bytes()) };
    let tz_key = slf.tz.key.as_deref().unwrap_or("");
    pattern.format(
        &slf.to_plain()
            .pattern_values()
            .with_offset(slf.offset)
            .with_timezone(tz_key, abbrev_str),
    )
}

fn __format__(cls: PyClass<ZonedDateTime>, slf: &ZonedDateTime, spec_obj: PyObj) -> PyReturn {
    if spec_obj.is_truthy()? {
        format(cls, slf, spec_obj)
    } else {
        __str__(cls.into(), slf)
    }
}

fn parse(cls: PyClass<ZonedDateTime>, args: &[PyObj], kwargs: &mut IterKwargs) -> PyReturn {
    let s_obj = handle_one_arg("parse", args)?;
    let s_pystr = s_obj
        .cast_exact::<PyStr>()
        .ok_or_type_err("parse() argument must be str")?;
    let s = s_pystr.as_utf8()?;

    let state = cls.state();
    let mut pattern_arg = RenamedKeyword::default();
    let mut dis = None;
    let mut mismatch = OffsetMismatch::Raise;
    handle_kwargs("parse", kwargs, |k, v, eq| {
        if eq(k, *state.str_pattern) {
            pattern_arg.set_new(v);
        } else if eq(k, *state.str_format) {
            pattern_arg.set_old(v);
        } else if eq(k, *state.str_disambiguation) {
            dis = Some(Disambiguation::from_py(v, state)?);
        } else if eq(k, *state.str_offset_mismatch) {
            mismatch = OffsetMismatch::from_py(v, state)?;
        } else {
            return Ok(false);
        }
        Ok(true)
    })?;

    let fmt_obj = pattern_arg
        .finish(
            state,
            "parse",
            "pattern",
            "format",
            c"'format' is deprecated; use 'pattern' instead",
            1,
        )?
        .ok_or_type_err("parse() missing required keyword argument 'pattern'")?;
    let fmt_pystr = fmt_obj
        .cast_exact::<PyStr>()
        .ok_or_type_err("pattern must be str")?;
    let fmt_bytes = fmt_pystr.as_utf8()?;

    let pattern = pattern::CompiledPattern::compile(fmt_bytes).into_value_err()?;
    pattern.validate(
        pattern::CategorySet::DATE_TIME_OFFSET_TZ,
        "ZonedDateTime",
        *cls.state().warn_whenever,
        *cls.state().warn_deprecation,
    )?;
    let parsed = pattern.parse(s).into_value_err()?;

    let tz_id = parsed
        .tz_id
        .as_deref()
        .ok_or_value_err("ZonedDateTime.parse() pattern must include a timezone ID field (VV)")?;

    let date = parsed.date("Pattern must include year, month, and day fields")?;
    parsed.validate_weekday(date)?;
    let dt = date.at(parsed.time()?);
    let tz = state.tz_store.get(tz_id)?;
    if let Some(offset) = parsed.offset_secs {
        if parsed.offset_is_z {
            dt.assume_utc().into_zoned_obj(tz, cls)
        } else if let Some(actual) = matching_local_offset(
            tz.mapping_for_local(dt.local_seconds()),
            offset,
            parsed.offset_exact,
        ) {
            dt.assume_offset(actual)
                .ok_or_range_err()?
                .into_zoned_obj_unchecked(tz, cls)
        } else {
            match mismatch {
                OffsetMismatch::Raise => raise_value_err(format!(
                    "Offset {}s does not match timezone {tz_id:?}",
                    offset.get()
                )),
                OffsetMismatch::KeepInstant => dt
                    .assume_offset(offset)
                    .ok_or_range_err()?
                    .to_instant()
                    .into_zoned_obj(tz, cls),
                OffsetMismatch::KeepLocal => dt
                    .resolve_with_disambiguation(&tz, dis, state)?
                    .into_zoned_obj_unchecked(tz, cls),
            }
        }
    } else {
        dt.resolve_with_disambiguation(&tz, dis, state)?
            .into_zoned_obj_unchecked(tz, cls)
    }
}

static mut METHODS: &[PyMethodDef] = &[
    COPY_METHOD,
    DEEPCOPY_METHOD,
    method0!(ZonedDateTime, __reduce__, c""),
    method1!(ZonedDateTime, to_tz, doc::EXACTTIME_TO_TZ),
    method0!(ZonedDateTime, to_system_tz, doc::EXACTTIME_TO_SYSTEM_TZ),
    method_vararg!(
        ZonedDateTime,
        to_fixed_offset,
        doc::EXACTTIME_TO_FIXED_OFFSET
    ),
    method1!(ZonedDateTime, exact_eq, doc::EXACTTIME_STRICT_EQ),
    method1!(ZonedDateTime, strict_eq, doc::EXACTTIME_STRICT_EQ),
    method0!(ZonedDateTime, to_stdlib, doc::BASICCONVERSIONS_TO_STDLIB),
    method0!(ZonedDateTime, to_instant, doc::EXACTANDLOCALTIME_TO_INSTANT),
    method0!(ZonedDateTime, to_plain, doc::EXACTANDLOCALTIME_TO_PLAIN),
    method0!(ZonedDateTime, date, doc::LOCALTIME_DATE),
    method0!(ZonedDateTime, time, doc::LOCALTIME_TIME),
    method0!(ZonedDateTime, day_of_year, doc::LOCALTIME_DAY_OF_YEAR),
    method0!(ZonedDateTime, days_in_month, doc::LOCALTIME_DAYS_IN_MONTH),
    method0!(ZonedDateTime, days_in_year, doc::LOCALTIME_DAYS_IN_YEAR),
    method0!(ZonedDateTime, in_leap_year, doc::LOCALTIME_IN_LEAP_YEAR),
    method1!(ZonedDateTime, start_of, doc::ZONEDDATETIME_START_OF),
    method1!(ZonedDateTime, end_of, doc::ZONEDDATETIME_END_OF),
    method_kwargs!(ZonedDateTime, format_iso, doc::ZONEDDATETIME_FORMAT_ISO),
    classmethod_kwargs!(ZonedDateTime, parse_iso, doc::ZONEDDATETIME_PARSE_ISO),
    classmethod1!(ZonedDateTime, now, doc::ZONEDDATETIME_NOW),
    classmethod0!(
        ZonedDateTime,
        now_in_system_tz,
        doc::ZONEDDATETIME_NOW_IN_SYSTEM_TZ
    ),
    // This method is defined different because it
    // makes use of the arg/kwargs processing macro.
    // Other types only use it for the __new__ method.
    PyMethodDef {
        ml_name: c"from_system_tz".as_ptr(),
        ml_meth: PyMethodDefPointer {
            PyCFunctionWithKeywords: {
                unsafe extern "C" fn _wrap(
                    cls: *mut PyObject,
                    args: *mut PyObject,
                    kwargs: *mut PyObject,
                ) -> *mut PyObject {
                    from_system_tz(
                        unsafe { PyClass::from_ptr_unchecked(cls.cast()) },
                        unsafe { PyTuple::from_ptr_unchecked(args) },
                        (!kwargs.is_null()).then(|| unsafe { PyDict::from_ptr_unchecked(kwargs) }),
                    )
                    .to_py_owned_ptr()
                }
                _wrap
            },
        },
        ml_flags: METH_CLASS | METH_VARARGS | METH_KEYWORDS,
        ml_doc: doc::ZONEDDATETIME_FROM_SYSTEM_TZ.as_ptr(),
    },
    method_kwargs!(ZonedDateTime, timestamp, doc::EXACTTIME_TIMESTAMP),
    method0!(
        ZonedDateTime,
        timestamp_millis,
        doc::EXACTTIME_TIMESTAMP_MILLIS
    ),
    method0!(
        ZonedDateTime,
        timestamp_nanos,
        doc::EXACTTIME_TIMESTAMP_NANOS
    ),
    method0!(ZonedDateTime, is_ambiguous, doc::ZONEDDATETIME_IS_AMBIGUOUS),
    method0!(
        ZonedDateTime,
        next_transition,
        doc::ZONEDDATETIME_NEXT_TRANSITION
    ),
    method0!(
        ZonedDateTime,
        prev_transition,
        doc::ZONEDDATETIME_PREV_TRANSITION
    ),
    method0!(ZonedDateTime, dst_offset, doc::ZONEDDATETIME_DST_OFFSET),
    method0!(ZonedDateTime, tz_abbrev, doc::ZONEDDATETIME_TZ_ABBREV),
    classmethod_kwargs!(
        ZonedDateTime,
        from_timestamp,
        doc::ZONEDDATETIME_FROM_TIMESTAMP
    ),
    classmethod_kwargs!(
        ZonedDateTime,
        from_timestamp_millis,
        doc::ZONEDDATETIME_FROM_TIMESTAMP_MILLIS
    ),
    classmethod_kwargs!(
        ZonedDateTime,
        from_timestamp_nanos,
        doc::ZONEDDATETIME_FROM_TIMESTAMP_NANOS
    ),
    method_kwargs!(ZonedDateTime, replace, doc::ZONEDDATETIME_REPLACE),
    method_kwargs!(ZonedDateTime, replace_date, doc::ZONEDDATETIME_REPLACE_DATE),
    method_kwargs!(ZonedDateTime, replace_time, doc::ZONEDDATETIME_REPLACE_TIME),
    method_kwargs!(ZonedDateTime, add, doc::ZONEDDATETIME_ADD),
    method_kwargs!(ZonedDateTime, subtract, doc::ZONEDDATETIME_SUBTRACT),
    method1!(ZonedDateTime, difference, doc::EXACTTIME_DIFFERENCE),
    method0!(ZonedDateTime, day_length, doc::ZONEDDATETIME_DAY_LENGTH),
    method_kwargs!(ZonedDateTime, round, doc::ZONEDDATETIME_ROUND),
    method_kwargs!(ZonedDateTime, since, doc::ZONEDDATETIME_SINCE),
    method_kwargs!(ZonedDateTime, until, doc::ZONEDDATETIME_UNTIL),
    method1!(ZonedDateTime, format, doc::ZONEDDATETIME_FORMAT),
    method1!(ZonedDateTime, __format__, c""),
    classmethod_kwargs!(ZonedDateTime, parse, doc::ZONEDDATETIME_PARSE),
    classmethod_kwargs!(
        ZonedDateTime,
        __get_pydantic_core_schema__,
        doc::PYDANTIC_SCHEMA
    ),
    PyMethodDef::zeroed(),
];

fn year(_: PyType, slf: &ZonedDateTime) -> PyReturn {
    slf.date.year.get().to_py()
}

fn month(_: PyType, slf: &ZonedDateTime) -> PyReturn {
    slf.date.month.get().to_py()
}

fn day(_: PyType, slf: &ZonedDateTime) -> PyReturn {
    slf.date.day.to_py()
}

fn hour(_: PyType, slf: &ZonedDateTime) -> PyReturn {
    slf.time.hour.to_py()
}

fn minute(_: PyType, slf: &ZonedDateTime) -> PyReturn {
    slf.time.minute.to_py()
}

fn second(_: PyType, slf: &ZonedDateTime) -> PyReturn {
    slf.time.second.to_py()
}

fn nanosecond(_: PyType, slf: &ZonedDateTime) -> PyReturn {
    slf.time.subsec.get().to_py()
}

fn tz_id(_: PyType, slf: &ZonedDateTime) -> PyReturn {
    match slf.tz.key.as_ref() {
        Some(key) => key.as_str().to_py(),
        None => Ok(none()),
    }
}

fn tz(cls: PyClass<ZonedDateTime>, slf: &ZonedDateTime) -> PyReturn {
    warn_deprecated(cls.state(), c"tz is deprecated; use tz_id instead", 1)?;
    tz_id(cls.into(), slf)
}

fn offset(cls: PyClass<ZonedDateTime>, slf: &ZonedDateTime) -> PyReturn {
    slf.offset.to_delta().to_obj(*cls.state().time_delta_type)
}

static mut GETSETTERS: &[PyGetSetDef] = &[
    getter!(ZonedDateTime, year, doc::LOCALTIME_YEAR),
    getter!(ZonedDateTime, month, doc::LOCALTIME_MONTH),
    getter!(ZonedDateTime, day, doc::LOCALTIME_DAY),
    getter!(ZonedDateTime, hour, doc::LOCALTIME_HOUR),
    getter!(ZonedDateTime, minute, doc::LOCALTIME_MINUTE),
    getter!(ZonedDateTime, second, doc::LOCALTIME_SECOND),
    getter!(ZonedDateTime, nanosecond, doc::LOCALTIME_NANOSECOND),
    getter!(ZonedDateTime, tz, doc::ZONEDDATETIME_TZ),
    getter!(ZonedDateTime, tz_id, doc::ZONEDDATETIME_TZ),
    getter!(ZonedDateTime, offset, doc::EXACTANDLOCALTIME_OFFSET),
    PyGetSetDef {
        name: NULL(),
        get: None,
        set: None,
        doc: NULL(),
        closure: NULL(),
    },
];

pub(crate) static mut SPEC: PyType_Spec =
    type_spec::<ZonedDateTime>(c"whenever.ZonedDateTime", unsafe { SLOTS });
