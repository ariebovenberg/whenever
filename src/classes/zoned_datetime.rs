use crate::{
    classes::{
        date::Date,
        instant::Instant,
        itemized_date_delta::ItemizedDateDelta,
        itemized_delta::{ItemizedDelta, handle_delta_unit_kwargs},
        offset_datetime::OffsetDateTime,
        plain_datetime::{BoundaryUnit, DateTime, set_components_from_kwargs},
        time::Time,
        time_delta::TimeDelta,
    },
    common::{
        ambiguity::*,
        fmt::{self, Sink, Suffix},
        math::{self, DateRoundIncrement, DeltaUnitSet, SinceUntilKwargs},
        parse::Scan,
        pattern, round,
        scalar::*,
    },
    docstrings as doc,
    py::*,
    pymodule::State,
    tz::tzif::TimeZone,
};
use core::{
    ffi::{c_int, c_long, c_void},
    ptr::null_mut as NULL,
};
use pyo3_ffi::*;
use std::sync::Arc;

#[derive(Debug, Clone)]
pub(crate) struct ZonedDateTime {
    pub(crate) date: Date,
    time: Time,
    offset: Offset,
    pub(crate) tz: Arc<TimeZone>,
}

// Custom implementation to optimize timezone equality checks
impl std::cmp::PartialEq for ZonedDateTime {
    fn eq(&self, other: &Self) -> bool {
        self.date == other.date
            && self.time == other.time
            && self.offset == other.offset
            && self.same_tz(other)
    }
}

impl ZonedDateTime {
    /// Whether two ZonedDateTimes share the same timezone (pointer or value equality).
    fn same_tz(&self, other: &Self) -> bool {
        Arc::ptr_eq(&self.tz, &other.tz) || *self.tz == *other.tz
    }

    pub(crate) fn instant(&self) -> Instant {
        self.date
            .at(self.time)
            .assume_utc()
            .offset(-self.offset)
            // SAFETY: we know the instant of a ZonedDateTime is always valid
            .unwrap()
    }

    fn local(&self) -> DateTime {
        DateTime {
            date: self.date,
            time: self.time,
        }
    }

    pub(crate) fn fixed_offset(&self) -> OffsetDateTime {
        OffsetDateTime {
            date: self.date,
            time: self.time,
            offset: self.offset,
        }
    }

    pub(crate) fn with_date(&self, new_date: Date) -> Option<OffsetDateTime> {
        self.fixed_offset().with_date_in_tz(new_date, &self.tz)
    }

    pub(crate) fn shift_default(&self, delta: ItemizedDelta) -> Option<OffsetDateTime> {
        let (months, days, tdelta) = delta.to_components()?;
        self.fixed_offset()
            .shift_in_tz(months, days, tdelta, &self.tz)
    }

    pub(crate) fn shift(
        &self,
        months: DeltaMonths,
        days: DeltaDays,
        delta: TimeDelta,
        dis: Option<Disambiguate>,
        state: &State,
        cls: HeapType<Self>,
    ) -> PyReturn {
        let shifted_by_date = if !months.is_zero() || !days.is_zero() {
            self.date
                .shift(months, days)
                .ok_or_range_err()?
                .at(self.time)
                .localize_custom(&self.tz, dis, self.offset, state)?
        } else {
            self.fixed_offset()
        };

        shifted_by_date
            .instant()
            .shift(delta)
            .ok_or_range_err()?
            .to_tz_py(self.tz.clone(), cls)
    }
}

impl DateTime {
    /// Simple/fast path to resolve with the 'compatible' disambiguation strategy.
    pub(crate) fn localize_default(self, tz: &TimeZone) -> Option<OffsetDateTime> {
        match tz.ambiguity_for_local(self.assume_utc().epoch) {
            Ambiguity::Unambiguous(offset) | Ambiguity::Fold(_, offset, _) => {
                self.with_offset(offset)
            }
            Ambiguity::Gap(_, later_offset, earlier_offset) => {
                let shift = later_offset.sub(earlier_offset);
                self.shift_by_offset(shift)?.with_offset(later_offset)
            }
        }
    }

    /// Like `with_tz_offset`, but with a preferred offset to try to reuse if possible.
    pub(crate) fn localize_using_offset(
        self,
        tz: &TimeZone,
        target: Offset,
    ) -> Option<OffsetDateTime> {
        match tz.ambiguity_for_local(self.assume_utc().epoch) {
            Ambiguity::Unambiguous(offset) => self.with_offset(offset),
            Ambiguity::Fold(_, earlier_offset, later_offset) => {
                self.with_offset(if target == later_offset {
                    later_offset
                } else {
                    earlier_offset
                })
            }
            // For gaps, don't try to reuse the previous offset since the
            // time doesn't exist. Use "compatible" (later) behavior.
            Ambiguity::Gap(_, later_offset, earlier_offset) => {
                let shift = later_offset.sub(earlier_offset);
                self.shift_by_offset(shift)?.with_offset(later_offset)
            }
        }
    }

    pub(crate) fn localize_using_disambiguate(
        self,
        tz: &TimeZone,
        dis: Disambiguate,
        state: &State,
    ) -> PyResult<OffsetDateTime> {
        match tz.ambiguity_for_local(self.assume_utc().epoch) {
            Ambiguity::Unambiguous(offset) => self.with_offset(offset),
            Ambiguity::Fold(_, earlier_offset, later_offset) => self.with_offset(match dis {
                Disambiguate::Earlier => earlier_offset,
                Disambiguate::Later => later_offset,
                Disambiguate::Compatible => earlier_offset,
                Disambiguate::Raise => raise(
                    *state.exc_repeated,
                    format!(
                        "{} {} is repeated in {}",
                        self.date,
                        self.time,
                        tz_err_display(&tz.key)
                    ),
                )?,
            }),
            Ambiguity::Gap(_, later_offset, earlier_offset) => {
                let shift = later_offset.sub(earlier_offset);
                let (shift, offset) = match dis {
                    Disambiguate::Earlier => (-shift, earlier_offset),
                    Disambiguate::Later => (shift, later_offset),
                    Disambiguate::Compatible => (shift, later_offset),
                    Disambiguate::Raise => raise(
                        *state.exc_skipped,
                        format!(
                            "{} {} is skipped in {}",
                            self.date,
                            self.time,
                            tz_err_display(&tz.key)
                        ),
                    )?,
                };
                self.shift_by_offset(shift)
                    // shifting out of the gap can result in an out-of-range date
                    .ok_or_range_err()?
                    .with_offset(offset)
            }
        }
        // or the shifted datetime represents an invalid instant
        .ok_or_range_err()
    }

    fn localize_custom(
        self,
        tz: &TimeZone,
        dis: Option<Disambiguate>,
        preferred_offset: Offset,
        state: &State,
    ) -> PyResult<OffsetDateTime> {
        match dis {
            Some(d) => self.localize_using_disambiguate(tz, d, state),
            None => self
                .localize_using_offset(tz, preferred_offset)
                .ok_or_range_err(),
        }
    }
}

impl OffsetDateTime {
    fn with_date_in_tz(self, new_date: Date, tz: &TimeZone) -> Option<OffsetDateTime> {
        match tz.ambiguity_for_local(new_date.epoch_at(self.time)) {
            Ambiguity::Unambiguous(offset) => OffsetDateTime::new(new_date, self.time, offset),
            Ambiguity::Fold(_, earlier_offset, later_offset) => {
                // Compatible: pick the offset matching the original
                let offset = if self.offset == later_offset {
                    later_offset
                } else {
                    earlier_offset
                };
                OffsetDateTime::new(new_date, self.time, offset)
            }
            Ambiguity::Gap(_, later_offset, earlier_offset) => {
                // Compatible: shift to later
                let shift = later_offset.sub(earlier_offset);
                DateTime {
                    date: new_date,
                    time: self.time,
                }
                .shift_by_offset(shift)?
                .with_offset(later_offset)
            }
        }
    }

    pub(crate) fn shift_in_tz(
        self,
        months: DeltaMonths,
        days: DeltaDays,
        tdelta: TimeDelta,
        tz: &TimeZone,
    ) -> Option<OffsetDateTime> {
        let shifted_by_date = if !months.is_zero() || !days.is_zero() {
            self.with_date_in_tz(self.date.shift(months, days)?, tz)?
        } else {
            self
        };
        shifted_by_date
            .instant()
            .shift(tdelta)?
            .to_offset(shifted_by_date.offset)
    }
}

enum OffsetInIsoString {
    Some(Offset),
    Z,
    Missing,
}

fn read_offset_and_tzname<'a>(s: &'a mut Scan) -> Option<(OffsetInIsoString, &'a str)> {
    let offset = match s.peek() {
        Some(b'[') => OffsetInIsoString::Missing,
        Some(b'Z' | b'z') => {
            s.take_unchecked(1);
            OffsetInIsoString::Z
        }
        _ => OffsetInIsoString::Some(Offset::read_iso(s)?),
    };
    let tz = s.rest();
    (tz.len() > 2
        && tz[0] == b'['
        // This scanning check ensures there's no other closing bracket
        && tz.iter().position(|&b| b == b']') == Some(tz.len() - 1)
        && tz.is_ascii())
    .then(|| {
        (offset, unsafe {
            // Safe: we've just checked that it's ASCII-only
            std::str::from_utf8_unchecked(&tz[1..tz.len() - 1])
        })
    })
}

impl PyWrapped for ZonedDateTime {}

impl Instant {
    /// Convert an instant to a zoned datetime, ready to be returned to Python.
    pub(crate) fn to_tz_py(self, tz: Arc<TimeZone>, cls: HeapType<ZonedDateTime>) -> PyReturn {
        self.to_tz(&tz)
            .ok_or_range_err()?
            // SAFETY: We've already checked for both out-of-range date and time.
            .assume_tz_unchecked(tz, cls)
    }

    // Covert an instant to an OffsetDateTime in the given timezone.
    // Returns None if out of range
    pub(crate) fn to_tz(self, tz: &TimeZone) -> Option<OffsetDateTime> {
        let epoch = self.epoch;
        let offset = tz.offset_for_instant(epoch);
        Some(
            epoch
                .offset(offset)?
                .datetime(self.subsec)
                // SAFETY: We've already checked for both out-of-range date and time.
                .with_offset_unchecked(offset),
        )
    }
}

impl OffsetDateTime {
    pub(crate) fn assume_tz_unchecked(
        self,
        tz: Arc<TimeZone>,
        cls: HeapType<ZonedDateTime>,
    ) -> PyReturn {
        ZonedDateTime {
            date: self.date,
            time: self.time,
            offset: self.offset,
            tz,
        }
        .to_obj(cls)
    }
}

fn __new__(cls: HeapType<ZonedDateTime>, args: PyTuple, kwargs: Option<PyDict>) -> PyReturn {
    // Alternate constructor: one ISO 8601 string or stdlib datetime argument
    if args.len() == 1 && kwargs.map_or(0, |d| d.len()) == 0 {
        let arg = args.iter().next().unwrap();
        if PyStr::isinstance(arg) {
            return parse_iso(cls, arg);
        }
        if let Some(dt) = arg.cast_allow_subclass::<PyDateTime>() {
            return from_py_datetime_inner(cls, dt);
        }
        return raise_type_err("ZonedDateTime() requires an ISO 8601 string or datetime.datetime");
    };

    let state = cls.state();
    let mut year: c_long = 0;
    let mut month: c_long = 0;
    let mut day: c_long = 0;
    let mut hour: c_long = 0;
    let mut minute: c_long = 0;
    let mut second: c_long = 0;
    let mut nanosecond: c_long = 0;
    let mut tz: *mut PyObject = NULL();
    let mut disambiguate: *mut PyObject = NULL();

    parse_args_kwargs!(
        args,
        kwargs,
        c"lll|lll$lOO:ZonedDateTime",
        year,
        month,
        day,
        hour,
        minute,
        second,
        nanosecond,
        tz,
        disambiguate
    );

    let tz = state
        .tz_store
        .obj_get(tz.borrow_opt().ok_or_type_err("`tz` argment is required")?)?;
    let date = Date::from_longs(year, month, day).ok_or_value_err("invalid date")?;
    let time =
        Time::from_longs(hour, minute, second, nanosecond).ok_or_value_err("invalid time")?;
    let dis = disambiguate
        .borrow_opt()
        .map_or(Ok(Disambiguate::Compatible), |o| {
            Disambiguate::from_py(o, state)
        })?;
    DateTime { date, time }
        .localize_using_disambiguate(&tz, dis, state)?
        .assume_tz_unchecked(tz, cls)
}

extern "C" fn dealloc(arg: PyObj) {
    // SAFETY: in dealloc we have exclusive access. We must drop the Arc<TimeZone>
    // before freeing the memory, since generic_dealloc won't run Rust destructors.
    unsafe {
        let ptr = &raw mut (*(arg.as_ptr() as *mut PyWrap<ZonedDateTime>)).data;
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
        date.format_iso(false),
        b' ',
        time.format_iso(fmt::Unit::Auto, false),
        offset.format_iso(false),
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
        date.format_iso(false),
        b'T',
        time.format_iso(fmt::Unit::Auto, false),
        offset.format_iso(false),
        TzFormat { tz },
    ))
}

struct TzFormat<'a> {
    tz: &'a TimeZone,
}

impl fmt::Chunk for TzFormat<'_> {
    fn len(&self) -> usize {
        self.tz.key.as_ref().map_or(0, |k| k.len() + 2) // +2 for brackets around tz
    }

    fn write(&self, sink: &mut impl Sink) {
        if let Some(ref tz_key) = self.tz.key {
            sink.write_byte(b'[');
            sink.write(tz_key.as_bytes());
            sink.write_byte(b']');
        }
    }
}

fn __richcmp__(
    cls: HeapType<ZonedDateTime>,
    a: &ZonedDateTime,
    b_obj: PyObj,
    op: c_int,
) -> PyReturn {
    let inst_a = a.instant();
    let inst_b = if let Some(zdt) = b_obj.extract_ref(cls) {
        zdt.instant()
    } else {
        let state = cls.state();

        if let Some(inst) = b_obj.extract(*state.instant_type) {
            inst
        } else if let Some(odt) = b_obj.extract(*state.offset_datetime_type) {
            odt.instant()
        } else {
            return not_implemented();
        }
    };
    match op {
        pyo3_ffi::Py_EQ => inst_a == inst_b,
        pyo3_ffi::Py_NE => inst_a != inst_b,
        pyo3_ffi::Py_LT => inst_a < inst_b,
        pyo3_ffi::Py_LE => inst_a <= inst_b,
        pyo3_ffi::Py_GT => inst_a > inst_b,
        pyo3_ffi::Py_GE => inst_a >= inst_b,
        _ => unreachable!(),
    }
    .to_py()
}

extern "C" fn __hash__(arg: PyObj) -> Py_hash_t {
    // SAFETY: the first arg to this function is the self type
    let (_, slf) = unsafe { arg.assume_heaptype_ref::<ZonedDateTime>() };
    hashmask(slf.instant().pyhash())
}

fn __add__(a_obj: PyObj, b_obj: PyObj) -> PyReturn {
    if let Some(state) = a_obj.type_().same_module(b_obj.type_()) {
        // SAFETY: the way we've structured binary operations within whenever
        // ensures that the first operand is the self type.
        let (cls, slf) = unsafe { a_obj.assume_heaptype_ref::<ZonedDateTime>() };
        shift_operator(state, cls, slf, b_obj, false)
    } else {
        not_implemented()
    }
}

fn __sub__(a_obj: PyObj, b_obj: PyObj) -> PyReturn {
    let type_a = a_obj.type_();
    let type_b = b_obj.type_();

    // Easy case: ZonedDT - ZonedDT
    let (state, inst_a, inst_b) = if type_a == type_b {
        // SAFETY: one of the operands is guaranteed to be the self type
        let (cls, a) = unsafe { a_obj.assume_heaptype_ref::<ZonedDateTime>() };
        let (_, b) = unsafe { b_obj.assume_heaptype_ref::<ZonedDateTime>() };
        (cls.state(), a.instant(), b.instant())
    // Other cases are more difficult, as they can be triggered
    // by reflexive operations with arbitrary types.
    // We need to eliminate them carefully.
    } else if let Some(state) = type_a.same_module(type_b) {
        // SAFETY: the way we've structured binary operations within whenever
        // ensures that the first operand is the self type.
        let (cls, slf) = unsafe { a_obj.assume_heaptype_ref::<ZonedDateTime>() };
        let inst_b = if let Some(i) = b_obj.extract(*state.instant_type) {
            i
        } else if let Some(odt) = b_obj.extract(*state.offset_datetime_type) {
            odt.instant()
        } else {
            return shift_operator(state, cls, slf, b_obj, true);
        };
        (state, slf.instant(), inst_b)
    } else {
        return not_implemented();
    };
    inst_a.diff(inst_b).to_obj(*state.time_delta_type)
}

fn shift_operator(
    state: &State,
    cls: HeapType<ZonedDateTime>,
    slf: &ZonedDateTime,
    arg: PyObj,
    negate: bool,
) -> PyReturn {
    let mut months = DeltaMonths::ZERO;
    let mut days = DeltaDays::ZERO;
    let mut tdelta = TimeDelta::ZERO;

    if let Some(d) = arg.extract(*state.time_delta_type) {
        tdelta = d;
    } else if let Some(d) = arg.extract(*state.date_delta_type) {
        months = d.months;
        days = d.days;
    } else if let Some(d) = arg.extract(*state.datetime_delta_type) {
        months = d.ddelta.months;
        days = d.ddelta.days;
        tdelta = d.tdelta;
    } else if let Some(d) = arg.extract(*state.itemized_date_delta_type) {
        let (m, dy) = d.to_months_days().ok_or_range_err()?;
        months = m;
        days = dy;
    } else if let Some(d) = arg.extract(*state.itemized_delta_type) {
        let (m, dy, td) = d.to_components().ok_or_range_err()?;
        months = m;
        days = dy;
        tdelta = td;
    } else {
        raise_type_err(format!(
            "unsupported operand type(s) for -: 'ZonedDateTime' and '{}'",
            arg.type_()
        ))?;
    }
    months = months.negate_if(negate);
    days = days.negate_if(negate);
    tdelta = tdelta.negate_if(negate);

    slf.shift(months, days, tdelta, None, state, cls)
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

fn exact_eq(cls: HeapType<ZonedDateTime>, slf: &ZonedDateTime, obj_b: PyObj) -> PyReturn {
    if let Some(zdt) = obj_b.extract_ref(cls) {
        (slf == zdt).to_py()
    } else {
        raise_type_err("can't compare different types")?
    }
}

fn to_tz(cls: HeapType<ZonedDateTime>, slf: &ZonedDateTime, tz_obj: PyObj) -> PyReturn {
    slf.instant()
        .to_tz_py(cls.state().tz_store.obj_get(tz_obj)?, cls)
}

pub(crate) fn unpickle(state: &State, args: &[PyObj]) -> PyReturn {
    let &[data, tz_obj] = args else {
        raise_type_err("invalid pickle data")?
    };
    let py_bytes = data
        .cast_exact::<PyBytes>()
        .ok_or_type_err("invalid pickle data")?;
    let mut packed = py_bytes.as_bytes();
    if packed.len() != 15 {
        raise_type_err("invalid pickle data")?;
    }
    ZonedDateTime {
        date: Date {
            year: Year::new_unchecked(unpack_one!(packed, u16)),
            month: Month::new_unchecked(unpack_one!(packed, u8)),
            day: unpack_one!(packed, u8),
        },
        time: Time {
            hour: unpack_one!(packed, u8),
            minute: unpack_one!(packed, u8),
            second: unpack_one!(packed, u8),
            subsec: SubSecNanos::new_unchecked(unpack_one!(packed, i32)),
        },
        offset: Offset::new_unchecked(unpack_one!(packed, i32)),
        tz: state.tz_store.obj_get(tz_obj)?,
    }
    .to_obj(*state.zoned_datetime_type)
}

fn to_stdlib(cls: HeapType<ZonedDateTime>, slf: &ZonedDateTime) -> PyReturn {
    // Chosen approach: get the UTC date and time, then use ZoneInfo.fromutc().
    // This ensures we preserve the instant in time in the rare case
    // that ZoneInfo disagrees with our offset.
    // FUTURE: document the rare case that offsets could disagree
    let DateTime {
        date: Date { year, month, day },
        time:
            Time {
                hour,
                minute,
                second,
                subsec,
            },
    } = slf
        .local()
        .shift_by_offset(-slf.offset.as_offset_delta())
        // Safety: we know the UTC date and time are valid
        .unwrap();
    let state = cls.state();
    let &PyDateTime_CAPI {
        DateTime_FromDateAndTime,
        DateTimeType,
        TimeZone_FromTimeZone,
        Delta_FromDelta,
        DeltaType,
        ..
    } = state.py_api()?;
    let tzinfo = match slf.tz.key.as_ref() {
        Some(key) => state.zoneinfo_type.get()?.call1(*key.as_str().to_py()?),
        None => {
            let offset = slf.offset;
            // SAFETY: calling C API with valid arguments
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
            unsafe { TimeZone_FromTimeZone(delta.as_ptr(), NULL()) }.own()
        }
    }?;

    tzinfo.getattr(c"fromutc")?.call1(
        // SAFETY: calling C API with valid arguments
        *unsafe {
            DateTime_FromDateAndTime(
                year.get().into(),
                month.get().into(),
                day.into(),
                hour.into(),
                minute.into(),
                second.into(),
                (subsec.get() / 1_000) as _,
                tzinfo.as_ptr(),
                DateTimeType,
            )
        }
        .own()?,
    )
}

fn py_datetime(cls: HeapType<ZonedDateTime>, slf: &ZonedDateTime) -> PyReturn {
    warn_with_class(
        *cls.state().warn_deprecation,
        c"py_datetime() is deprecated. Use to_stdlib() instead.",
        1,
    )?;
    to_stdlib(cls, slf)
}

fn to_instant(cls: HeapType<ZonedDateTime>, slf: &ZonedDateTime) -> PyReturn {
    slf.instant().to_obj(*cls.state().instant_type)
}

fn to_fixed_offset(cls: HeapType<ZonedDateTime>, slf: &ZonedDateTime, args: &[PyObj]) -> PyReturn {
    let state = cls.state();
    match *args {
        [] => OffsetDateTime::new_unchecked(slf.date, slf.time, slf.offset),
        [arg] => slf
            .instant()
            .to_offset(Offset::from_obj(arg, *state.time_delta_type)?)
            .ok_or_range_err()?,
        _ => raise_type_err("to_fixed_offset() takes at most 1 argument")?,
    }
    .to_obj(*state.offset_datetime_type)
}

fn to_system_tz(cls: HeapType<ZonedDateTime>, slf: &ZonedDateTime) -> PyReturn {
    slf.instant()
        .to_tz_py(cls.state().tz_store.get_system_tz()?, cls)
}

fn date(cls: HeapType<ZonedDateTime>, slf: &ZonedDateTime) -> PyReturn {
    slf.date.to_obj(*cls.state().date_type)
}

fn time(cls: HeapType<ZonedDateTime>, slf: &ZonedDateTime) -> PyReturn {
    slf.time.to_obj(*cls.state().time_type)
}

fn day_of_year(_: HeapType<ZonedDateTime>, slf: &ZonedDateTime) -> PyReturn {
    let d = slf.date;
    (d.year.days_before_month(d.month) + d.day as u16).to_py()
}

fn days_in_month(_: HeapType<ZonedDateTime>, slf: &ZonedDateTime) -> PyReturn {
    let d = slf.date;
    d.year.days_in_month(d.month).to_py()
}

fn days_in_year(_: HeapType<ZonedDateTime>, slf: &ZonedDateTime) -> PyReturn {
    (if slf.date.year.is_leap() { 366 } else { 365 }).to_py()
}

fn in_leap_year(_: HeapType<ZonedDateTime>, slf: &ZonedDateTime) -> PyReturn {
    slf.date.year.is_leap().to_py()
}

fn start_of(cls: HeapType<ZonedDateTime>, slf: &ZonedDateTime, unit_obj: PyObj) -> PyReturn {
    let unit = BoundaryUnit::from_py(cls.state(), unit_obj)?;

    // Behavior differs:
    // 1. Calendar units always consume folds. A unit is only "started" once
    //    with the next "start of day/week/month/year".
    // 2. Other units consume folds under certain conditions, but not always.
    match unit {
        BoundaryUnit::Date(_) | BoundaryUnit::Day => slf
            .local()
            .start_of_unit(unit)
            .ok_or_range_err()?
            .localize_default(&slf.tz)
            .ok_or_range_err()?
            .assume_tz_unchecked(slf.tz.clone(), cls),
        BoundaryUnit::Time(_) => {
            let start_local = slf.local().start_of_unit(unit).ok_or_range_err()?;
            match slf.tz.ambiguity_for_local(start_local.local_epoch()) {
                Ambiguity::Unambiguous(f) => start_local.with_offset(f),
                Ambiguity::Fold(_, earlier_offset, later_offset) => {
                    // Use the 'later' part of the fold if we're already in it.
                    // Otherwise, use the earlier part.
                    start_local.with_offset(if later_offset == slf.offset {
                        later_offset
                    } else {
                        earlier_offset
                    })
                }
                Ambiguity::Gap(end, later_offset, _) => {
                    end.datetime(slf.time.subsec).with_offset(later_offset)
                }
            }
        }
        .ok_or_range_err()?
        .assume_tz_unchecked(slf.tz.clone(), cls),
    }
}

fn end_of(cls: HeapType<ZonedDateTime>, slf: &ZonedDateTime, unit_obj: PyObj) -> PyReturn {
    let unit = BoundaryUnit::from_py(cls.state(), unit_obj)?;

    // Behavior differs:
    // 1. Calendar units always consume folds--so that it seamlessly lines up
    //    with the next "start of day/week/month/year".
    // 2. Other units consume folds under certain conditions, but not always.
    match unit {
        BoundaryUnit::Date(_) | BoundaryUnit::Day => slf
            // Calculate the start of the next unit, then step back one ns.
            .local()
            .next_start_of_unit(unit)
            .ok_or_range_err()?
            .localize_default(&slf.tz)
            .ok_or_range_err()?
            .instant()
            .shift(-TimeDelta::RESOLUTION)
            .unwrap()
            .to_tz_py(slf.tz.clone(), cls),
        BoundaryUnit::Time(u) => {
            let end_local = slf.local().end_of_unit(unit).ok_or_range_err()?;
            let local_epoch = end_local.local_epoch();
            match slf.tz.ambiguity_for_local(local_epoch) {
                Ambiguity::Unambiguous(f) => end_local.with_offset(f),
                Ambiguity::Fold(end, earlier_offset, later_offset) => {
                    end_local.with_offset(
                        // Use the 'later' part of the fold if...
                        if
                        // ...(a) we're already in that part of the fold...
                        later_offset == slf.offset ||
                        // ...or (b) we're exactly at the end of the fold, and the fold is
                        // shorter than the unit.
                        (local_epoch.get() + 1 == end.get()
                            && earlier_offset.sub(later_offset).get() < u.in_secs())
                        {
                            later_offset
                        } else {
                            earlier_offset
                        },
                    )
                }
                Ambiguity::Gap(end, later_offset, earlier_offset) => end
                    .saturating_add_i32(-later_offset.sub(earlier_offset).get() - 1)
                    .datetime(SubSecNanos::MAX)
                    .with_offset(earlier_offset),
            }
        }
        .ok_or_range_err()?
        .assume_tz_unchecked(slf.tz.clone(), cls),
    }
}

fn replace_date(
    cls: HeapType<ZonedDateTime>,
    slf: &ZonedDateTime,
    args: &[PyObj],
    kwargs: &mut IterKwargs,
) -> PyReturn {
    let state = cls.state();

    let &[arg] = args else {
        raise_type_err(format!(
            "replace_date() takes exactly 1 argument but {} were given",
            args.len()
        ))?
    };

    let dis = Disambiguate::from_only_kwarg(kwargs, "replace_date", state)?;
    let ZonedDateTime {
        time,
        offset,
        ref tz,
        ..
    } = *slf;
    arg.extract(*state.date_type)
        .ok_or_type_err("date must be a whenever.Date")?
        .at(time)
        .localize_custom(tz, dis, offset, state)?
        .assume_tz_unchecked(tz.clone(), cls)
}

fn replace_time(
    cls: HeapType<ZonedDateTime>,
    slf: &ZonedDateTime,
    args: &[PyObj],
    kwargs: &mut IterKwargs,
) -> PyReturn {
    let state = cls.state();
    let &[arg] = args else {
        raise_type_err(format!(
            "replace_time() takes exactly 1 argument but {} were given",
            args.len()
        ))?
    };

    let dis = Disambiguate::from_only_kwarg(kwargs, "replace_time", state)?;
    let ZonedDateTime {
        date,
        offset,
        ref tz,
        ..
    } = *slf;
    arg.extract(*state.time_type)
        .ok_or_type_err("time must be a whenever.Time instance")?
        .on(date)
        .localize_custom(tz, dis, offset, state)?
        .assume_tz_unchecked(tz.clone(), cls)
}

fn format_iso(
    cls: HeapType<ZonedDateTime>,
    slf: &ZonedDateTime,
    args: &[PyObj],
    kwargs: &mut IterKwargs,
) -> PyReturn {
    fmt::format_iso(
        slf.date,
        slf.time,
        cls.state(),
        args,
        kwargs,
        Suffix::OffsetTz(slf.offset, slf.tz.key.as_deref()),
    )
}

fn parse_iso(cls: HeapType<ZonedDateTime>, arg: PyObj) -> PyReturn {
    let py_str = arg
        .cast_allow_subclass::<PyStr>()
        // NOTE: this exception message also needs to make sense when
        // called through the constructor
        .ok_or_type_err("when parsing from ISO format, the argument must be str")?;
    let mut s = Scan::new(py_str.as_utf8()?);
    let (dt, (offset, tzstr)) = DateTime::read_iso(&mut s)
        .zip(read_offset_and_tzname(&mut s))
        .ok_or_else_value_err(|| format!("Invalid format: {arg}"))?;
    let state = cls.state();
    let tz = state.tz_store.get(tzstr)?;
    match offset {
        OffsetInIsoString::Some(offset) => {
            // Make sure the offset is valid
            match tz.ambiguity_for_local(dt.assume_utc().epoch) {
                Ambiguity::Unambiguous(f) if f == offset => (),
                Ambiguity::Fold(_, earlier_offset, later_offset)
                    if earlier_offset == offset || later_offset == offset => {}
                _ => raise(
                    *state.exc_invalid_offset,
                    format!("invalid offset for {tzstr}"),
                )?,
            }
            dt.with_offset(offset)
                .ok_or_range_err()?
                .assume_tz_unchecked(tz.clone(), cls)
        }
        OffsetInIsoString::Z => dt.assume_utc().to_tz_py(tz, cls),
        OffsetInIsoString::Missing => dt
            .localize_default(&tz)
            .ok_or_range_err()?
            .assume_tz_unchecked(tz, cls),
    }
}

fn replace(
    cls: HeapType<ZonedDateTime>,
    slf: &ZonedDateTime,
    args: &[PyObj],
    kwargs: &mut IterKwargs,
) -> PyReturn {
    if !args.is_empty() {
        raise_type_err("replace() takes no positional arguments")?;
    }
    let state = cls.state();
    let ZonedDateTime {
        date,
        time,
        offset,
        ref tz,
    } = *slf;
    let mut year = date.year.get().into();
    let mut month = date.month.get().into();
    let mut day = date.day.into();
    let mut hour = time.hour.into();
    let mut minute = time.minute.into();
    let mut second = time.second.into();
    let mut nanos = time.subsec.get() as _;
    let mut dis = None;
    let mut tz_new = None;

    handle_kwargs("replace", kwargs, |key, value, eq| {
        if eq(key, *state.str_tz) {
            let tz_arg = state.tz_store.obj_get(value)?;
            // If we change timezones, forget about trying to preserve the offset.
            // Just use compatible disambiguation.
            if !Arc::ptr_eq(tz, &tz_arg) && **tz != *tz_arg {
                dis = Some(Disambiguate::Compatible);
            }
            tz_new = Some(tz_arg);
        } else if eq(key, *state.str_disambiguate) {
            dis = Some(Disambiguate::from_py(value, state)?);
        } else {
            return set_components_from_kwargs(
                key,
                value,
                &mut year,
                &mut month,
                &mut day,
                &mut hour,
                &mut minute,
                &mut second,
                &mut nanos,
                state,
                eq,
            );
        }
        Ok(true)
    })?;

    let tz = tz_new.unwrap_or_else(|| tz.clone());
    Date::from_longs(year, month, day)
        .ok_or_value_err("invalid date")?
        .at(Time::from_longs(hour, minute, second, nanos).ok_or_value_err("invalid time")?)
        .localize_custom(&tz, dis, offset, state)?
        .assume_tz_unchecked(tz, cls)
}

fn now(cls: HeapType<ZonedDateTime>, tz_obj: PyObj) -> PyReturn {
    let state = cls.state();
    state.now()?.to_tz_py(state.tz_store.obj_get(tz_obj)?, cls)
}

fn now_in_system_tz(cls: HeapType<ZonedDateTime>) -> PyReturn {
    let state = cls.state();
    state.now()?.to_tz_py(state.tz_store.get_system_tz()?, cls)
}

fn from_system_tz(cls: HeapType<ZonedDateTime>, args: PyTuple, kwargs: Option<PyDict>) -> PyReturn {
    let state = cls.state();
    let mut year: c_long = 0;
    let mut month: c_long = 0;
    let mut day: c_long = 0;
    let mut hour: c_long = 0;
    let mut minute: c_long = 0;
    let mut second: c_long = 0;
    let mut nanosecond: c_long = 0;
    let mut disambiguate: *mut PyObject = NULL();

    parse_args_kwargs!(
        args,
        kwargs,
        c"lll|lll$lO:ZonedDateTime",
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
        .map_or(Ok(Disambiguate::Compatible), |o| {
            Disambiguate::from_py(o, state)
        })?;
    Date::from_longs(year, month, day)
        .ok_or_value_err("invalid date")?
        .at(Time::from_longs(hour, minute, second, nanosecond).ok_or_value_err("invalid time")?)
        .localize_using_disambiguate(&tz, dis, state)?
        .assume_tz_unchecked(tz, cls)
}

fn from_py_datetime(cls: HeapType<ZonedDateTime>, arg: PyObj) -> PyReturn {
    warn_with_class(
        *cls.state().warn_deprecation,
        c"from_py_datetime() is deprecated. Use ZonedDateTime() constructor instead.",
        1,
    )?;
    let Some(dt) = arg.cast_allow_subclass::<PyDateTime>() else {
        raise_type_err("argument must be a datetime.datetime instance")?
    };
    from_py_datetime_inner(cls, dt)
}

fn from_py_datetime_inner(cls: HeapType<ZonedDateTime>, dt: PyDateTime) -> PyReturn {
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
    .to_tz_py(tz, cls)
}

fn to_plain(cls: HeapType<ZonedDateTime>, slf: &ZonedDateTime) -> PyReturn {
    slf.local().to_obj(*cls.state().plain_datetime_type)
}

fn timestamp(_: PyType, slf: &ZonedDateTime) -> PyReturn {
    slf.instant().epoch.get().to_py()
}

fn timestamp_millis(_: PyType, slf: &ZonedDateTime) -> PyReturn {
    slf.instant().timestamp_millis().to_py()
}

fn timestamp_nanos(_: PyType, slf: &ZonedDateTime) -> PyReturn {
    slf.instant().timestamp_nanos().to_py()
}

fn __reduce__(cls: HeapType<ZonedDateTime>, slf: &ZonedDateTime) -> PyReturn {
    let ZonedDateTime {
        date: Date { year, month, day },
        time:
            Time {
                hour,
                minute,
                second,
                subsec,
            },
        offset,
        ref tz,
    } = *slf;
    if tz.key.is_none() {
        return raise_value_err("cannot pickle ZonedDateTime with unknown timezone ID");
    }
    let data = pack![
        year.get(),
        month.get(),
        day,
        hour,
        minute,
        second,
        subsec.get(),
        offset.get()
    ];
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
        (&[_], Some((key, value))) if kwargs.len() == 1 => {
            if key.py_eq(*state.str_tz)? {
                state.tz_store.obj_get(value)
            } else {
                raise_type_err(format!(
                    "{fname}() got an unexpected keyword argument {key}"
                ))
            }
        }
        (&[_], None) => raise_type_err(format!(
            "{fname}() missing 1 required keyword-only argument: 'tz'"
        )),
        (&[], _) => raise_type_err(format!("{fname}() missing 1 required positional argument")),
        _ => raise_type_err(format!(
            "{}() expected 2 arguments, got {}",
            fname,
            args.len() + (kwargs.len() as usize)
        )),
    }
}

fn from_timestamp(
    cls: HeapType<ZonedDateTime>,
    args: &[PyObj],
    kwargs: &mut IterKwargs,
) -> PyReturn {
    let state = cls.state();
    let tz = check_from_timestamp_args_return_tz(args, kwargs, state, "from_timestamp")?;

    if let Some(py_int) = args[0].cast_allow_subclass::<PyInt>() {
        Instant::from_timestamp(py_int.to_i64()?)
    } else if let Some(py_float) = args[0].cast_allow_subclass::<PyFloat>() {
        Instant::from_timestamp_f64(py_float.to_f64()?)
    } else {
        raise_type_err("timestamp must be an integer or float")?
    }
    .ok_or_range_err()?
    .to_tz_py(tz, cls)
}

fn from_timestamp_millis(
    cls: HeapType<ZonedDateTime>,
    args: &[PyObj],
    kwargs: &mut IterKwargs,
) -> PyReturn {
    let state = cls.state();
    let tz = check_from_timestamp_args_return_tz(args, kwargs, state, "from_timestamp_millis")?;
    Instant::from_timestamp_millis(
        args[0]
            .cast_allow_subclass::<PyInt>()
            .ok_or_type_err("timestamp must be an integer")?
            .to_i64()?,
    )
    // FUTURE: a faster way to check both bounds
    .ok_or_range_err()?
    .to_tz_py(tz, cls)
}

fn from_timestamp_nanos(
    cls: HeapType<ZonedDateTime>,
    args: &[PyObj],
    kwargs: &mut IterKwargs,
) -> PyReturn {
    let state = cls.state();
    let tz = check_from_timestamp_args_return_tz(args, kwargs, state, "from_timestamp_nanos")?;
    Instant::from_timestamp_nanos(
        args[0]
            .cast_allow_subclass::<PyInt>()
            .ok_or_type_err("timestamp must be an integer")?
            .to_i128()?,
    )
    .ok_or_range_err()?
    .to_tz_py(tz, cls)
}

fn is_ambiguous(_: PyType, slf: &ZonedDateTime) -> PyReturn {
    let ZonedDateTime {
        date, time, ref tz, ..
    } = *slf;
    matches!(
        tz.ambiguity_for_local(date.epoch_at(time)),
        Ambiguity::Fold(_, _, _)
    )
    .to_py()
}

fn next_transition(cls: HeapType<ZonedDateTime>, slf: &ZonedDateTime) -> PyReturn {
    match slf.tz.next_transition(slf.instant().epoch) {
        Some((epoch, offset)) => epoch
            .offset(offset)
            .ok_or_range_err()?
            .datetime(SubSecNanos::MIN)
            .with_offset_unchecked(offset)
            .assume_tz_unchecked(slf.tz.clone(), cls),
        None => Ok(none()),
    }
}

fn prev_transition(cls: HeapType<ZonedDateTime>, slf: &ZonedDateTime) -> PyReturn {
    match slf.tz.prev_transition(slf.instant().epoch) {
        Some((epoch, offset)) => epoch
            .offset(offset)
            .ok_or_range_err()?
            .datetime(SubSecNanos::MIN)
            .with_offset_unchecked(offset)
            .assume_tz_unchecked(slf.tz.clone(), cls),
        None => Ok(none()),
    }
}

fn dst_offset(cls: HeapType<ZonedDateTime>, slf: &ZonedDateTime) -> PyReturn {
    let state = cls.state();
    let meta = slf.tz.meta_for_instant(slf.instant().epoch);
    TimeDelta::from_nanos_unchecked(meta.dst_saving as i128 * 1_000_000_000)
        .to_obj(*state.time_delta_type)
}

fn tz_abbrev(_: PyType, slf: &ZonedDateTime) -> PyReturn {
    let meta = slf.tz.meta_for_instant(slf.instant().epoch);
    // SAFETY: TzAbbrev always contains valid ASCII bytes
    unsafe { std::str::from_utf8_unchecked(meta.abbrev.as_bytes()) }.to_py()
}

fn add(
    cls: HeapType<ZonedDateTime>,
    slf: &ZonedDateTime,
    args: &[PyObj],
    kwargs: &mut IterKwargs,
) -> PyReturn {
    shift_method(cls, slf, args, kwargs, false)
}

fn subtract(
    cls: HeapType<ZonedDateTime>,
    slf: &ZonedDateTime,
    args: &[PyObj],
    kwargs: &mut IterKwargs,
) -> PyReturn {
    shift_method(cls, slf, args, kwargs, true)
}

fn shift_method(
    cls: HeapType<ZonedDateTime>,
    slf: &ZonedDateTime,
    args: &[PyObj],
    kwargs: &mut IterKwargs,
    negate: bool,
) -> PyReturn {
    let fname = if negate { "subtract" } else { "add" };
    let state = cls.state();
    let mut dis = None;
    let mut months = DeltaMonths::ZERO;
    let mut days = DeltaDays::ZERO;
    let mut tdelta = TimeDelta::ZERO;

    match *args {
        [arg] => {
            match kwargs.next() {
                Some((key, value))
                    if kwargs.len() == 1 && key.py_eq(*state.str_disambiguate)? =>
                {
                    dis = Some(Disambiguate::from_py(value, state)?)
                }
                None => {}
                _ => raise_type_err(format!(
                    "{fname}() can't mix positional and keyword arguments"
                ))?,
            };
            if let Some(d) = arg.extract(*state.time_delta_type) {
                tdelta = d;
            } else if let Some(d) = arg.extract(*state.date_delta_type) {
                months = d.months;
                days = d.days;
            } else if let Some(d) = arg.extract(*state.datetime_delta_type) {
                months = d.ddelta.months;
                days = d.ddelta.days;
                tdelta = d.tdelta;
            } else if let Some(d) = arg.extract(*state.itemized_date_delta_type) {
                let (m, dy) = d.to_months_days().ok_or_range_err()?;
                months = m;
                days = dy;
            } else if let Some(d) = arg.extract(*state.itemized_delta_type) {
                let (m, dy, td) = d.to_components().ok_or_range_err()?;
                months = m;
                days = dy;
                tdelta = td;
            } else {
                raise_type_err(format!("{fname}() argument must be a delta"))?
            }
        }
        [] => {
            let mut units = DeltaUnitSet::EMPTY;
            handle_kwargs(fname, kwargs, |key, value, eq| {
                if eq(key, *state.str_disambiguate) {
                    dis = Disambiguate::from_py(value, state)?.into();
                    Ok(true)
                } else {
                    handle_delta_unit_kwargs(
                        key,
                        value,
                        &mut months,
                        &mut days,
                        &mut tdelta,
                        &mut units,
                        eq,
                        true,
                        true,
                        state,
                    )
                }
            })?;
        }
        _ => raise_type_err(format!(
            "{}() takes at most 1 positional argument, got {}",
            fname,
            args.len()
        ))?,
    }
    months = months.negate_if(negate);
    days = days.negate_if(negate);
    tdelta = tdelta.negate_if(negate);

    slf.shift(months, days, tdelta, dis, state, cls)
}

fn difference(cls: HeapType<ZonedDateTime>, slf: &ZonedDateTime, arg: PyObj) -> PyReturn {
    let state = cls.state();
    let inst_a = slf.instant();

    let inst_b = if let Some(zdt) = arg.extract_ref(cls) {
        zdt.instant()
    } else if let Some(i) = arg.extract(*state.instant_type) {
        i
    } else if let Some(odt) = arg.extract(*state.offset_datetime_type) {
        odt.instant()
    } else {
        raise_type_err(
            "difference() argument must be an OffsetDateTime, Instant, or ZonedDateTime",
        )?
    };
    inst_a.diff(inst_b).to_obj(*state.time_delta_type)
}

fn start_of_day(cls: HeapType<ZonedDateTime>, slf: &ZonedDateTime) -> PyReturn {
    warn_with_class(
        *cls.state().warn_deprecation,
        c"start_of_day() is deprecated; use start_of(\"day\") instead.",
        1,
    )?;
    slf.local()
        .start_of_unit(BoundaryUnit::Day)
        .ok_or_range_err()?
        .localize_default(&slf.tz)
        .ok_or_range_err()?
        .assume_tz_unchecked(slf.tz.clone(), cls)
}

fn day_length(cls: HeapType<ZonedDateTime>, slf: &ZonedDateTime) -> PyReturn {
    let ZonedDateTime { date, ref tz, .. } = *slf;
    let start_of_day = date
        .at(Time::MIN)
        .localize_default(tz)
        .ok_or_range_err()?
        .instant();
    let start_of_next_day = date
        .tomorrow()
        .ok_or_range_err()?
        .at(Time::MIN)
        .localize_default(tz)
        .ok_or_range_err()?
        .instant();
    start_of_next_day
        .diff(start_of_day)
        .to_obj(*cls.state().time_delta_type)
}

fn round(
    cls: HeapType<ZonedDateTime>,
    slf: &ZonedDateTime,
    args: &[PyObj],
    kwargs: &mut IterKwargs,
) -> PyReturn {
    let round::Args {
        increment, mode, ..
    } = round::Args::parse(cls.state(), args, kwargs, false)?;

    match increment {
        round::RoundIncrement::Day => round_day(slf, mode),
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
            DateTime {
                date,
                time: time_rounded,
            }
            .localize_using_offset(tz, offset)
        }
    }
    .ok_or_range_err()?
    .assume_tz_unchecked(slf.tz.clone(), cls)
}

fn round_day(slf: &ZonedDateTime, mode: round::Mode) -> Option<OffsetDateTime> {
    let ZonedDateTime {
        date, time, ref tz, ..
    } = *slf;
    let get_floor = || date.at(Time::MIN).localize_default(tz);
    let get_ceil = || date.tomorrow()?.at(Time::MIN).localize_default(tz);
    match mode {
        round::Mode::Ceil | round::Mode::Expand => {
            // Round up anything *except* midnight (which is a no-op)
            if time == Time::MIN {
                Some(slf.fixed_offset())
            } else {
                get_ceil()
            }
        }
        round::Mode::Floor | round::Mode::Trunc => get_floor(),
        _ => {
            let time_ns = time.total_nanos();
            let floor = get_floor()?;
            let ceil = get_ceil()?;
            let day_ns = ceil.instant().diff(floor.instant()).total_nanos() as u64;
            debug_assert!(day_ns > 1);
            // Time is always non-negative, so half_trunc=half_floor, half_expand=half_ceil
            let threshold = match mode {
                round::Mode::HalfEven => day_ns / 2 + (time_ns % 2 == 0) as u64,
                round::Mode::HalfFloor | round::Mode::HalfTrunc => day_ns / 2 + 1,
                round::Mode::HalfCeil | round::Mode::HalfExpand => day_ns / 2,
                _ => unreachable!(),
            };
            Some(if time_ns >= threshold { ceil } else { floor })
        }
    }
}

fn tz_err_display(k: &Option<String>) -> String {
    match k {
        Some(key) => format!("timezone '{key}'"),
        None => "the system timezone (with unknown ID)".to_string(),
    }
}

fn since(
    cls: HeapType<ZonedDateTime>,
    slf: &ZonedDateTime,
    args: &[PyObj],
    kwargs: &mut IterKwargs,
) -> PyReturn {
    zoned_since(cls, slf, args, kwargs, false)
}

fn until(
    cls: HeapType<ZonedDateTime>,
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
    unit: math::DeltaUnit,
    neg: bool,
) -> PyReturn {
    match unit.to_exact(false) {
        Ok(u) => {
            // For nanoseconds (in_nanos == 1), return int to preserve full precision.
            let nanos = a.instant().diff(b.instant()).total_nanos();
            let unit_nanos = u.in_nanos();
            if unit_nanos == 1 {
                nanos.to_py()
            } else {
                (nanos as f64 / unit_nanos as f64).to_py()
            }
        }
        Err(cal_unit) => {
            let (result, trunc_raw, expand_raw) = math::date_diff_single_unit(
                target_date,
                b.date,
                DateRoundIncrement::MIN,
                cal_unit,
                neg,
            )
            .ok_or_range_err()?;
            let trunc = b.with_date(trunc_raw.into()).ok_or_range_err()?.instant();
            let expand = b.with_date(expand_raw.into()).ok_or_range_err()?.instant();
            // result is signed; take absolute value and restore sign at the end.
            // num/denom ratio is always positive (same sign).
            let num = a.instant().diff(trunc).total_nanos() as f64;
            let denom = expand.diff(trunc).total_nanos() as f64;
            let sign: f64 = if neg { -1.0 } else { 1.0 };
            ((result.abs() as f64 + num / denom) * sign).to_py()
        }
    }
}

pub(crate) fn zoned_target(
    mut target_date: Date,
    a_inst: Instant,
    b: &ZonedDateTime,
    neg: bool,
) -> Option<Date> {
    // Adjust target_date so the exact remainder has the same sign.
    // The while loop handles the rare case of a 24h+ gap (e.g. Samoa 2011).
    if !neg {
        while b.with_date(target_date)?.instant() > a_inst {
            target_date = target_date.yesterday()?;
        }
    } else {
        while b.with_date(target_date)?.instant() < a_inst {
            target_date = target_date.tomorrow()?;
        }
    }
    Some(target_date)
}

fn zoned_since(
    cls: HeapType<ZonedDateTime>,
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
    let kwargs = SinceUntilKwargs::parse(fname, state, kwargs)?;

    if kwargs.has_calendar() && !slf.same_tz(other) {
        raise_value_err(
            "Calendar units can only be used to compare ZonedDateTimes \
             with the same timezone",
        )?;
    }
    let (a, b) = if flip { (other, slf) } else { (slf, other) };
    let a_inst = a.instant();
    let neg = a_inst < b.instant();

    let target_date = zoned_target(a.date, a_inst, b, neg).ok_or_range_err()?;

    match kwargs {
        SinceUntilKwargs::Total(unit) => {
            zoned_since_float(a.fixed_offset(), b, target_date, unit, neg)
        }
        SinceUntilKwargs::InUnits(units, round_mode, round_increment) => zoned_since_in_units(
            a.fixed_offset(),
            a_inst,
            b,
            target_date,
            units,
            round_mode,
            round_increment,
            neg,
        )
        .ok_or_range_err()?
        .to_obj(*state.itemized_delta_type),
    }
}

#[allow(clippy::too_many_arguments)]
pub(crate) fn zoned_since_in_units(
    a: OffsetDateTime,
    a_inst: Instant,
    b: &ZonedDateTime,
    target_date: Date,
    units: DeltaUnitSet,
    round_mode: round::Mode,
    round_increment: math::RoundIncrement,
    neg: bool,
) -> Option<ItemizedDelta> {
    let (cal_units, exact_units) = units.split_cal_exact();
    let (mut ddelta, trunc_date, expand_date) = if cal_units.is_empty() {
        (ItemizedDateDelta::UNSET, b.date.into(), a.date.into())
    } else {
        let inc = if exact_units.is_empty() {
            round_increment.to_date()?
        } else {
            DateRoundIncrement::MIN
        };
        math::date_diff(target_date, b.date, inc, cal_units, neg)?
    };

    let trunc = b.with_date(trunc_date.into())?.instant();
    let expand = b.with_date(expand_date.into())?.instant();

    // If there are no time units, round the calendar units.
    // Otherwise, calculate the time delta remainder
    let mut result = if exact_units.is_empty() {
        ddelta.round_by_time(
            cal_units.smallest(),
            a_inst,
            trunc,
            expand,
            round_mode.to_abs_trunc(neg),
            round_increment.to_date()?,
            neg,
        );
        ItemizedDelta::UNSET
    } else {
        a_inst.diff(trunc).in_exact_units(
            exact_units,
            round_increment,
            round_mode.to_abs_euclid(neg),
        )?
    };

    result.fill_cal_units(ddelta);
    result.into()
}

fn format(_cls: HeapType<ZonedDateTime>, slf: &ZonedDateTime, pattern_obj: PyObj) -> PyReturn {
    let pattern_pystr = pattern_obj
        .cast_exact::<PyStr>()
        .ok_or_type_err("format() argument must be str")?;
    let pattern_str = pattern_pystr.as_utf8()?;
    let elements = pattern::compile(pattern_str).into_value_err()?;
    pattern::validate_fields(
        &elements,
        pattern::CategorySet::DATE_TIME_OFFSET_TZ,
        "ZonedDateTime",
    )?;
    if pattern::has_12h_without_ampm(&elements) {
        warn_with_class(
            exc_user_warning(),
            c"12-hour format (ii) without AM/PM designator (a/aa) may be ambiguous",
            1,
        )?;
    }
    let meta = slf.tz.meta_for_instant(slf.instant().epoch);
    // SAFETY: TzAbbrev always contains valid ASCII bytes
    let abbrev_str = unsafe { std::str::from_utf8_unchecked(meta.abbrev.as_bytes()) };
    let tz_key = slf.tz.key.as_deref().unwrap_or("");
    let vals = pattern::FormatValues {
        year: slf.date.year,
        month: slf.date.month,
        day: slf.date.day,
        weekday: slf.date.day_of_week(),
        hour: slf.time.hour,
        minute: slf.time.minute,
        second: slf.time.second,
        nanos: slf.time.subsec,
        offset_secs: Some(slf.offset),
        tz_id: Some(tz_key),
        tz_abbrev: Some(abbrev_str),
    };
    pattern::format_to_py(&elements, &vals)
}

fn __format__(cls: HeapType<ZonedDateTime>, slf: &ZonedDateTime, spec_obj: PyObj) -> PyReturn {
    if spec_obj.is_truthy() {
        format(cls, slf, spec_obj)
    } else {
        __str__(cls.into(), slf)
    }
}

fn parse(cls: HeapType<ZonedDateTime>, args: &[PyObj], kwargs: &mut IterKwargs) -> PyReturn {
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

    let state = cls.state();
    let mut fmt_obj = None;
    let mut dis = Disambiguate::Compatible;
    handle_kwargs("parse", kwargs, |key, value, eq| {
        if eq(key, *state.str_format) {
            fmt_obj = Some(value);
        } else if eq(key, *state.str_disambiguate) {
            dis = Disambiguate::from_py(value, state)?;
        } else {
            return Ok(false);
        }
        Ok(true)
    })?;

    let fmt_obj = fmt_obj.ok_or_else(|| {
        raise_type_err::<(), _>("parse() requires 'format' keyword argument").unwrap_err()
    })?;
    let fmt_pystr = fmt_obj
        .cast_exact::<PyStr>()
        .ok_or_type_err("format must be str")?;
    let fmt_bytes = fmt_pystr.as_utf8()?;

    let elements = pattern::compile(fmt_bytes).into_value_err()?;
    pattern::validate_fields(
        &elements,
        pattern::CategorySet::DATE_TIME_OFFSET_TZ,
        "ZonedDateTime",
    )?;

    let parsed = pattern::parse_to_state(&elements, s).into_value_err()?;

    let tz_id = parsed
        .tz_id
        .as_deref()
        .ok_or_value_err("ZonedDateTime.parse() pattern must include a timezone ID field (VV)")?;

    let year = parsed
        .year
        .ok_or_value_err("Pattern must include year, month, and day fields")?;
    let month = parsed
        .month
        .ok_or_value_err("Pattern must include year, month, and day fields")?;
    let day = parsed
        .day
        .ok_or_value_err("Pattern must include year, month, and day fields")?;

    let date = Date::new(year, month, day).ok_or_value_err("Invalid date")?;

    if let Some(wd) = parsed.weekday
        && date.day_of_week() != wd
    {
        raise_value_err("Parsed weekday does not match the date")?;
    }

    let hour = parsed.hour.unwrap_or(0);
    let minute = parsed.minute.unwrap_or(0);
    let second = parsed.second.unwrap_or(0);
    let dt =
        date.at(Time::new(hour, minute, second, parsed.nanos).ok_or_value_err("Invalid time")?);
    let tz = state.tz_store.get(tz_id)?;
    // NOTE: we can't reuse localize_*() methods because we need to outright
    // reject invalid offsets, rather than just disambiguate them.
    if let Some(offset) = parsed.offset_secs {
        // Use offset to disambiguate during DST transitions.
        match tz.ambiguity_for_local(dt.assume_utc().epoch) {
            Ambiguity::Unambiguous(f) if f == offset => dt
                .with_offset(offset)
                .ok_or_range_err()?
                .assume_tz_unchecked(tz, cls),
            Ambiguity::Fold(_, earlier_offset, later_offset)
                if earlier_offset == offset || later_offset == offset =>
            {
                dt.with_offset(offset)
                    .ok_or_range_err()?
                    .assume_tz_unchecked(tz, cls)
            }
            Ambiguity::Gap(_, _, _) => raise_value_err(format!(
                "The local time does not exist in timezone {tz_id:?}"
            )),
            _ => raise_value_err(format!(
                "Offset {}s does not match timezone {tz_id:?}",
                offset.get()
            )),
        }
    } else {
        // No offset provided — use disambiguate kwarg
        dt.localize_using_disambiguate(&tz, dis, state)?
            .assume_tz_unchecked(tz, cls)
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
    method1!(ZonedDateTime, exact_eq, doc::EXACTTIME_EXACT_EQ),
    method0!(ZonedDateTime, to_stdlib, doc::BASICCONVERSIONS_TO_STDLIB),
    method0!(
        ZonedDateTime,
        py_datetime,
        doc::BASICCONVERSIONS_PY_DATETIME
    ),
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
    classmethod1!(ZonedDateTime, parse_iso, doc::ZONEDDATETIME_PARSE_ISO),
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
                        unsafe { HeapType::from_ptr_unchecked(cls.cast()) },
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
    classmethod1!(
        ZonedDateTime,
        from_py_datetime,
        doc::BASICCONVERSIONS_FROM_PY_DATETIME
    ),
    method0!(ZonedDateTime, timestamp, doc::EXACTTIME_TIMESTAMP),
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
    method0!(ZonedDateTime, start_of_day, doc::ZONEDDATETIME_START_OF_DAY),
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

fn tz(_: PyType, slf: &ZonedDateTime) -> PyReturn {
    match slf.tz.key.as_ref() {
        Some(key) => key.as_str().to_py(),
        None => Ok(none()),
    }
}

fn offset(cls: HeapType<ZonedDateTime>, slf: &ZonedDateTime) -> PyReturn {
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
