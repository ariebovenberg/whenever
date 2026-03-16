use crate::{
    classes::{
        date::Date,
        instant::Instant,
        itemized_date_delta::ItemizedDateDelta,
        itemized_delta::{ItemizedDelta, handle_delta_unit_kwargs},
        offset_datetime::OffsetDateTime,
        plain_datetime::{DateTime, set_components_from_kwargs},
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
    tz::{
        store::{TzHandle, TzPtr},
        tzif::TimeZone,
    },
};
use core::{
    ffi::{c_int, c_long, c_void},
    ptr::null_mut as NULL,
};
use pyo3_ffi::*;
use std::ptr::NonNull;

// FUTURE: can we make this non-Copy? Copy makes it possible to accidentally
// allocate multiple instances with the same timezone pointer, which can lead to double-frees if
// both are deallocated. Currently we rely on careful code review to avoid this, but it would be
// nice to have a safety net.
#[derive(Debug, Copy, Clone)]
pub(crate) struct ZonedDateTime {
    pub(crate) date: Date,
    time: Time,
    offset: Offset,
    pub(crate) tz: TzPtr,
}

impl std::cmp::PartialEq for ZonedDateTime {
    fn eq(&self, other: &Self) -> bool {
        self.date == other.date
            && self.time == other.time
            && self.offset == other.offset
            && self.tz.is_same_tz(other.tz)
    }
}

impl ZonedDateTime {
    pub(crate) fn create(
        date: Date,
        time: Time,
        offset: Offset,
        tz: TzHandle<'_>,
        cls: HeapType<Self>,
    ) -> PyReturn {
        // Check: the instant represented by the date and time is within range
        date.epoch_at(time).offset(-offset).ok_or_range_err()?;
        Self::new_unchecked(date, time, offset, tz, cls)
    }

    pub(crate) fn new_unchecked(
        date: Date,
        time: Time,
        offset: Offset,
        tz: TzHandle<'_>,
        cls: HeapType<Self>,
    ) -> PyReturn {
        generic_alloc(
            cls.into(),
            ZonedDateTime {
                date,
                time,
                offset,
                tz: tz.into_py(),
            },
        )
    }

    pub(crate) fn resolve_default(
        date: Date,
        time: Time,
        tz: TzHandle<'_>,
        cls: HeapType<Self>,
    ) -> PyReturn {
        let (DateTime { date, time }, offset) = match tz.ambiguity_for_local(date.epoch_at(time)) {
            Ambiguity::Unambiguous(offset) | Ambiguity::Fold(offset, _) => {
                (DateTime { date, time }, offset)
            }
            Ambiguity::Gap(offset, offset_prev) => {
                let shift = offset.sub(offset_prev);
                (
                    DateTime { date, time }
                        .change_offset(shift)
                        .ok_or_range_err()?,
                    offset,
                )
            }
        };
        ZonedDateTime::create(date, time, offset, tz, cls)
    }

    #[allow(clippy::too_many_arguments)]
    pub(crate) fn resolve(
        date: Date,
        time: Time,
        tz: &TimeZone,
        dis: Option<Disambiguate>,
        preferred_offset: Offset,
        exc_repeated: PyObj,
        exc_skipped: PyObj,
    ) -> PyResult<OffsetDateTime> {
        match dis {
            Some(d) => {
                Self::resolve_using_disambiguate(date, time, tz, d, exc_repeated, exc_skipped)
            }
            None => Self::resolve_using_offset(date, time, tz, preferred_offset),
        }
    }

    pub(crate) fn resolve_using_disambiguate(
        date: Date,
        time: Time,
        tz: &TimeZone,
        dis: Disambiguate,
        exc_repeated: PyObj,
        exc_skipped: PyObj,
    ) -> PyResult<OffsetDateTime> {
        match tz.ambiguity_for_local(date.epoch_at(time)) {
            Ambiguity::Unambiguous(offset) => OffsetDateTime::new(date, time, offset),
            Ambiguity::Fold(earlier, later) => OffsetDateTime::new(
                date,
                time,
                match dis {
                    Disambiguate::Earlier => earlier,
                    Disambiguate::Later => later,
                    Disambiguate::Compatible => earlier,
                    Disambiguate::Raise => raise(
                        exc_repeated.as_ptr(),
                        format!(
                            "{} {} is repeated in {}",
                            date,
                            time,
                            tz_err_display(&tz.key)
                        ),
                    )?,
                },
            ),
            Ambiguity::Gap(later, earlier) => {
                let shift = later.sub(earlier);
                let dt = DateTime { date, time };
                let (shift, offset) = match dis {
                    Disambiguate::Earlier => (-shift, earlier),
                    Disambiguate::Later => (shift, later),
                    Disambiguate::Compatible => (shift, later),
                    Disambiguate::Raise => raise(
                        exc_skipped.as_ptr(),
                        format!(
                            "{} {} is skipped in {}",
                            date,
                            time,
                            tz_err_display(&tz.key)
                        ),
                    )?,
                };
                dt.change_offset(shift)
                    // shifting out of the gap can result in an out-of-range date
                    .ok_or_range_err()?
                    .with_offset(offset)
            }
        }
        // or the shifted datetime represents an invalid instant
        .ok_or_range_err()
    }

    /// Resolve a local time in a timezone, trying to reuse the given offset
    /// if it is valid. Otherwise, the "compatible" disambiguation is used.
    fn resolve_using_offset(
        date: Date,
        time: Time,
        tz: &TimeZone,
        target: Offset,
    ) -> PyResult<OffsetDateTime> {
        use Ambiguity::*;
        match tz.ambiguity_for_local(date.epoch_at(time)) {
            Unambiguous(offset) => OffsetDateTime::new(date, time, offset),
            Fold(offset0, offset1) => OffsetDateTime::new(
                date,
                time,
                if target == offset1 { offset1 } else { offset0 },
            ),
            // For gaps, don't try to reuse the previous offset since the
            // time doesn't exist. Use "compatible" (later) behavior.
            Gap(later, earlier) => {
                let shift = later.sub(earlier);
                DateTime { date, time }
                    .change_offset(shift)
                    .ok_or_range_err()?
                    .with_offset(later)
            }
        }
        .ok_or_range_err()
    }

    pub(crate) fn instant(self) -> Instant {
        Instant::from_datetime(self.date, self.time)
            .offset(-self.offset)
            // Safe: we know the instant of a ZonedDateTime is always valid
            .unwrap()
    }

    pub(crate) const fn without_offset(self) -> DateTime {
        DateTime {
            date: self.date,
            time: self.time,
        }
    }

    pub(crate) fn without_tz(self) -> OffsetDateTime {
        OffsetDateTime {
            date: self.date,
            time: self.time,
            offset: self.offset,
        }
    }

    pub(crate) fn with_date(self, new_date: Date) -> Option<OffsetDateTime> {
        self.without_tz().with_date_in_tz(new_date, self.tz)
    }

    pub(crate) fn shift_default(self, delta: ItemizedDelta) -> Option<OffsetDateTime> {
        let (months, days, tdelta) = delta.to_components()?;
        self.without_tz().shift_in_tz(months, days, tdelta, self.tz)
    }

    #[allow(clippy::too_many_arguments)]
    pub(crate) fn shift(
        self,
        months: DeltaMonths,
        days: DeltaDays,
        delta: TimeDelta,
        dis: Option<Disambiguate>,
        exc_repeated: PyObj,
        exc_skipped: PyObj,
        cls: HeapType<Self>,
    ) -> PyReturn {
        let shifted_by_date = if !months.is_zero() || !days.is_zero() {
            let ZonedDateTime {
                date,
                time,
                tz,
                offset,
            } = self;
            Self::resolve(
                date.shift(months, days).ok_or_range_err()?,
                time,
                &tz,
                dis,
                offset,
                exc_repeated,
                exc_skipped,
            )?
        } else {
            self.without_tz()
        };

        shifted_by_date
            .instant()
            .shift(delta)
            .ok_or_range_err()?
            .to_tz(self.tz.newref(), cls)
    }
}

impl OffsetDateTime {
    fn with_date_in_tz(self, new_date: Date, tz: TzPtr) -> Option<OffsetDateTime> {
        match tz.ambiguity_for_local(new_date.epoch_at(self.time)) {
            Ambiguity::Unambiguous(offset) => OffsetDateTime::new(new_date, self.time, offset),
            Ambiguity::Fold(earlier, later) => {
                // Compatible: pick the offset matching the original
                let offset = if self.offset == later { later } else { earlier };
                OffsetDateTime::new(new_date, self.time, offset)
            }
            Ambiguity::Gap(later, earlier) => {
                // Compatible: shift to later
                let shift = later.sub(earlier);
                DateTime {
                    date: new_date,
                    time: self.time,
                }
                .change_offset(shift)?
                .with_offset(later)
            }
        }
    }

    pub(crate) fn shift_in_tz(
        self,
        months: DeltaMonths,
        days: DeltaDays,
        tdelta: TimeDelta,
        tz: TzPtr,
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
    /// Convert an instant to a zoned datetime in the given timezone.
    /// Returns None if the resulting date would be out of range.
    pub(crate) fn to_tz(self, tz: TzHandle<'_>, cls: HeapType<ZonedDateTime>) -> PyReturn {
        let epoch = self.epoch;
        let offset = tz.offset_for_instant(epoch);
        let local = epoch
            .offset(offset)
            .ok_or_range_err()?
            .datetime(self.subsec);
        // SAFETY: We've already checked for both out-of-range date and time.
        ZonedDateTime::new_unchecked(local.date, local.time, offset, tz, cls)
    }

    // TODO docs
    pub(crate) fn to_tz2(self, tz: TzPtr) -> Option<OffsetDateTime> {
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
        tz: TzHandle<'_>,
        cls: HeapType<ZonedDateTime>,
    ) -> PyReturn {
        ZonedDateTime::new_unchecked(self.date, self.time, self.offset, tz, cls)
    }
}

fn __new__(cls: HeapType<ZonedDateTime>, args: PyTuple, kwargs: Option<PyDict>) -> PyReturn {
    // Alternate constructor: one ISO 8601 string or stdlib datetime argument
    if args.len() == 1 && kwargs.map_or(0, |d| d.len()) == 0 {
        let arg = args.iter().next().unwrap();
        if let Some(dt) = arg.cast_allow_subclass::<PyDateTime>() {
            return from_py_datetime_inner(cls, dt);
        }
        return parse_iso(cls, arg);
    };

    let &State {
        exc_repeated,
        exc_skipped,
        str_compatible,
        str_raise,
        str_earlier,
        str_later,
        ref tz_store,
        ..
    } = cls.state();
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

    let Some(tz) = NonNull::new(tz) else {
        return raise_type_err("tz argument is required");
    };

    let tz = tz_store.obj_get(PyObj::wrap(tz))?;
    let date = Date::from_longs(year, month, day).ok_or_value_err("invalid date")?;
    let time =
        Time::from_longs(hour, minute, second, nanosecond).ok_or_value_err("invalid time")?;
    let dis = match NonNull::new(disambiguate) {
        None => Disambiguate::Compatible,
        Some(dis) => Disambiguate::from_py(
            PyObj::wrap(dis),
            str_compatible,
            str_raise,
            str_earlier,
            str_later,
        )?,
    };
    ZonedDateTime::resolve_using_disambiguate(date, time, &tz, dis, exc_repeated, exc_skipped)?
        .assume_tz_unchecked(tz, cls)
}

extern "C" fn dealloc(arg: PyObj) {
    // SAFETY: the first arg to this function is the self type
    let (cls, slf) = unsafe { arg.assume_heaptype::<ZonedDateTime>() };
    catch_panic!(
        slf.tz.decref_with_cleanup(|| &cls.state().tz_store),
        {
            unsafe {
                // NOTE: we can't pass our instance as a context, since
                // its timezone pointer may be invalid at this point.
                PyErr_WriteUnraisable(NULL());
            }
        },
        "Panic in ZonedDateTime dealloc"
    );
    // As per recommendation, we free the memory regardless of whether
    // the destructor panicked. Worst case: we leak memory of timezone data.
    generic_dealloc(arg)
}

fn __repr__(_: PyType, slf: ZonedDateTime) -> PyReturn {
    let ZonedDateTime {
        date,
        time,
        offset,
        tz,
    } = slf;
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

fn __str__(_: PyType, slf: ZonedDateTime) -> PyReturn {
    let ZonedDateTime {
        date,
        time,
        offset,
        tz,
    } = slf;
    PyAsciiStrBuilder::format((
        date.format_iso(false),
        b'T',
        time.format_iso(fmt::Unit::Auto, false),
        offset.format_iso(false),
        TzFormat { tz },
    ))
}

struct TzFormat {
    tz: TzPtr,
}

impl fmt::Chunk for TzFormat {
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
    a: ZonedDateTime,
    b_obj: PyObj,
    op: c_int,
) -> PyReturn {
    let inst_a = a.instant();
    let inst_b = if let Some(zdt) = b_obj.extract(cls) {
        zdt.instant()
    } else {
        let &State {
            instant_type,
            offset_datetime_type,
            ..
        } = cls.state();

        if let Some(inst) = b_obj.extract(instant_type) {
            inst
        } else if let Some(odt) = b_obj.extract(offset_datetime_type) {
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
    let (_, slf) = unsafe { arg.assume_heaptype::<ZonedDateTime>() };
    hashmask(slf.instant().pyhash())
}

fn __add__(a_obj: PyObj, b_obj: PyObj) -> PyReturn {
    if let Some(state) = a_obj.type_().same_module(b_obj.type_()) {
        // SAFETY: the way we've structured binary operations within whenever
        // ensures that the first operand is the self type.
        let (cls, slf) = unsafe { a_obj.assume_heaptype::<ZonedDateTime>() };
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
        let (cls, a) = unsafe { a_obj.assume_heaptype::<ZonedDateTime>() };
        let (_, b) = unsafe { b_obj.assume_heaptype::<ZonedDateTime>() };
        (cls.state(), a.instant(), b.instant())
    // Other cases are more difficult, as they can be triggered
    // by reflexive operations with arbitrary types.
    // We need to eliminate them carefully.
    } else if let Some(state) = type_a.same_module(type_b) {
        // SAFETY: the way we've structured binary operations within whenever
        // ensures that the first operand is the self type.
        let (cls, slf) = unsafe { a_obj.assume_heaptype::<ZonedDateTime>() };
        let inst_b = if let Some(i) = b_obj.extract(state.instant_type) {
            i
        } else if let Some(odt) = b_obj.extract(state.offset_datetime_type) {
            odt.instant()
        } else {
            return shift_operator(state, cls, slf, b_obj, true);
        };
        (state, slf.instant(), inst_b)
    } else {
        return not_implemented();
    };
    inst_a.diff(inst_b).to_obj(state.time_delta_type)
}

#[inline]
fn shift_operator(
    state: &State,
    cls: HeapType<ZonedDateTime>,
    slf: ZonedDateTime,
    arg: PyObj,
    negate: bool,
) -> PyReturn {
    let &State {
        time_delta_type,
        date_delta_type,
        datetime_delta_type,
        exc_repeated,
        exc_skipped,
        ..
    } = state;

    let mut months = DeltaMonths::ZERO;
    let mut days = DeltaDays::ZERO;
    let mut tdelta = TimeDelta::ZERO;

    if let Some(d) = arg.extract(time_delta_type) {
        tdelta = d;
    } else if let Some(d) = arg.extract(date_delta_type) {
        months = d.months;
        days = d.days;
    } else if let Some(d) = arg.extract(datetime_delta_type) {
        months = d.ddelta.months;
        days = d.ddelta.days;
        tdelta = d.tdelta;
    } else if let Some(d) = arg.extract(state.itemized_date_delta_type) {
        let (m, dy) = d.to_months_days().ok_or_range_err()?;
        months = m;
        days = dy;
    } else if let Some(d) = arg.extract(state.itemized_delta_type) {
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

    slf.shift(months, days, tdelta, None, exc_repeated, exc_skipped, cls)
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

fn exact_eq(cls: HeapType<ZonedDateTime>, slf: ZonedDateTime, obj_b: PyObj) -> PyReturn {
    if let Some(zdt) = obj_b.extract(cls) {
        (slf == zdt).to_py()
    } else {
        raise_type_err("can't compare different types")?
    }
}

fn to_tz(cls: HeapType<ZonedDateTime>, slf: ZonedDateTime, tz_obj: PyObj) -> PyReturn {
    let tz_new = cls.state().tz_store.obj_get(tz_obj)?;
    slf.instant().to_tz(tz_new, cls)
}

pub(crate) fn unpickle(state: &State, args: &[PyObj]) -> PyReturn {
    let &[data, tz_obj] = args else {
        raise_type_err("invalid pickle data")?
    };
    let &State {
        zoned_datetime_type,
        ref tz_store,
        ..
    } = state;

    let py_bytes = data
        .cast_exact::<PyBytes>()
        .ok_or_type_err("invalid pickle data")?;
    let mut packed = py_bytes.as_bytes()?;
    if packed.len() != 15 {
        raise_type_err("invalid pickle data")?;
    }
    ZonedDateTime::new_unchecked(
        Date {
            year: Year::new_unchecked(unpack_one!(packed, u16)),
            month: Month::new_unchecked(unpack_one!(packed, u8)),
            day: unpack_one!(packed, u8),
        },
        Time {
            hour: unpack_one!(packed, u8),
            minute: unpack_one!(packed, u8),
            second: unpack_one!(packed, u8),
            subsec: SubSecNanos::new_unchecked(unpack_one!(packed, i32)),
        },
        Offset::new_unchecked(unpack_one!(packed, i32)),
        tz_store.obj_get(tz_obj)?,
        zoned_datetime_type,
    )
}

fn to_stdlib(cls: HeapType<ZonedDateTime>, slf: ZonedDateTime) -> PyReturn {
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
        .without_offset()
        .change_offset(-slf.offset.as_offset_delta())
        // Safety: we know the UTC date and time are valid
        .unwrap();
    let &State {
        py_api:
            &PyDateTime_CAPI {
                DateTime_FromDateAndTime,
                DateTimeType,
                TimeZone_FromTimeZone,
                Delta_FromDelta,
                DeltaType,
                ..
            },
        ref zoneinfo_type,
        ..
    } = cls.state();

    let tzinfo = match slf.tz.key.as_ref() {
        Some(key) => zoneinfo_type.get()?.call1(key.as_str().to_py()?.borrow()),
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
            .rust_owned()?;
            unsafe { TimeZone_FromTimeZone(delta.as_ptr(), NULL()) }.rust_owned()
        }
    }?;

    tzinfo.getattr(c"fromutc")?.call1(
        // SAFETY: calling C API with valid arguments
        unsafe {
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
        .rust_owned()?
        .borrow(),
    )
}

fn py_datetime(cls: HeapType<ZonedDateTime>, slf: ZonedDateTime) -> PyReturn {
    let &State {
        warn_deprecation, ..
    } = cls.state();
    warn_with_class(
        warn_deprecation,
        c"py_datetime() is deprecated. Use to_stdlib() instead.",
        1,
    )?;
    to_stdlib(cls, slf)
}

fn to_instant(cls: HeapType<ZonedDateTime>, slf: ZonedDateTime) -> PyReturn {
    slf.instant().to_obj(cls.state().instant_type)
}

fn to_fixed_offset(cls: HeapType<ZonedDateTime>, slf: ZonedDateTime, args: &[PyObj]) -> PyReturn {
    let &State {
        offset_datetime_type,
        time_delta_type,
        ..
    } = cls.state();
    match *args {
        [] => OffsetDateTime::new_unchecked(slf.date, slf.time, slf.offset),
        [arg] => slf
            .instant()
            .to_offset(Offset::from_obj(arg, time_delta_type)?)
            .ok_or_range_err()?,
        _ => raise_type_err("to_fixed_offset() takes at most 1 argument")?,
    }
    .to_obj(offset_datetime_type)
}

fn to_system_tz(cls: HeapType<ZonedDateTime>, slf: ZonedDateTime) -> PyReturn {
    let tz_new = cls.state().tz_store.get_system_tz()?;
    slf.instant().to_tz(tz_new, cls)
}

fn date(cls: HeapType<ZonedDateTime>, slf: ZonedDateTime) -> PyReturn {
    slf.date.to_obj(cls.state().date_type)
}

fn time(cls: HeapType<ZonedDateTime>, slf: ZonedDateTime) -> PyReturn {
    slf.time.to_obj(cls.state().time_type)
}

fn replace_date(
    cls: HeapType<ZonedDateTime>,
    slf: ZonedDateTime,
    args: &[PyObj],
    kwargs: &mut IterKwargs,
) -> PyReturn {
    let &State {
        date_type,
        str_disambiguate,
        exc_skipped,
        exc_repeated,
        str_compatible,
        str_raise,
        str_earlier,
        str_later,
        ..
    } = cls.state();

    let &[arg] = args else {
        raise_type_err(format!(
            "replace_date() takes exactly 1 argument but {} were given",
            args.len()
        ))?
    };

    let dis = Disambiguate::from_only_kwarg(
        kwargs,
        str_disambiguate,
        "replace_date",
        str_compatible,
        str_raise,
        str_earlier,
        str_later,
    )?;
    let ZonedDateTime {
        time, tz, offset, ..
    } = slf;
    if let Some(date) = arg.extract(date_type) {
        ZonedDateTime::resolve(date, time, &tz, dis, offset, exc_repeated, exc_skipped)?
            .assume_tz_unchecked(tz.newref(), cls)
    } else {
        raise_type_err("date must be a whenever.Date instance")
    }
}

fn replace_time(
    cls: HeapType<ZonedDateTime>,
    slf: ZonedDateTime,
    args: &[PyObj],
    kwargs: &mut IterKwargs,
) -> PyReturn {
    let &State {
        time_type,
        str_disambiguate,
        exc_skipped,
        exc_repeated,
        str_compatible,
        str_raise,
        str_earlier,
        str_later,
        ..
    } = cls.state();

    let &[arg] = args else {
        raise_type_err(format!(
            "replace_time() takes exactly 1 argument but {} were given",
            args.len()
        ))?
    };

    let dis = Disambiguate::from_only_kwarg(
        kwargs,
        str_disambiguate,
        "replace_time",
        str_compatible,
        str_raise,
        str_earlier,
        str_later,
    )?;
    let ZonedDateTime {
        date, tz, offset, ..
    } = slf;
    ZonedDateTime::resolve(
        date,
        arg.extract(time_type)
            .ok_or_type_err("time must be a whenever.Time instance")?,
        &tz,
        dis,
        offset,
        exc_repeated,
        exc_skipped,
    )?
    .assume_tz_unchecked(tz.newref(), cls)
}

fn format_iso(
    cls: HeapType<ZonedDateTime>,
    slf: ZonedDateTime,
    args: &[PyObj],
    kwargs: &mut IterKwargs,
) -> PyReturn {
    fmt::format_iso(
        slf.date,
        slf.time,
        cls.state(),
        args,
        kwargs,
        Suffix::OffsetTz(slf.offset, slf.tz),
    )
}

fn parse_iso(cls: HeapType<ZonedDateTime>, arg: PyObj) -> PyReturn {
    let py_str = arg
        .cast_allow_subclass::<PyStr>()
        // NOTE: this exception message also needs to make sense when
        // called through the constructor
        .ok_or_type_err("when parsing from ISO format, the argument must be str")?;
    let mut s = Scan::new(py_str.as_utf8()?);
    let (DateTime { date, time }, (offset, tzstr)) = DateTime::read_iso(&mut s)
        .zip(read_offset_and_tzname(&mut s))
        .ok_or_else_value_err(|| format!("Invalid format: {arg}"))?;
    let &State {
        exc_invalid_offset,
        ref tz_store,
        ..
    } = cls.state();
    let tz = tz_store.get(tzstr)?;
    match offset {
        OffsetInIsoString::Some(offset) => {
            // Make sure the offset is valid
            match tz.ambiguity_for_local(date.epoch_at(time)) {
                Ambiguity::Unambiguous(f) if f == offset => (),
                Ambiguity::Fold(f1, f2) if f1 == offset || f2 == offset => (),
                _ => raise(
                    exc_invalid_offset.as_ptr(),
                    format!("invalid offset for {tzstr}"),
                )?,
            }
            ZonedDateTime::create(date, time, offset, tz, cls)
        }
        OffsetInIsoString::Z => Instant::from_datetime(date, time).to_tz(tz, cls),
        OffsetInIsoString::Missing => ZonedDateTime::resolve_default(date, time, tz, cls),
    }
}

fn replace(
    cls: HeapType<ZonedDateTime>,
    slf: ZonedDateTime,
    args: &[PyObj],
    kwargs: &mut IterKwargs,
) -> PyReturn {
    if !args.is_empty() {
        raise_type_err("replace() takes no positional arguments")?;
    }
    let &State {
        exc_repeated,
        exc_skipped,
        str_tz,
        str_disambiguate,
        str_year,
        str_month,
        str_day,
        str_hour,
        str_minute,
        str_second,
        str_nanosecond,
        str_compatible,
        str_raise,
        str_earlier,
        str_later,
        ref tz_store,
        ..
    } = cls.state();
    let ZonedDateTime {
        date,
        time,
        tz,
        offset,
    } = slf;
    let mut year = date.year.get().into();
    let mut month = date.month.get().into();
    let mut day = date.day.into();
    let mut hour = time.hour.into();
    let mut minute = time.minute.into();
    let mut second = time.second.into();
    let mut nanos = time.subsec.get() as _;
    let mut dis = None;
    let mut tz = tz.newref();

    handle_kwargs("replace", kwargs, |key, value, eq| {
        if eq(key, str_tz) {
            let tz_new = tz_store.obj_get(value)?;
            // If we change timezones, forget about trying to preserve the offset.
            // Just use compatible disambiguation.
            if !tz.is_same_tz(*tz_new) {
                dis = Some(Disambiguate::Compatible);
            }
            tz = tz_new;
        } else if eq(key, str_disambiguate) {
            dis = Some(Disambiguate::from_py(
                value,
                str_compatible,
                str_raise,
                str_earlier,
                str_later,
            )?);
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
                str_year,
                str_month,
                str_day,
                str_hour,
                str_minute,
                str_second,
                str_nanosecond,
                eq,
            );
        }
        Ok(true)
    })?;

    let date = Date::from_longs(year, month, day).ok_or_value_err("invalid date")?;
    let time = Time::from_longs(hour, minute, second, nanos).ok_or_value_err("invalid time")?;
    ZonedDateTime::resolve(date, time, &tz, dis, offset, exc_repeated, exc_skipped)?
        .assume_tz_unchecked(tz, cls)
}

fn now(cls: HeapType<ZonedDateTime>, tz_obj: PyObj) -> PyReturn {
    let state = cls.state();
    let tz = state.tz_store.obj_get(tz_obj)?;
    state.time_ns()?.to_tz(tz, cls)
}

fn now_in_system_tz(cls: HeapType<ZonedDateTime>) -> PyReturn {
    let state = cls.state();
    let tz = state.tz_store.get_system_tz()?;
    state.time_ns()?.to_tz(tz, cls)
}

fn from_system_tz(cls: HeapType<ZonedDateTime>, args: PyTuple, kwargs: Option<PyDict>) -> PyReturn {
    let &State {
        exc_repeated,
        exc_skipped,
        str_compatible,
        str_raise,
        str_earlier,
        str_later,
        ref tz_store,
        ..
    } = cls.state();
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

    let tz = tz_store.get_system_tz()?;
    let date = Date::from_longs(year, month, day).ok_or_value_err("invalid date")?;
    let time =
        Time::from_longs(hour, minute, second, nanosecond).ok_or_value_err("invalid time")?;
    let dis = match NonNull::new(disambiguate) {
        None => Disambiguate::Compatible,
        Some(dis) => Disambiguate::from_py(
            PyObj::wrap(dis),
            str_compatible,
            str_raise,
            str_earlier,
            str_later,
        )?,
    };
    ZonedDateTime::resolve_using_disambiguate(date, time, &tz, dis, exc_repeated, exc_skipped)?
        .assume_tz_unchecked(tz, cls)
}

fn from_py_datetime(cls: HeapType<ZonedDateTime>, arg: PyObj) -> PyReturn {
    let &State {
        warn_deprecation, ..
    } = cls.state();
    warn_with_class(
        warn_deprecation,
        c"from_py_datetime() is deprecated. Use ZonedDateTime() constructor instead.",
        1,
    )?;
    let Some(dt) = arg.cast_allow_subclass::<PyDateTime>() else {
        raise_type_err("argument must be a datetime.datetime instance")?
    };
    from_py_datetime_inner(cls, dt)
}

fn from_py_datetime_inner(cls: HeapType<ZonedDateTime>, dt: PyDateTime) -> PyReturn {
    let State {
        zoneinfo_type,
        tz_store,
        ..
    } = cls.state();
    let tzinfo = dt.tzinfo();
    // NOTE: it has to be exactly a `ZoneInfo`, since
    // we *know* that this corresponds to a TZ database entry.
    // Other types could be making up their own rules.
    if tzinfo.type_().as_ptr() != zoneinfo_type.get()?.as_ptr() {
        raise_value_err(format!(
            "tzinfo must be of type ZoneInfo (exactly), got {tzinfo}"
        ))?;
    }
    let key = tzinfo.getattr(c"key")?;
    if key.is_none() {
        raise_value_err(doc::ZONEINFO_NO_KEY_MSG)?;
    };

    let tz = tz_store.obj_get(*key)?;
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
            unsafe { PyExc_RuntimeError },
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
    .to_tz(tz, cls)
}

fn to_plain(cls: HeapType<ZonedDateTime>, slf: ZonedDateTime) -> PyReturn {
    slf.without_offset().to_obj(cls.state().plain_datetime_type)
}

fn timestamp(_: PyType, slf: ZonedDateTime) -> PyReturn {
    slf.instant().epoch.get().to_py()
}

fn timestamp_millis(_: PyType, slf: ZonedDateTime) -> PyReturn {
    slf.instant().timestamp_millis().to_py()
}

fn timestamp_nanos(_: PyType, slf: ZonedDateTime) -> PyReturn {
    slf.instant().timestamp_nanos().to_py()
}

fn __reduce__(cls: HeapType<ZonedDateTime>, slf: ZonedDateTime) -> PyResult<Owned<PyTuple>> {
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
        tz,
    } = slf;
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
    (
        cls.state().unpickle_zoned_datetime.newref(),
        (data.to_py()?, tz_key.as_str().to_py()?).into_pytuple()?,
    )
        .into_pytuple()
}

/// checks the args comply with (ts, /, *, tz: str)
#[inline]
fn check_from_timestamp_args_return_tz<'a>(
    args: &[PyObj],
    kwargs: &mut IterKwargs,
    &State {
        ref tz_store,
        str_tz,
        ..
    }: &'a State,
    fname: &str,
) -> PyResult<TzHandle<'a>> {
    match (args, kwargs.next()) {
        (&[_], Some((key, value))) if kwargs.len() == 1 => {
            if key.py_eq(str_tz)? {
                tz_store.obj_get(value)
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
    .to_tz(tz, cls)
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
    .to_tz(tz, cls)
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
    .to_tz(tz, cls)
}

fn is_ambiguous(_: PyType, slf: ZonedDateTime) -> PyReturn {
    let ZonedDateTime { date, time, tz, .. } = slf;
    matches!(
        tz.ambiguity_for_local(date.epoch_at(time)),
        Ambiguity::Fold(_, _)
    )
    .to_py()
}

fn dst_offset(cls: HeapType<ZonedDateTime>, slf: ZonedDateTime) -> PyReturn {
    let &State {
        time_delta_type, ..
    } = cls.state();
    let meta = slf.tz.meta_for_instant(slf.instant().epoch);
    TimeDelta::from_nanos_unchecked(meta.dst_saving as i128 * 1_000_000_000).to_obj(time_delta_type)
}

fn tz_abbrev(_: PyType, slf: ZonedDateTime) -> PyReturn {
    let meta = slf.tz.meta_for_instant(slf.instant().epoch);
    // SAFETY: TzAbbrev always contains valid ASCII bytes
    unsafe { std::str::from_utf8_unchecked(meta.abbrev.as_bytes()) }.to_py()
}

fn add(
    cls: HeapType<ZonedDateTime>,
    slf: ZonedDateTime,
    args: &[PyObj],
    kwargs: &mut IterKwargs,
) -> PyReturn {
    shift_method(cls, slf, args, kwargs, false)
}

fn subtract(
    cls: HeapType<ZonedDateTime>,
    slf: ZonedDateTime,
    args: &[PyObj],
    kwargs: &mut IterKwargs,
) -> PyReturn {
    shift_method(cls, slf, args, kwargs, true)
}

#[inline]
fn shift_method(
    cls: HeapType<ZonedDateTime>,
    slf: ZonedDateTime,
    args: &[PyObj],
    kwargs: &mut IterKwargs,
    negate: bool,
) -> PyReturn {
    let fname = if negate { "subtract" } else { "add" };
    let state = cls.state();
    let &State {
        time_delta_type,
        date_delta_type,
        datetime_delta_type,
        str_disambiguate,
        exc_repeated,
        exc_skipped,
        str_compatible,
        str_raise,
        str_earlier,
        str_later,
        str_years,
        str_months,
        str_weeks,
        str_days,
        str_hours,
        str_minutes,
        str_seconds,
        str_milliseconds,
        str_microseconds,
        str_nanoseconds,
        itemized_date_delta_type,
        itemized_delta_type,
        ..
    } = state;
    let mut dis = None;
    let mut months = DeltaMonths::ZERO;
    let mut days = DeltaDays::ZERO;
    let mut tdelta = TimeDelta::ZERO;

    match *args {
        [arg] => {
            match kwargs.next() {
                Some((key, value)) if kwargs.len() == 1 && key.py_eq(str_disambiguate)? => {
                    dis = Some(Disambiguate::from_py(
                        value,
                        str_compatible,
                        str_raise,
                        str_earlier,
                        str_later,
                    )?)
                }
                None => {}
                _ => raise_type_err(format!(
                    "{fname}() can't mix positional and keyword arguments"
                ))?,
            };
            if let Some(d) = arg.extract(time_delta_type) {
                tdelta = d;
            } else if let Some(d) = arg.extract(date_delta_type) {
                months = d.months;
                days = d.days;
            } else if let Some(d) = arg.extract(datetime_delta_type) {
                months = d.ddelta.months;
                days = d.ddelta.days;
                tdelta = d.tdelta;
            } else if let Some(d) = arg.extract(itemized_date_delta_type) {
                let (m, dy) = d.to_months_days().ok_or_range_err()?;
                months = m;
                days = dy;
            } else if let Some(d) = arg.extract(itemized_delta_type) {
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
                if eq(key, str_disambiguate) {
                    dis = Disambiguate::from_py(
                        value,
                        str_compatible,
                        str_raise,
                        str_earlier,
                        str_later,
                    )?
                    .into();
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
                        str_years,
                        str_months,
                        str_weeks,
                        str_days,
                        str_hours,
                        str_minutes,
                        str_seconds,
                        Some(str_milliseconds),
                        Some(str_microseconds),
                        str_nanoseconds,
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

    slf.shift(months, days, tdelta, dis, exc_repeated, exc_skipped, cls)
}

fn difference(cls: HeapType<ZonedDateTime>, slf: ZonedDateTime, arg: PyObj) -> PyReturn {
    let &State {
        warn_deprecation,
        instant_type,
        offset_datetime_type,
        time_delta_type,
        ..
    } = cls.state();
    warn_with_class(
        warn_deprecation,
        c"The difference() method is deprecated. Use the subtraction operator or since() method instead.",
        2,
    )?;
    let inst_a = slf.instant();

    let inst_b = if let Some(zdt) = arg.extract(cls) {
        zdt.instant()
    } else if let Some(i) = arg.extract(instant_type) {
        i
    } else if let Some(odt) = arg.extract(offset_datetime_type) {
        odt.instant()
    } else {
        raise_type_err(
            "difference() argument must be an OffsetDateTime, Instant, or ZonedDateTime",
        )?
    };
    inst_a.diff(inst_b).to_obj(time_delta_type)
}

fn start_of_day(cls: HeapType<ZonedDateTime>, slf: ZonedDateTime) -> PyReturn {
    let ZonedDateTime { date, tz, .. } = slf;
    let &State {
        exc_repeated,
        exc_skipped,
        ..
    } = cls.state();
    ZonedDateTime::resolve_using_disambiguate(
        date,
        Time::MIDNIGHT,
        &tz,
        Disambiguate::Compatible,
        exc_repeated,
        exc_skipped,
    )?
    .assume_tz_unchecked(tz.newref(), cls)
}

fn day_length(cls: HeapType<ZonedDateTime>, slf: ZonedDateTime) -> PyReturn {
    let ZonedDateTime { date, tz, .. } = slf;
    let &State {
        exc_repeated,
        exc_skipped,
        time_delta_type,
        ..
    } = cls.state();
    let start_of_day = ZonedDateTime::resolve_using_disambiguate(
        date,
        Time::MIDNIGHT,
        &tz,
        Disambiguate::Compatible,
        exc_repeated,
        exc_skipped,
    )?
    .instant();
    let start_of_next_day = ZonedDateTime::resolve_using_disambiguate(
        date.tomorrow().ok_or_range_err()?,
        Time::MIDNIGHT,
        &tz,
        Disambiguate::Compatible,
        exc_repeated,
        exc_skipped,
    )?
    .instant();
    start_of_next_day.diff(start_of_day).to_obj(time_delta_type)
}

fn round(
    cls: HeapType<ZonedDateTime>,
    slf: ZonedDateTime,
    args: &[PyObj],
    kwargs: &mut IterKwargs,
) -> PyReturn {
    let state = cls.state();
    let round::Args {
        increment, mode, ..
    } = round::Args::parse(state, args, kwargs, false)?;

    match increment {
        round::RoundIncrement::Day => round_day(slf, state, mode),
        round::RoundIncrement::Exact(ns) => {
            let ZonedDateTime {
                mut date,
                time,
                offset,
                tz,
            } = slf;
            let (time_rounded, next_day) = time.round(ns.get(), mode);
            if next_day == 1 {
                date = date.tomorrow().ok_or_range_err()?;
            };
            ZonedDateTime::resolve_using_offset(date, time_rounded, &tz, offset)
        }
    }?
    .assume_tz_unchecked(slf.tz.newref(), cls)
}

fn round_day(slf: ZonedDateTime, state: &State, mode: round::Mode) -> PyResult<OffsetDateTime> {
    let ZonedDateTime { date, time, tz, .. } = slf;
    let &State {
        exc_repeated,
        exc_skipped,
        ..
    } = state;
    let get_floor = || {
        ZonedDateTime::resolve_using_disambiguate(
            date,
            Time::MIDNIGHT,
            &tz,
            Disambiguate::Compatible,
            exc_repeated,
            exc_skipped,
        )
    };
    let get_ceil = || {
        ZonedDateTime::resolve_using_disambiguate(
            date.tomorrow().ok_or_range_err()?,
            Time::MIDNIGHT,
            &tz,
            Disambiguate::Compatible,
            exc_repeated,
            exc_skipped,
        )
    };
    match mode {
        round::Mode::Ceil | round::Mode::Expand => {
            // Round up anything *except* midnight (which is a no-op)
            if time == Time::MIDNIGHT {
                Ok(slf.without_tz())
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
            if time_ns >= threshold {
                Ok(ceil)
            } else {
                Ok(floor)
            }
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
    slf: ZonedDateTime,
    args: &[PyObj],
    kwargs: &mut IterKwargs,
) -> PyReturn {
    zoned_since(cls, slf, args, kwargs, false)
}

fn until(
    cls: HeapType<ZonedDateTime>,
    slf: ZonedDateTime,
    args: &[PyObj],
    kwargs: &mut IterKwargs,
) -> PyReturn {
    zoned_since(cls, slf, args, kwargs, true)
}

fn zoned_since_single_unit(
    a: OffsetDateTime,
    b: ZonedDateTime,
    target_date: Date,
    unit: math::DeltaUnit,
    round_mode: round::Mode,
    round_increment: math::RoundIncrement,
    sign: i8,
) -> PyReturn {
    match unit.to_exact(false) {
        Ok(u) => a
            .instant()
            .diff(b.instant())
            .in_single_unit(u, round_increment, round_mode),
        Err(u) => {
            let inc = round_increment.to_date().ok_or_range_err()?;
            let (result, trunc_date, expand_date) =
                math::date_diff_single_unit(target_date, b.date, inc, u, sign).ok_or_range_err()?;
            let trunc = b.with_date(trunc_date.into()).ok_or_range_err()?.instant();
            let expand = b.with_date(expand_date.into()).ok_or_range_err()?.instant();
            math::round_by_time(result, a.instant(), trunc, expand, round_mode, inc, sign).to_py()
        }
    }
}

pub(crate) fn zoned_target(
    mut target_date: Date,
    a_inst: Instant,
    b: ZonedDateTime,
    sign: i8,
) -> Option<Date> {
    // Adjust target_date so the exact remainder has the same sign.
    // The while loop handles the rare case of a 24h+ gap (e.g. Samoa 2011).
    if sign == 1 {
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
    slf: ZonedDateTime,
    args: &[PyObj],
    kwargs: &mut IterKwargs,
    flip: bool,
) -> PyReturn {
    let fname = if flip { "until" } else { "since" };
    let state = cls.state();

    let other = handle_one_arg(fname, args)?
        .extract(cls)
        .ok_or_type_err("argument must be a whenever.ZonedDateTime")?;
    let SinceUntilKwargs {
        units,
        round_mode,
        round_increment,
    } = SinceUntilKwargs::parse(fname, state, kwargs)?;

    if units.has_calendar() && !slf.tz.is_same_tz(other.tz) {
        raise_value_err(
            "Calendar units can only be used to compare ZonedDateTimes \
             with the same timezone",
        )?;
    }
    let (a, b) = if flip { (other, slf) } else { (slf, other) };
    let a_inst = a.instant();
    let b_inst = b.instant();
    let sign: i8 = if a_inst >= b_inst { 1 } else { -1 };

    let target_date = zoned_target(a.date, a_inst, b, sign).ok_or_range_err()?;

    match units {
        math::UnitsOrUnit::One(unit) => zoned_since_single_unit(
            a.without_tz(),
            b,
            target_date,
            unit,
            round_mode,
            round_increment,
            sign,
        ),
        math::UnitsOrUnit::Seq(units) => zoned_since_in_units(
            a.without_tz(),
            a_inst,
            b,
            target_date,
            units,
            round_mode,
            round_increment,
            sign,
        )
        .ok_or_range_err()?
        .to_obj(state.itemized_delta_type),
    }
}

pub(crate) fn zoned_since_in_units(
    a: OffsetDateTime,
    a_inst: Instant,
    b: ZonedDateTime,
    target_date: Date,
    units: DeltaUnitSet,
    round_mode: round::Mode,
    round_increment: math::RoundIncrement,
    sign: i8,
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
        math::date_diff(target_date, b.date, inc, cal_units, sign)?
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
            round_mode,
            round_increment.to_date()?,
            sign,
        );
        ItemizedDelta::UNSET
    } else {
        a_inst
            .diff(trunc)
            .in_exact_units(exact_units, round_increment, round_mode)?
    };

    result.fill_cal_units(ddelta);
    result.into()
}

fn format(_cls: HeapType<ZonedDateTime>, slf: ZonedDateTime, pattern_obj: PyObj) -> PyReturn {
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
            // SAFETY: PyExc_UserWarning is always valid
            unsafe { PyObj::from_ptr_unchecked(PyExc_UserWarning) },
            c"12-hour format (ii) without AM/PM designator (a/aa) may be ambiguous",
            2,
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

fn __format__(cls: HeapType<ZonedDateTime>, slf: ZonedDateTime, spec_obj: PyObj) -> PyReturn {
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

    let &State {
        str_format,
        str_disambiguate,
        str_compatible,
        str_raise,
        str_earlier,
        str_later,
        exc_repeated,
        exc_skipped,
        ref tz_store,
        ..
    } = cls.state();

    let mut fmt_obj = None;
    let mut dis = Disambiguate::Compatible;
    handle_kwargs("parse", kwargs, |key, value, eq| {
        if eq(key, str_format) {
            fmt_obj = Some(value);
        } else if eq(key, str_disambiguate) {
            dis = Disambiguate::from_py(value, str_compatible, str_raise, str_earlier, str_later)?;
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

    let state = pattern::parse_to_state(&elements, s).into_value_err()?;

    let tz_id = state
        .tz_id
        .as_deref()
        .ok_or_value_err("ZonedDateTime.parse() pattern must include a timezone ID field (VV)")?;

    let year = state
        .year
        .ok_or_value_err("Pattern must include year, month, and day fields")?;
    let month = state
        .month
        .ok_or_value_err("Pattern must include year, month, and day fields")?;
    let day = state
        .day
        .ok_or_value_err("Pattern must include year, month, and day fields")?;

    let date = Date::new(year, month, day).ok_or_value_err("Invalid date")?;

    if let Some(wd) = state.weekday {
        if date.day_of_week() != wd {
            raise_value_err("Parsed weekday does not match the date")?;
        }
    }

    let hour = state.hour.unwrap_or(0);
    let minute = state.minute.unwrap_or(0);
    let second = state.second.unwrap_or(0);

    if hour >= 24 || minute >= 60 || second >= 60 {
        raise_value_err("Invalid time")?;
    }

    let time = Time {
        hour,
        minute,
        second,
        subsec: state.nanos,
    };

    let tz = tz_store.get(tz_id)?;

    if let Some(offset) = state.offset_secs {
        // Use offset to disambiguate during DST transitions.
        // offset is already a validated scalar::Offset — no range check needed.
        match tz.ambiguity_for_local(date.epoch_at(time)) {
            Ambiguity::Unambiguous(f) if f == offset => {
                ZonedDateTime::create(date, time, offset, tz, cls)
            }
            Ambiguity::Fold(f1, f2) if f1 == offset || f2 == offset => {
                ZonedDateTime::create(date, time, offset, tz, cls)
            }
            Ambiguity::Gap(_, _) => raise_value_err(format!(
                "The local time does not exist in timezone {tz_id:?}"
            )),
            _ => raise_value_err(format!(
                "Offset {}s does not match timezone {tz_id:?}",
                offset.get()
            )),
        }
    } else {
        // No offset provided — use disambiguate kwarg
        let odt = ZonedDateTime::resolve_using_disambiguate(
            date,
            time,
            &tz,
            dis,
            exc_repeated,
            exc_skipped,
        )?;
        odt.assume_tz_unchecked(tz, cls)
    }
}

static mut METHODS: &[PyMethodDef] = &[
    method0!(ZonedDateTime, __copy__, c""),
    method1!(ZonedDateTime, __deepcopy__, c""),
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
        doc::ZONEDDATETIME_FROM_PY_DATETIME
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

fn year(_: PyType, slf: ZonedDateTime) -> PyReturn {
    slf.date.year.get().to_py()
}

fn month(_: PyType, slf: ZonedDateTime) -> PyReturn {
    slf.date.month.get().to_py()
}

fn day(_: PyType, slf: ZonedDateTime) -> PyReturn {
    slf.date.day.to_py()
}

fn hour(_: PyType, slf: ZonedDateTime) -> PyReturn {
    slf.time.hour.to_py()
}

fn minute(_: PyType, slf: ZonedDateTime) -> PyReturn {
    slf.time.minute.to_py()
}

fn second(_: PyType, slf: ZonedDateTime) -> PyReturn {
    slf.time.second.to_py()
}

fn nanosecond(_: PyType, slf: ZonedDateTime) -> PyReturn {
    slf.time.subsec.get().to_py()
}

fn tz(_: PyType, slf: ZonedDateTime) -> PyReturn {
    match slf.tz.key.as_ref() {
        Some(key) => key.as_str().to_py(),
        None => Ok(none()),
    }
}

fn offset(cls: HeapType<ZonedDateTime>, slf: ZonedDateTime) -> PyReturn {
    TimeDelta::from_offset(slf.offset).to_obj(cls.state().time_delta_type)
}

static mut GETSETTERS: &[PyGetSetDef] = &[
    // TODO LOW: have these docstrings synced with Python too
    getter!(ZonedDateTime, year, "The year component"),
    getter!(ZonedDateTime, month, "The month component"),
    getter!(ZonedDateTime, day, "The day component"),
    getter!(ZonedDateTime, hour, "The hour component"),
    getter!(ZonedDateTime, minute, "The minute component"),
    getter!(ZonedDateTime, second, "The second component"),
    getter!(ZonedDateTime, nanosecond, "The nanosecond component"),
    getter!(ZonedDateTime, tz, "The tz ID"),
    getter!(ZonedDateTime, offset, "The offset from UTC"),
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
