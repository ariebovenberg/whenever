use core::{
    ffi::{c_int, c_long, c_void},
    ptr::null_mut as NULL,
};
use pyo3_ffi::*;
use std::ptr::NonNull;

use crate::{
    classes::{
        date::Date,
        datetime_delta::set_units_from_kwargs,
        instant::Instant,
        offset_datetime::OffsetDateTime,
        plain_datetime::{DateTime, set_components_from_kwargs},
        time::Time,
        time_delta::TimeDelta,
    },
    common::{
        ambiguity::*,
        fmt::{self, Sink, Suffix},
        parse::Scan,
        round,
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

#[derive(Debug, Copy, Clone)]
pub(crate) struct ZonedDateTime {
    date: Date,
    time: Time,
    offset: Offset,
    tz: TzPtr,
}

impl std::cmp::PartialEq for ZonedDateTime {
    fn eq(&self, other: &Self) -> bool {
        self.date == other.date
            && self.time == other.time
            && self.offset == other.offset
            && *self.tz == *other.tz
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
        date.epoch_at(time)
            .offset(-offset)
            .ok_or_value_err("Resulting datetime is out of range")?;
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
                        .ok_or_value_err("Resulting date is out of range")?,
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
                    .ok_or_value_err("Resulting date is out of range")?
                    .with_offset(offset)
            }
        }
        // or the shifted datetime represents an invalid instant
        .ok_or_value_err("Resulting time is out of range")
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
            Gap(offset0, offset1) => {
                let (offset, shift) = if target == offset0 {
                    (offset0, offset0.sub(offset1))
                } else {
                    (offset1, offset1.sub(offset0))
                };
                DateTime { date, time }
                    .change_offset(shift)
                    .ok_or_value_err("Resulting date is out of range")?
                    .with_offset(offset)
            }
        }
        .ok_or_value_err("Resulting time is out of range")
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
                date.shift(months, days)
                    .ok_or_value_err("Resulting date is out of range")?,
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
            .ok_or_value_err("Instant is out of range")?
            .to_tz(self.tz.new_non_unique(), cls)
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
            .ok_or_value_err("Resulting date is out of range")?
            .datetime(self.subsec);
        // SAFETY: We've already checked for both out-of-range date and time.
        ZonedDateTime::new_unchecked(local.date, local.time, offset, tz, cls)
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
    let date = Date::from_longs(year, month, day).ok_or_value_err("Invalid date")?;
    let time =
        Time::from_longs(hour, minute, second, nanosecond).ok_or_value_err("Invalid time")?;
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
    slf.tz.decref_with_cleanup(|| &cls.state().tz_store);
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
        b"ZonedDateTime(",
        date.format_iso(false),
        b' ',
        time.format_iso(fmt::Unit::Auto, false),
        offset.format_iso(false),
        b'[',
        &tz.key
            .as_deref()
            .unwrap_or("<system timezone without ID>")
            .as_bytes(),
        b"])",
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
        _shift_operator(state, cls, slf, b_obj, false)
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
            return _shift_operator(state, cls, slf, b_obj, true);
        };
        (state, slf.instant(), inst_b)
    } else {
        return not_implemented();
    };
    inst_a.diff(inst_b).to_obj(state.time_delta_type)
}

#[inline]
fn _shift_operator(
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
    } else {
        raise_type_err(format!(
            "unsupported operand type(s) for -: 'ZonedDateTime' and '{}'",
            arg.type_()
        ))?;
    }
    if negate {
        months = -months;
        days = -days;
        tdelta = -tdelta;
    };

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
    if let Some(odt) = obj_b.extract(cls) {
        (slf == odt).to_py()
    } else {
        raise_type_err("Can't compare different types")?
    }
}

fn to_tz(cls: HeapType<ZonedDateTime>, slf: ZonedDateTime, tz_obj: PyObj) -> PyReturn {
    let tz_new = cls.state().tz_store.obj_get(tz_obj)?;
    slf.instant().to_tz(tz_new, cls)
}

pub(crate) fn unpickle(state: &State, args: &[PyObj]) -> PyReturn {
    let &[data, tz_obj] = args else {
        raise_type_err("Invalid pickle data")?
    };
    let &State {
        zoned_datetime_type,
        ref tz_store,
        ..
    } = state;

    let py_bytes = data
        .cast::<PyBytes>()
        .ok_or_type_err("Invalid pickle data")?;
    let mut packed = py_bytes.as_bytes()?;
    if packed.len() != 15 {
        raise_type_err("Invalid pickle data")?;
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

fn py_datetime(cls: HeapType<ZonedDateTime>, slf: ZonedDateTime) -> PyReturn {
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
            .ok_or_value_err("Resulting local date is out of range")?,
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
            .assume_tz_unchecked(tz.new_non_unique(), cls)
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
    .assume_tz_unchecked(tz.new_non_unique(), cls)
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
    let mut tz = tz.new_non_unique();

    handle_kwargs("replace", kwargs, |key, value, eq| {
        if eq(key, str_tz) {
            let tz_new = tz_store.obj_get(value)?;
            // If we change timezones, forget about trying to preserve the offset.
            // Just use compatible disambiguation.
            if tz_new.as_ptr() != tz.as_ptr() {
                dis.get_or_insert(Disambiguate::Compatible);
            };
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

    let date = Date::from_longs(year, month, day).ok_or_value_err("Invalid date")?;
    let time = Time::from_longs(hour, minute, second, nanos).ok_or_value_err("Invalid time")?;
    ZonedDateTime::resolve(date, time, &tz, dis, offset, exc_repeated, exc_skipped)?
        .assume_tz_unchecked(tz, cls)
}

fn now(cls: HeapType<ZonedDateTime>, tz_obj: PyObj) -> PyReturn {
    let state = cls.state();
    let tz = state.tz_store.obj_get(tz_obj)?;
    state.time_ns()?.to_tz(tz, cls)
}

fn from_py_datetime(cls: HeapType<ZonedDateTime>, arg: PyObj) -> PyReturn {
    let State {
        zoneinfo_type,
        tz_store,
        ..
    } = cls.state();

    let Some(dt) = arg.cast_allow_subclass::<PyDateTime>() else {
        raise_type_err("Argument must be a datetime.datetime instance")?
    };
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
        .cast::<PyFloat>()
        .ok_or_raise(
            unsafe { PyExc_RuntimeError },
            "datetime.datetime.timestamp() returned non-float",
        )?
        .to_f64()?;
    Instant {
        epoch: EpochSecs::new(epoch_float.floor() as _).ok_or_value_err("instant out of range")?,
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
        return raise_value_err("Cannot pickle ZonedDateTime with unknown timezone ID");
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
        .ok_or_value_err("Cannot pickle ZonedDateTime without timezone ID")?;
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

    if let Some(py_int) = args[0].cast::<PyInt>() {
        Instant::from_timestamp(py_int.to_i64()?)
    } else if let Some(py_float) = args[0].cast::<PyFloat>() {
        Instant::from_timestamp_f64(py_float.to_f64()?)
    } else {
        raise_type_err("Timestamp must be an integer or float")?
    }
    .ok_or_value_err("timestamp is out of range")?
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
            .cast::<PyInt>()
            .ok_or_type_err("timestamp must be an integer")?
            .to_i64()?,
    )
    // FUTURE: a faster way to check both bounds
    .ok_or_value_err("timestamp is out of range")?
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
            .cast::<PyInt>()
            .ok_or_type_err("timestamp must be an integer")?
            .to_i128()?,
    )
    .ok_or_value_err("timestamp is out of range")?
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

fn parse_iso(cls: HeapType<ZonedDateTime>, arg: PyObj) -> PyReturn {
    let py_str = arg
        .cast::<PyStr>()
        .ok_or_type_err("Argument must be a string")?;
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
                    format!("Invalid offset for {tzstr}"),
                )?,
            }
            ZonedDateTime::create(date, time, offset, tz, cls)
        }
        OffsetInIsoString::Z => Instant::from_datetime(date, time).to_tz(tz, cls),
        OffsetInIsoString::Missing => ZonedDateTime::resolve_default(date, time, tz, cls),
    }
}

fn add(
    cls: HeapType<ZonedDateTime>,
    slf: ZonedDateTime,
    args: &[PyObj],
    kwargs: &mut IterKwargs,
) -> PyReturn {
    _shift_method(cls, slf, args, kwargs, false)
}

fn subtract(
    cls: HeapType<ZonedDateTime>,
    slf: ZonedDateTime,
    args: &[PyObj],
    kwargs: &mut IterKwargs,
) -> PyReturn {
    _shift_method(cls, slf, args, kwargs, true)
}

#[inline]
fn _shift_method(
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
        ..
    } = state;
    let mut dis = None;
    let mut monthdelta = DeltaMonths::ZERO;
    let mut daydelta = DeltaDays::ZERO;
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
                monthdelta = d.months;
                daydelta = d.days;
            } else if let Some(d) = arg.extract(datetime_delta_type) {
                monthdelta = d.ddelta.months;
                daydelta = d.ddelta.days;
                tdelta = d.tdelta;
            } else {
                raise_type_err(format!("{fname}() argument must be a delta"))?
            }
        }
        [] => {
            let mut nanos: i128 = 0;
            let mut months: i32 = 0;
            let mut days: i32 = 0;
            handle_kwargs(fname, kwargs, |key, value, eq| {
                if eq(key, str_disambiguate) {
                    dis = Some(Disambiguate::from_py(
                        value,
                        str_compatible,
                        str_raise,
                        str_earlier,
                        str_later,
                    )?);
                    Ok(true)
                } else {
                    set_units_from_kwargs(key, value, &mut months, &mut days, &mut nanos, state, eq)
                }
            })?;
            tdelta = TimeDelta::from_nanos(nanos).ok_or_value_err("Total duration too large")?;
            monthdelta = DeltaMonths::new(months).ok_or_value_err("Total months out of range")?;
            daydelta = DeltaDays::new(days).ok_or_value_err("Total days out of range")?;
        }
        _ => raise_type_err(format!(
            "{}() takes at most 1 positional argument, got {}",
            fname,
            args.len()
        ))?,
    }
    if negate {
        monthdelta = -monthdelta;
        daydelta = -daydelta;
        tdelta = -tdelta;
    }

    slf.shift(
        monthdelta,
        daydelta,
        tdelta,
        dis,
        exc_repeated,
        exc_skipped,
        cls,
    )
}

fn difference(cls: HeapType<ZonedDateTime>, slf: ZonedDateTime, arg: PyObj) -> PyReturn {
    let state = cls.state();
    let inst_a = slf.instant();

    let inst_b = if let Some(zdt) = arg.extract(cls) {
        zdt.instant()
    } else if let Some(i) = arg.extract(state.instant_type) {
        i
    } else if let Some(odt) = arg.extract(state.offset_datetime_type) {
        odt.instant()
    } else {
        raise_type_err(
            "difference() argument must be an OffsetDateTime, Instant, or ZonedDateTime",
        )?
    };
    inst_a.diff(inst_b).to_obj(state.time_delta_type)
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
    .assume_tz_unchecked(tz.new_non_unique(), cls)
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
        date.tomorrow().ok_or_value_err("Day out of range")?,
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
    let (unit, increment, mode) = round::parse_args(state, args, kwargs, false, false)?;

    match unit {
        round::Unit::Day => _round_day(slf, state, mode),
        _ => {
            let ZonedDateTime {
                mut date,
                time,
                offset,
                tz,
            } = slf;
            let (time_rounded, next_day) = time.round(increment as u64, mode);
            if next_day == 1 {
                date = date
                    .tomorrow()
                    .ok_or_value_err("Resulting date out of range")?;
            };
            ZonedDateTime::resolve_using_offset(date, time_rounded, &tz, offset)
        }
    }?
    .assume_tz_unchecked(slf.tz.new_non_unique(), cls)
}

fn _round_day(slf: ZonedDateTime, state: &State, mode: round::Mode) -> PyResult<OffsetDateTime> {
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
            date.tomorrow()
                .ok_or_value_err("Resulting date out of range")?,
            Time::MIDNIGHT,
            &tz,
            Disambiguate::Compatible,
            exc_repeated,
            exc_skipped,
        )
    };
    match mode {
        round::Mode::Ceil => {
            // Round up anything *except* midnight (which is a no-op)
            if time == Time::MIDNIGHT {
                Ok(slf.without_tz())
            } else {
                get_ceil()
            }
        }
        round::Mode::Floor => get_floor(),
        _ => {
            let time_ns = time.total_nanos();
            let floor = get_floor()?;
            let ceil = get_ceil()?;
            let day_ns = ceil.instant().diff(floor.instant()).total_nanos() as u64;
            debug_assert!(day_ns > 1);
            let threshold = match mode {
                round::Mode::HalfEven => day_ns / 2 + (time_ns % 2 == 0) as u64,
                round::Mode::HalfFloor => day_ns / 2 + 1,
                round::Mode::HalfCeil => day_ns / 2,
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
