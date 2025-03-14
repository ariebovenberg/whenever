use core::ffi::{c_int, c_long, c_void, CStr};
use core::ptr::null_mut as NULL;
use pyo3_ffi::*;
use std::fmt::{self, Display, Formatter};

use crate::common::*;
use crate::datetime_delta::set_units_from_kwargs;
use crate::docstrings as doc;
use crate::local_datetime::set_components_from_kwargs;
use crate::tz::cache::TzRef;
use crate::{
    date::{Date, MAX as MAX_DATE},
    date_delta::DateDelta,
    datetime_delta::DateTimeDelta,
    instant::{Instant, MAX_EPOCH, MAX_INSTANT, MIN_EPOCH, MIN_INSTANT},
    local_datetime::DateTime,
    offset_datetime::{self, OffsetDateTime},
    round,
    time::{Time, MIDNIGHT},
    time_delta::{self, TimeDelta},
    State,
};

#[derive(Debug, Eq, PartialEq, Copy, Clone)]
pub(crate) struct ZonedDateTime {
    date: Date,
    time: Time,
    offset_secs: Offset,
    tz: TzRef,
}

pub(crate) const SINGLETONS: &[(&CStr, ZonedDateTime); 0] = &[];

impl ZonedDateTime {
    pub(crate) unsafe fn new(
        date: Date,
        time: Time,
        offset_secs: Offset,
        tz: TzRef,
    ) -> Option<ZonedDateTime> {
        (MIN_EPOCH..=MAX_EPOCH)
            .contains(&(date.timestamp_at(time) - i64::from(offset_secs)))
            .then_some(Self {
                date,
                time,
                offset_secs,
                tz,
            })
    }

    #[allow(clippy::too_many_arguments)]
    pub(crate) unsafe fn resolve(
        date: Date,
        time: Time,
        tz: TzRef,
        dis: Option<Disambiguate>,
        preferred_offset: Offset,
        exc_repeated: *mut PyObject,
        exc_skipped: *mut PyObject,
    ) -> PyResult<Self> {
        match dis {
            Some(d) => {
                Self::resolve_using_disambiguate(date, time, tz, d, exc_repeated, exc_skipped)
            }
            None => Self::resolve_using_offset(date, time, tz, preferred_offset),
        }
    }

    pub(crate) unsafe fn resolve_using_disambiguate(
        date: Date,
        time: Time,
        tz: TzRef,
        dis: Disambiguate,
        exc_repeated: *mut PyObject,
        exc_skipped: *mut PyObject,
    ) -> PyResult<Self> {
        let local_epoch = date.timestamp_at(time);
        let (dt, offset) = match tz.ambiguity_for_local(local_epoch) {
            Ambiguity::Unambiguous(offset) => (DateTime { date, time }, offset),
            Ambiguity::Fold(earlier, later) => (
                DateTime { date, time },
                match dis {
                    Disambiguate::Earlier => earlier,
                    Disambiguate::Later => later,
                    Disambiguate::Compatible => earlier,
                    Disambiguate::Raise => raise(
                        exc_repeated,
                        format!("{} {} is repeated in timezone '{}'", date, time, tz.key),
                    )?,
                },
            ),
            Ambiguity::Gap(later, earlier) => {
                let shift = later - earlier;
                let dt = DateTime { date, time };
                match dis {
                    Disambiguate::Earlier => (dt.small_shift_unchecked(-shift), earlier),
                    Disambiguate::Later => (dt.small_shift_unchecked(shift), later),
                    Disambiguate::Compatible => (dt.small_shift_unchecked(shift), later),
                    Disambiguate::Raise => raise(
                        exc_skipped,
                        format!("{} {} is skipped in timezone '{}'", date, time, tz.key),
                    )?,
                }
            }
        };
        dt.assume_tz(offset, tz)
            .ok_or_value_err("Resulting datetime is out of range")
    }

    /// Resolve a local time in a timezone, trying to reuse the given offset
    /// if it is valid. Otherwise, the "compatible" disambiguation is used.
    unsafe fn resolve_using_offset(
        date: Date,
        time: Time,
        tz: TzRef,
        offset: Offset,
    ) -> PyResult<Self> {
        use Ambiguity::*;
        match tz.ambiguity_for_local(date.timestamp_at(time)) {
            Unambiguous(offset_secs) => ZonedDateTime::new(date, time, offset_secs, tz),
            Fold(offset0, offset1) => ZonedDateTime::new(
                date,
                time,
                if offset == offset1 { offset1 } else { offset0 },
                tz,
            ),
            Gap(offset0, offset1) => {
                let (offset_secs, shift) = if offset == offset0 {
                    (offset0, offset0 - offset1)
                } else {
                    (offset1, offset1 - offset0)
                };
                DateTime { date, time }
                    .small_shift_unchecked(shift)
                    .assume_tz(offset_secs, tz)
            }
        }
        .ok_or_value_err("Resulting datetime is out of range")
    }

    pub(crate) const fn instant(self) -> Instant {
        Instant::from_datetime(self.date, self.time).shift_secs_unchecked(-self.offset_secs as i64)
    }

    pub(crate) const fn to_offset(self) -> OffsetDateTime {
        OffsetDateTime::new_unchecked(self.date, self.time, self.offset_secs)
    }

    pub(crate) const fn without_offset(self) -> DateTime {
        DateTime {
            date: self.date,
            time: self.time,
        }
    }

    #[allow(clippy::too_many_arguments)]
    pub(crate) unsafe fn shift(
        self,
        months: i32,
        days: i32,
        delta: TimeDelta,
        dis: Option<Disambiguate>,
        exc_repeated: *mut PyObject,
        exc_skipped: *mut PyObject,
    ) -> PyResult<Self> {
        let shifted_by_date = if months != 0 || days != 0 {
            let ZonedDateTime {
                date,
                time,
                tz,
                offset_secs,
            } = self;
            Self::resolve(
                date.shift(months, days)
                    .ok_or_value_err("Resulting date is out of range")?,
                time,
                tz,
                dis,
                offset_secs,
                exc_repeated,
                exc_skipped,
            )?
        } else {
            self
        };

        shifted_by_date
            .instant()
            .shift(delta)
            .ok_or_value_err("Instant is out of range")?
            .to_tz(self.tz)
            .ok_or_value_err("Resulting date is out of range")
    }
}

impl PyWrapped for ZonedDateTime {
    #[inline]
    unsafe fn to_obj(self, type_: *mut PyTypeObject) -> PyReturn {
        let obj = generic_alloc(type_, self)?;
        self.tz.incref();
        Ok(obj)
    }
}

impl DateTime {
    pub(crate) unsafe fn assume_tz(self, offset_secs: i32, tz: TzRef) -> Option<ZonedDateTime> {
        ZonedDateTime::new(self.date, self.time, offset_secs, tz)
    }

    pub(crate) unsafe fn assume_tz_unchecked(self, offset_secs: i32, tz: TzRef) -> ZonedDateTime {
        ZonedDateTime {
            date: self.date,
            time: self.time,
            offset_secs,
            tz,
        }
    }
}

impl Instant {
    pub(crate) unsafe fn to_tz(self, tz: TzRef) -> Option<ZonedDateTime> {
        let epoch = self.timestamp();
        println!("Epoch: {}", epoch);
        let offset = tz.offset_for_instant(epoch);
        println!("Offset: {}", offset);
        let local_epoch = epoch + i64::from(offset);
        println!("Local epoch: {}", local_epoch);
        if !(MIN_EPOCH..=MAX_EPOCH).contains(&local_epoch) {
            return None;
        }
        let date = Date::from_unix_days_unchecked((local_epoch / i64::from(S_PER_DAY)) as _);
        let time_secs = (local_epoch % i64::from(S_PER_DAY)) as i32;
        let time = Time {
            hour: (time_secs / 3600) as u8,
            minute: ((time_secs / 60) % 60) as u8,
            second: (time_secs % 60) as u8,
            nanos: self.subsec_nanos(),
        };
        Some(DateTime { date, time }.assume_tz_unchecked(offset, tz))
    }
}

impl Display for ZonedDateTime {
    fn fmt(&self, f: &mut Formatter<'_>) -> fmt::Result {
        let &ZonedDateTime {
            date,
            time,
            offset_secs,
            tz,
        } = self;
        write!(
            f,
            "{}T{}{}[{}]",
            date,
            time,
            offset_fmt(offset_secs),
            tz.key
        )
    }
}

unsafe fn __new__(cls: *mut PyTypeObject, args: *mut PyObject, kwargs: *mut PyObject) -> PyReturn {
    let &mut State {
        exc_repeated,
        exc_skipped,
        zoneinfo_notfound,
        ref mut tz_cache,
        ..
    } = State::for_type_mut(cls);
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

    if tz.is_null() {
        return raise_type_err("tz argument is required");
    }
    let tzref = tz_cache.py_get(tz, zoneinfo_notfound)?;
    let date = Date::from_longs(year, month, day).ok_or_value_err("Invalid date")?;
    let time =
        Time::from_longs(hour, minute, second, nanosecond).ok_or_value_err("Invalid time")?;
    let dis = if disambiguate.is_null() {
        Disambiguate::Compatible
    } else {
        Disambiguate::from_py(disambiguate)?
    };
    ZonedDateTime::resolve_using_disambiguate(date, time, tzref, dis, exc_repeated, exc_skipped)?
        .to_obj(cls)
}

unsafe extern "C" fn dealloc(slf: *mut PyObject) {
    ZonedDateTime::extract(slf)
        .tz
        .decref(|| &mut State::for_obj_mut(slf).tz_cache);
    generic_dealloc(slf)
}

unsafe fn __repr__(slf: *mut PyObject) -> PyReturn {
    let ZonedDateTime {
        date,
        time,
        offset_secs,
        tz,
    } = ZonedDateTime::extract(slf);
    format!(
        "ZonedDateTime({} {}{}[{}])",
        date,
        time,
        offset_fmt(offset_secs),
        tz.key
    )
    .to_py()
}

unsafe fn __str__(slf: *mut PyObject) -> PyReturn {
    format!("{}", ZonedDateTime::extract(slf)).to_py()
}

unsafe fn __richcmp__(a_obj: *mut PyObject, b_obj: *mut PyObject, op: c_int) -> PyReturn {
    let type_a = Py_TYPE(a_obj);
    let type_b = Py_TYPE(b_obj);
    let inst_a = ZonedDateTime::extract(a_obj).instant();
    let inst_b = if type_b == type_a {
        ZonedDateTime::extract(b_obj).instant()
    } else if type_b == State::for_type(type_a).instant_type {
        Instant::extract(b_obj)
    } else {
        return Ok(newref(Py_NotImplemented()));
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

unsafe extern "C" fn __hash__(slf: *mut PyObject) -> Py_hash_t {
    hashmask(ZonedDateTime::extract(slf).instant().pyhash())
}

#[inline]
unsafe fn _shift_operator(obj_a: *mut PyObject, obj_b: *mut PyObject, negate: bool) -> PyReturn {
    debug_assert_eq!(
        PyType_GetModule(Py_TYPE(obj_a)),
        PyType_GetModule(Py_TYPE(obj_b))
    );
    let type_a = Py_TYPE(obj_a);
    let type_b = Py_TYPE(obj_b);
    let &State {
        time_delta_type,
        date_delta_type,
        datetime_delta_type,
        exc_repeated,
        exc_skipped,
        ..
    } = State::for_type(type_a);

    let zdt = ZonedDateTime::extract(obj_a);
    let mut months = 0;
    let mut days = 0;
    let mut tdelta = TimeDelta::ZERO;

    if type_b == time_delta_type {
        tdelta = TimeDelta::extract(obj_b);
    } else if type_b == date_delta_type {
        let dd = DateDelta::extract(obj_b);
        months = dd.months;
        days = dd.days;
    } else if type_b == datetime_delta_type {
        let dtd = DateTimeDelta::extract(obj_b);
        months = dtd.ddelta.months;
        days = dtd.ddelta.days;
        tdelta = dtd.tdelta;
    } else {
        return Ok(newref(Py_NotImplemented()));
    };
    if negate {
        months = -months;
        days = -days;
        tdelta = -tdelta;
    };

    zdt.shift(months, days, tdelta, None, exc_repeated, exc_skipped)?
        .to_obj(type_a)
}

unsafe fn __add__(slf: *mut PyObject, arg: *mut PyObject) -> PyReturn {
    if PyType_GetModule(Py_TYPE(slf)) == PyType_GetModule(Py_TYPE(arg)) {
        _shift_operator(slf, arg, false)
    } else {
        Ok(newref(Py_NotImplemented()))
    }
}

unsafe fn __sub__(obj_a: *mut PyObject, obj_b: *mut PyObject) -> PyReturn {
    let type_a = Py_TYPE(obj_a);
    let type_b = Py_TYPE(obj_b);

    // Easy case: ZonedDT - ZonedDT
    let (inst_a, inst_b) = if type_a == type_b {
        (
            ZonedDateTime::extract(obj_a).instant(),
            ZonedDateTime::extract(obj_b).instant(),
        )
    // Other cases are more difficult, as they can be triggered
    // by reflexive operations with arbitrary types.
    // We need to eliminate them carefully.
    } else {
        let mod_a = PyType_GetModule(type_a);
        let mod_b = PyType_GetModule(type_b);
        if mod_a == mod_b {
            let inst_b = if type_b == State::for_mod(mod_a).instant_type {
                Instant::extract(obj_b)
            } else if type_b == State::for_mod(mod_a).offset_datetime_type
                || type_b == State::for_mod(mod_a).system_datetime_type
            {
                OffsetDateTime::extract(obj_b).instant()
            } else {
                return _shift_operator(obj_a, obj_b, true);
            };
            debug_assert_eq!(type_a, State::for_type(type_a).zoned_datetime_type);
            (ZonedDateTime::extract(obj_a).instant(), inst_b)
        } else {
            return Ok(newref(Py_NotImplemented()));
        }
    };
    inst_a
        .diff(inst_b)
        .to_obj(State::for_type(type_a).time_delta_type)
}

#[allow(static_mut_refs)]
static mut SLOTS: &[PyType_Slot] = &[
    slotmethod!(Py_tp_new, __new__),
    slotmethod!(Py_tp_str, __str__, 1),
    slotmethod!(Py_tp_repr, __repr__, 1),
    slotmethod!(Py_tp_richcompare, __richcmp__),
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

unsafe fn exact_eq(obj_a: *mut PyObject, obj_b: *mut PyObject) -> PyReturn {
    if Py_TYPE(obj_a) == Py_TYPE(obj_b) {
        (ZonedDateTime::extract(obj_a) == ZonedDateTime::extract(obj_b)).to_py()
    } else {
        raise_type_err(format!(
            "Argument must be ZonedDateTime, got {}",
            obj_b.repr()
        ))
    }
}

unsafe fn to_tz(slf: &mut PyObject, tz_obj: *mut PyObject) -> PyReturn {
    let cls = Py_TYPE(slf);
    let &mut State {
        zoneinfo_notfound,
        ref mut tz_cache,
        ..
    } = State::for_type_mut(cls);
    let tz_new = tz_cache.py_get(tz_obj, zoneinfo_notfound)?;
    ZonedDateTime::extract(slf)
        .instant()
        .to_tz(tz_new)
        .ok_or_value_err("Resulting datetime is out of range")?
        .to_obj(cls)
}

pub(crate) unsafe fn unpickle(module: &mut PyObject, args: &[*mut PyObject]) -> PyReturn {
    let &[data, tz_obj] = args else {
        raise_type_err("Invalid pickle data")?
    };
    let &mut State {
        zoned_datetime_type,
        zoneinfo_notfound,
        ref mut tz_cache,
        ..
    } = State::for_mod_mut(module);
    let mut packed = data.to_bytes()?.ok_or_type_err("Invalid pickle data")?;
    if packed.len() != 15 {
        raise_type_err("Invalid pickle data")?;
    }
    ZonedDateTime {
        date: Date {
            year: unpack_one!(packed, u16),
            month: unpack_one!(packed, u8),
            day: unpack_one!(packed, u8),
        },
        time: Time {
            hour: unpack_one!(packed, u8),
            minute: unpack_one!(packed, u8),
            second: unpack_one!(packed, u8),
            nanos: unpack_one!(packed, u32),
        },
        offset_secs: unpack_one!(packed, i32),
        tz: tz_cache.py_get(tz_obj, zoneinfo_notfound)?,
    }
    .to_obj(zoned_datetime_type)
}

unsafe fn py_datetime(slf: &mut PyObject, _: &mut PyObject) -> PyReturn {
    let zdt = ZonedDateTime::extract(slf);
    let DateTime {
        date: Date { year, month, day },
        time:
            Time {
                hour,
                minute,
                second,
                nanos,
            },
    } = zdt.without_offset().small_shift_unchecked(-zdt.offset_secs);
    let &State {
        py_api:
            &PyDateTime_CAPI {
                DateTime_FromDateAndTime,
                DateTimeType,
                ..
            },
        zoneinfo_type,
        ..
    } = State::for_obj(slf);
    let tz_key: &str = &zdt.tz.key;
    let zoneinfo = call1(zoneinfo_type, steal!(tz_key.to_py()?))?;
    defer_decref!(zoneinfo);
    methcall1(
        zoneinfo,
        "fromutc",
        steal!(DateTime_FromDateAndTime(
            year.into(),
            month.into(),
            day.into(),
            hour.into(),
            minute.into(),
            second.into(),
            (nanos / 1_000) as _,
            zoneinfo,
            DateTimeType,
        )),
    )
}

unsafe fn instant(slf: &mut PyObject, _: &mut PyObject) -> PyReturn {
    ZonedDateTime::extract(slf)
        .instant()
        .to_obj(State::for_obj(slf).instant_type)
}

unsafe fn to_fixed_offset(slf_obj: &mut PyObject, args: &[*mut PyObject]) -> PyReturn {
    let slf = ZonedDateTime::extract(slf_obj);
    let &State {
        offset_datetime_type,
        time_delta_type,
        ..
    } = State::for_obj(slf_obj);
    match *args {
        [] => OffsetDateTime::new_unchecked(slf.date, slf.time, slf.offset_secs)
            .to_obj(offset_datetime_type),
        [arg] => slf
            .instant()
            .to_offset(offset_datetime::extract_offset(arg, time_delta_type)?)
            .ok_or_value_err("Resulting local date is out of range")?
            .to_obj(offset_datetime_type),
        _ => raise_type_err("to_fixed_offset() takes at most 1 argument"),
    }
}

unsafe fn to_system_tz(slf: *mut PyObject, _: *mut PyObject) -> PyReturn {
    let &State {
        py_api,
        system_datetime_type,
        ..
    } = State::for_obj(slf);
    ZonedDateTime::extract(slf)
        .to_offset()
        .to_system_tz(py_api)?
        .to_obj(system_datetime_type)
}

unsafe fn date(slf: *mut PyObject, _: *mut PyObject) -> PyReturn {
    ZonedDateTime::extract(slf)
        .date
        .to_obj(State::for_obj(slf).date_type)
}

unsafe fn time(slf: *mut PyObject, _: *mut PyObject) -> PyReturn {
    ZonedDateTime::extract(slf)
        .time
        .to_obj(State::for_obj(slf).time_type)
}

unsafe fn replace_date(
    slf: *mut PyObject,
    cls: *mut PyTypeObject,
    args: &[*mut PyObject],
    kwargs: &mut KwargIter,
) -> PyReturn {
    let &State {
        date_type,
        str_disambiguate,
        exc_skipped,
        exc_repeated,
        ..
    } = State::for_obj(slf);

    let &[arg] = args else {
        raise_type_err(format!(
            "replace_date() takes exactly 1 argument but {} were given",
            args.len()
        ))?
    };

    let dis = Disambiguate::from_only_kwarg(kwargs, str_disambiguate, "replace_date")?;
    let ZonedDateTime {
        time,
        tz,
        offset_secs,
        ..
    } = ZonedDateTime::extract(slf);
    if Py_TYPE(arg) == date_type {
        ZonedDateTime::resolve(
            Date::extract(arg),
            time,
            tz,
            dis,
            offset_secs,
            exc_repeated,
            exc_skipped,
        )?
        .to_obj(cls)
    } else {
        raise_type_err("date must be a whenever.Date instance")
    }
}

unsafe fn replace_time(
    slf: *mut PyObject,
    cls: *mut PyTypeObject,
    args: &[*mut PyObject],
    kwargs: &mut KwargIter,
) -> PyReturn {
    let &State {
        time_type,
        str_disambiguate,
        exc_skipped,
        exc_repeated,
        ..
    } = State::for_obj(slf);

    let &[arg] = args else {
        raise_type_err(format!(
            "replace_time() takes exactly 1 argument but {} were given",
            args.len()
        ))?
    };

    let dis = Disambiguate::from_only_kwarg(kwargs, str_disambiguate, "replace_time")?;
    let ZonedDateTime {
        date,
        tz,
        offset_secs,
        ..
    } = ZonedDateTime::extract(slf);
    if Py_TYPE(arg) == time_type {
        ZonedDateTime::resolve(
            date,
            Time::extract(arg),
            tz,
            dis,
            offset_secs,
            exc_repeated,
            exc_skipped,
        )?
        .to_obj(cls)
    } else {
        raise_type_err("time must be a whenever.Time instance")
    }
}

unsafe fn format_common_iso(slf: *mut PyObject, _: *mut PyObject) -> PyReturn {
    __str__(slf)
}

unsafe fn replace(
    slf: *mut PyObject,
    cls: *mut PyTypeObject,
    args: &[*mut PyObject],
    kwargs: &mut KwargIter,
) -> PyReturn {
    if !args.is_empty() {
        raise_type_err("replace() takes no positional arguments")?;
    }
    let state = State::for_type(cls);
    let &State {
        exc_repeated,
        exc_skipped,
        str_tz,
        str_disambiguate,
        zoneinfo_notfound,
        ..
    } = state;
    // TODO: avoid two state lookups
    let tz_cache = &mut State::for_type_mut(cls).tz_cache;
    let ZonedDateTime {
        date,
        time,
        mut tz,
        offset_secs,
    } = ZonedDateTime::extract(slf);
    let mut year = date.year.into();
    let mut month = date.month.into();
    let mut day = date.day.into();
    let mut hour = time.hour.into();
    let mut minute = time.minute.into();
    let mut second = time.second.into();
    let mut nanos = time.nanos as _;
    let mut dis = None;

    handle_kwargs("replace", kwargs, |key, value, eq| {
        if eq(key, str_tz) {
            let tz_new = tz_cache.py_get(value, zoneinfo_notfound)?;
            // If we change timezones, forget about trying to preserve the offset.
            // Just use compatible disambiguation.
            if tz_new != tz {
                dis.get_or_insert(Disambiguate::Compatible);
            };
            tz = tz_new;
        } else if eq(key, str_disambiguate) {
            dis = Some(Disambiguate::from_py(value)?);
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

    let date = Date::from_longs(year, month, day).ok_or_value_err("Invalid date")?;
    let time = Time::from_longs(hour, minute, second, nanos).ok_or_value_err("Invalid time")?;
    ZonedDateTime::resolve(date, time, tz, dis, offset_secs, exc_repeated, exc_skipped)?.to_obj(cls)
}

unsafe fn now(cls: *mut PyObject, tz_obj: *mut PyObject) -> PyReturn {
    let state = State::for_type_mut(cls.cast());
    let &mut State {
        ref mut tz_cache,
        zoneinfo_notfound,
        ..
    } = state;
    let tz = tz_cache.py_get(tz_obj, zoneinfo_notfound)?;
    let (timestamp, subsec) = state.time_ns()?;
    // TODO: going through Instant incurrs a performance penalty
    Instant::from_timestamp_and_nanos(timestamp, subsec)
        .ok_or_value_err("Current datetime is out of range")? // UTC out of range
        .to_tz(tz)
        .ok_or_value_err("Current datetime is out of range")? // local date out of range
        .to_obj(cls.cast())
}

unsafe fn from_py_datetime(cls: *mut PyObject, dt: *mut PyObject) -> PyReturn {
    let &mut State {
        zoneinfo_type,
        zoneinfo_notfound,
        ref mut tz_cache,
        ..
    } = State::for_type_mut(cls.cast());
    if PyDateTime_Check(dt) == 0 {
        raise_type_err("Argument must be a datetime.datetime instance")?;
    }
    let tzinfo = borrow_dt_tzinfo(dt);

    // NOTE: it has to be exactly a `ZoneInfo`, since
    // we only know how to handle that type.  Even subclasses could
    // theoretically break the assumptions we make.
    if Py_TYPE(tzinfo) != zoneinfo_type.cast() {
        raise_value_err(format!(
            "tzinfo must be of type ZoneInfo (exactly), got {}",
            (Py_TYPE(tzinfo) as *mut PyObject).repr()
        ))?;
    }

    let tz_obj = PyObject_GetAttrString(tzinfo, c"key".as_ptr()).as_result()?;
    let tz = tz_cache.py_get(tz_obj, zoneinfo_notfound)?;

    // TODO: tz offsets could theoretically disagree!

    ZonedDateTime::new(
        Date {
            year: PyDateTime_GET_YEAR(dt) as _,
            month: PyDateTime_GET_MONTH(dt) as _,
            day: PyDateTime_GET_DAY(dt) as _,
        },
        Time {
            hour: PyDateTime_DATE_GET_HOUR(dt) as _,
            minute: PyDateTime_DATE_GET_MINUTE(dt) as _,
            second: PyDateTime_DATE_GET_SECOND(dt) as _,
            nanos: PyDateTime_DATE_GET_MICROSECOND(dt) as u32 * 1_000,
        },
        offset_from_py_dt(dt)?,
        tz,
    )
    .ok_or_value_err("Resulting datetime is out of range")?
    .to_obj(cls.cast())
}

unsafe fn local(slf: *mut PyObject, _: *mut PyObject) -> PyReturn {
    ZonedDateTime::extract(slf)
        .without_offset()
        .to_obj(State::for_obj(slf).local_datetime_type)
}

unsafe fn timestamp(slf: *mut PyObject, _: *mut PyObject) -> PyReturn {
    ZonedDateTime::extract(slf).instant().timestamp().to_py()
}

unsafe fn timestamp_millis(slf: *mut PyObject, _: *mut PyObject) -> PyReturn {
    ZonedDateTime::extract(slf)
        .instant()
        .timestamp_millis()
        .to_py()
}

unsafe fn timestamp_nanos(slf: *mut PyObject, _: *mut PyObject) -> PyReturn {
    ZonedDateTime::extract(slf)
        .instant()
        .timestamp_nanos()
        .to_py()
}

unsafe fn __reduce__(slf: *mut PyObject, _: *mut PyObject) -> PyReturn {
    let ZonedDateTime {
        date: Date { year, month, day },
        time:
            Time {
                hour,
                minute,
                second,
                nanos,
            },
        offset_secs,
        tz,
    } = ZonedDateTime::extract(slf);
    let data = pack![year, month, day, hour, minute, second, nanos, offset_secs];
    let tz_key: &str = &tz.key;
    (
        State::for_obj(slf).unpickle_zoned_datetime,
        steal!((steal!(data.to_py()?), steal!(tz_key.to_py()?),).to_py()?),
    )
        .to_py()
}

// checks the args comply with (ts, /, *, tz: str)
#[inline]
unsafe fn check_from_timestamp_args_return_tz(
    args: &[*mut PyObject],
    kwargs: &mut KwargIter,
    &mut State {
        ref mut tz_cache,
        zoneinfo_notfound,
        str_tz,
        ..
    }: &mut State,
    fname: &str,
) -> PyResult<TzRef> {
    match (args, kwargs.next()) {
        (&[_], Some((key, value))) if kwargs.len() == 1 => {
            if key.kwarg_eq(str_tz) {
                tz_cache.py_get(value, zoneinfo_notfound)
            } else {
                raise_type_err(format!(
                    "{}() got an unexpected keyword argument {}",
                    fname,
                    key.repr()
                ))
            }
        }
        (&[_], None) => raise_type_err(format!(
            "{}() missing 1 required keyword-only argument: 'tz'",
            fname
        )),
        (&[], _) => raise_type_err(format!(
            "{}() missing 1 required positional argument",
            fname
        )),
        _ => raise_type_err(format!(
            "{}() expected 2 arguments, got {}",
            fname,
            args.len() + (kwargs.len() as usize)
        )),
    }
}

unsafe fn from_timestamp(
    _: *mut PyObject,
    cls: *mut PyTypeObject,
    args: &[*mut PyObject],
    kwargs: &mut KwargIter,
) -> PyReturn {
    let state = &mut State::for_type_mut(cls);
    let tz = check_from_timestamp_args_return_tz(args, kwargs, state, "from_timestamp")?;

    match args[0].to_i64()? {
        Some(ts) => Instant::from_timestamp(ts),
        None => Instant::from_timestamp_f64(
            args[0]
                .to_f64()?
                .ok_or_type_err("Timestamp must be an integer or float")?,
        ),
    }
    .ok_or_value_err("timestamp is out of range")?
    .to_tz(tz)
    .ok_or_value_err("Resulting date out of range")?
    .to_obj(cls)
}

unsafe fn from_timestamp_millis(
    _: *mut PyObject,
    cls: *mut PyTypeObject,
    args: &[*mut PyObject],
    kwargs: &mut KwargIter,
) -> PyReturn {
    let state = &mut State::for_type_mut(cls);
    let tz = check_from_timestamp_args_return_tz(args, kwargs, state, "from_timestamp_millis")?;
    Instant::from_timestamp_millis(
        args[0]
            .to_i64()?
            .ok_or_type_err("timestamp must be an integer")?,
    )
    // TODO: fast check for both ranges!
    .ok_or_value_err("timestamp is out of range")?
    .to_tz(tz)
    .ok_or_value_err("Resulting date out of range")?
    .to_obj(cls)
}

unsafe fn from_timestamp_nanos(
    _: *mut PyObject,
    cls: *mut PyTypeObject,
    args: &[*mut PyObject],
    kwargs: &mut KwargIter,
) -> PyReturn {
    let state = &mut State::for_type_mut(cls);
    let tz = check_from_timestamp_args_return_tz(args, kwargs, state, "from_timestamp_nanos")?;
    Instant::from_timestamp_nanos(
        args[0]
            .to_i128()?
            .ok_or_type_err("timestamp must be an integer")?,
    )
    .ok_or_value_err("timestamp is out of range")?
    .to_tz(tz)
    .ok_or_value_err("Resulting date out of range")?
    .to_obj(cls)
}

unsafe fn is_ambiguous(slf: *mut PyObject, _: *mut PyObject) -> PyReturn {
    let ZonedDateTime { date, time, tz, .. } = ZonedDateTime::extract(slf);
    matches!(
        tz.ambiguity_for_local(
            i64::from(date.unix_days()) * i64::from(S_PER_DAY)
                + i64::from(time.total_seconds() as i32)
        ),
        Ambiguity::Fold(_, _)
    )
    .to_py()
}

// parse ±HH:MM[:SS] (consuming as much as possible of the input)
fn parse_offset_partial(s: &mut &[u8]) -> Option<i32> {
    debug_assert!(!s.is_empty());
    let sign = match s[0] {
        b'+' => 1,
        b'-' => -1,
        b'Z' => {
            *s = &s[1..];
            return Some(0);
        }
        _ => return None,
    };
    if s[3] != b':' {
        return None;
    }
    // the HH:MM part
    // FUTURE: technically, this eliminates 2x:00 offsets. There
    // are no such offsets in the IANA database, but may be possible...
    let secs = (parse_digit_max(s, 1, b'1')? * 10 + parse_digit(s, 2)?) as i32 * 3600
        + (parse_digit_max(s, 4, b'5')? * 10 + parse_digit(s, 5)?) as i32 * 60;
    // the optional seconds part
    match s.get(6) {
        Some(b':') => {
            if s.len() > 8 {
                let result = Some(
                    secs + parse_digit_max(s, 7, b'5')? as i32 * 10 + parse_digit(s, 8)? as i32,
                );
                *s = &s[9..];
                result
            } else {
                None
            }
        }
        _ => {
            *s = &s[6..];
            Some(secs)
        }
    }
    .map(|s| sign * s)
}

unsafe fn parse_common_iso(cls: *mut PyObject, s_obj: *mut PyObject) -> PyReturn {
    let s = &mut s_obj.to_utf8()?.ok_or_type_err("Argument must be string")?;
    let errmsg = || format!("Invalid format: {}", s_obj.repr());
    // at least: "YYYY-MM-DD HH:MM:SSZ[_]"
    if s.len() < 23 || s[10] != b'T' {
        raise_value_err(errmsg())?;
    }
    let date = Date::parse_partial(s).ok_or_else_value_err(errmsg)?;
    *s = &s[1..]; // skip the separator
    let time = Time::parse_partial(s).ok_or_else_value_err(errmsg)?;

    // at least "Z[_]" remains
    if s.len() < 4 {
        raise_value_err(errmsg())?;
    }
    let offset_secs = parse_offset_partial(s).ok_or_else_value_err(errmsg)?;
    if s.len() < 3 || s.len() > 255 || s[0] != b'[' || s[s.len() - 1] != b']' || !s.is_ascii() {
        raise_value_err(errmsg())?;
    }
    let &mut State {
        exc_invalid_offset,
        zoneinfo_notfound,
        ref mut tz_cache,
        ..
    } = State::for_type_mut(cls.cast());
    let tz = tz_cache
        .get(std::str::from_utf8_unchecked(&s[1..s.len() - 1]))
        .ok_or_else_raise(zoneinfo_notfound, || {
            format!(
                "No time zone found with key {}",
                std::str::from_utf8_unchecked(&s[1..s.len() - 1])
            )
        })?;

    let offset_is_valid = match tz.ambiguity_for_local(date.timestamp_at(time)) {
        Ambiguity::Unambiguous(o) => o == offset_secs,
        Ambiguity::Gap(o1, o2) | Ambiguity::Fold(o1, o2) => o1 == offset_secs || o2 == offset_secs,
    };
    if offset_is_valid {
        ZonedDateTime::new(date, time, offset_secs, tz)
            .ok_or_value_err("Datetime out of range")?
            .to_obj(cls.cast())
    } else {
        raise(
            exc_invalid_offset,
            format!("Invalid offset for timezone {}", tz.key),
        )
    }
}

unsafe fn add(
    slf: *mut PyObject,
    cls: *mut PyTypeObject,
    args: &[*mut PyObject],
    kwargs: &mut KwargIter,
) -> PyReturn {
    _shift_method(slf, cls, args, kwargs, false)
}

unsafe fn subtract(
    slf: *mut PyObject,
    cls: *mut PyTypeObject,
    args: &[*mut PyObject],
    kwargs: &mut KwargIter,
) -> PyReturn {
    _shift_method(slf, cls, args, kwargs, true)
}

#[inline]
unsafe fn _shift_method(
    slf: *mut PyObject,
    cls: *mut PyTypeObject,
    args: &[*mut PyObject],
    kwargs: &mut KwargIter,
    negate: bool,
) -> PyReturn {
    let fname = if negate { "subtract" } else { "add" };
    let state = State::for_type(cls);
    let mut dis = None;
    let mut months = 0;
    let mut days = 0;
    let mut tdelta = TimeDelta::ZERO;

    match *args {
        [arg] => {
            match kwargs.next() {
                Some((key, value)) if kwargs.len() == 1 && key.kwarg_eq(state.str_disambiguate) => {
                    dis = Some(Disambiguate::from_py(value)?)
                }
                None => {}
                _ => raise_type_err(format!(
                    "{}() can't mix positional and keyword arguments",
                    fname
                ))?,
            };
            if Py_TYPE(arg) == state.time_delta_type {
                tdelta = TimeDelta::extract(arg);
            } else if Py_TYPE(arg) == state.date_delta_type {
                let dd = DateDelta::extract(arg);
                months = dd.months;
                days = dd.days;
            } else if Py_TYPE(arg) == state.datetime_delta_type {
                let dtd = DateTimeDelta::extract(arg);
                months = dtd.ddelta.months;
                days = dtd.ddelta.days;
                tdelta = dtd.tdelta;
            } else {
                raise_type_err(format!("{}() argument must be a delta", fname))?
            }
        }
        [] => {
            let mut nanos: i128 = 0;
            handle_kwargs(fname, kwargs, |key, value, eq| {
                if eq(key, state.str_disambiguate) {
                    dis = Some(Disambiguate::from_py(value)?);
                    Ok(true)
                } else {
                    set_units_from_kwargs(key, value, &mut months, &mut days, &mut nanos, state, eq)
                }
            })?;
            tdelta = TimeDelta::from_nanos(nanos).ok_or_value_err("Total duration too large")?;
        }
        _ => raise_type_err(format!(
            "{}() takes at most 1 positional argument, got {}",
            fname,
            args.len()
        ))?,
    }
    if negate {
        months = -months;
        days = -days;
        tdelta = -tdelta;
    }

    ZonedDateTime::extract(slf)
        .shift(
            months,
            days,
            tdelta,
            dis,
            state.exc_repeated,
            state.exc_skipped,
        )?
        .to_obj(cls)
}

unsafe fn difference(obj_a: *mut PyObject, obj_b: *mut PyObject) -> PyReturn {
    let type_b = Py_TYPE(obj_b);
    let type_a = Py_TYPE(obj_a);
    let state = State::for_type(type_a);
    let inst_a = ZonedDateTime::extract(obj_a).instant();
    let inst_b = if type_b == Py_TYPE(obj_a) {
        ZonedDateTime::extract(obj_b).instant()
    } else if type_b == state.instant_type {
        Instant::extract(obj_b)
    } else if type_b == state.system_datetime_type || type_b == state.offset_datetime_type {
        OffsetDateTime::extract(obj_b).instant()
    } else {
        raise_type_err(
            "difference() argument must be an OffsetDateTime, 
             Instant, ZonedDateTime, or SystemDateTime",
        )?
    };
    inst_a.diff(inst_b).to_obj(state.time_delta_type)
}

unsafe fn start_of_day(slf: *mut PyObject, _: *mut PyObject) -> PyReturn {
    let ZonedDateTime { date, tz, .. } = ZonedDateTime::extract(slf);
    let &State {
        exc_repeated,
        exc_skipped,
        ..
    } = State::for_obj(slf);
    ZonedDateTime::resolve_using_disambiguate(
        date,
        MIDNIGHT,
        tz,
        Disambiguate::Compatible,
        exc_repeated,
        exc_skipped,
    )?
    .to_obj(Py_TYPE(slf))
}

unsafe fn day_length(slf: *mut PyObject, _: *mut PyObject) -> PyReturn {
    let ZonedDateTime { date, tz, .. } = ZonedDateTime::extract(slf);
    let &State {
        exc_repeated,
        exc_skipped,
        time_delta_type,
        ..
    } = State::for_obj(slf);
    let start_of_day = ZonedDateTime::resolve_using_disambiguate(
        date,
        MIDNIGHT,
        tz,
        Disambiguate::Compatible,
        exc_repeated,
        exc_skipped,
    )?
    .instant();
    let start_of_next_day = ZonedDateTime::resolve_using_disambiguate(
        date.increment(),
        MIDNIGHT,
        tz,
        Disambiguate::Compatible,
        exc_repeated,
        exc_skipped,
    )?
    .instant();
    start_of_next_day.diff(start_of_day).to_obj(time_delta_type)
}

unsafe fn round(
    slf: *mut PyObject,
    cls: *mut PyTypeObject,
    args: &[*mut PyObject],
    kwargs: &mut KwargIter,
) -> PyReturn {
    let state = State::for_type(cls);
    let (unit, increment, mode) = round::parse_args(state, args, kwargs, false, false)?;

    match unit {
        round::Unit::Day => _round_day(slf, state, mode),
        _ => {
            let ZonedDateTime {
                mut date,
                time,
                offset_secs,
                tz,
            } = ZonedDateTime::extract(slf);
            let (time_rounded, next_day) = time.round(increment as u64, mode);
            if next_day == 1 {
                if date != MAX_DATE {
                    date = date.increment();
                } else {
                    raise_value_err("Resulting datetime out of range")?
                }
            };
            ZonedDateTime::resolve_using_offset(date, time_rounded, tz, offset_secs)
        }
    }?
    .to_obj(cls)
}

unsafe fn _round_day(
    slf: *mut PyObject,
    state: &State,
    mode: round::Mode,
) -> PyResult<ZonedDateTime> {
    let ZonedDateTime { date, time, tz, .. } = ZonedDateTime::extract(slf);
    let &State {
        exc_repeated,
        exc_skipped,
        ..
    } = state;
    let get_floor = || {
        ZonedDateTime::resolve_using_disambiguate(
            date,
            MIDNIGHT,
            tz,
            Disambiguate::Compatible,
            exc_repeated,
            exc_skipped,
        )
    };
    let get_ceil = || {
        ZonedDateTime::resolve_using_disambiguate(
            date.increment(),
            MIDNIGHT,
            tz,
            Disambiguate::Compatible,
            exc_repeated,
            exc_skipped,
        )
    };
    match mode {
        round::Mode::Ceil => get_ceil(),
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

static mut METHODS: &[PyMethodDef] = &[
    method!(identity2 named "__copy__", c""),
    method!(identity2 named "__deepcopy__", c"", METH_O),
    method!(__reduce__, c""),
    method!(to_tz, doc::KNOWSINSTANT_TO_TZ, METH_O),
    method!(to_system_tz, doc::KNOWSINSTANT_TO_SYSTEM_TZ),
    method_vararg!(to_fixed_offset, doc::KNOWSINSTANT_TO_FIXED_OFFSET),
    method!(exact_eq, doc::KNOWSINSTANT_EXACT_EQ, METH_O),
    method!(py_datetime, doc::BASICCONVERSIONS_PY_DATETIME),
    method!(instant, doc::KNOWSINSTANTANDLOCAL_INSTANT),
    method!(local, doc::KNOWSINSTANTANDLOCAL_LOCAL),
    method!(date, doc::KNOWSLOCAL_DATE),
    method!(time, doc::KNOWSLOCAL_TIME),
    method!(format_common_iso, doc::ZONEDDATETIME_FORMAT_COMMON_ISO),
    method!(
        parse_common_iso,
        doc::ZONEDDATETIME_PARSE_COMMON_ISO,
        METH_O | METH_CLASS
    ),
    method!(now, doc::ZONEDDATETIME_NOW, METH_O | METH_CLASS),
    method!(
        from_py_datetime,
        doc::ZONEDDATETIME_FROM_PY_DATETIME,
        METH_O | METH_CLASS
    ),
    method!(timestamp, doc::KNOWSINSTANT_TIMESTAMP),
    method!(timestamp_millis, doc::KNOWSINSTANT_TIMESTAMP_MILLIS),
    method!(timestamp_nanos, doc::KNOWSINSTANT_TIMESTAMP_NANOS),
    method!(is_ambiguous, doc::ZONEDDATETIME_IS_AMBIGUOUS),
    method_kwargs!(
        from_timestamp,
        doc::ZONEDDATETIME_FROM_TIMESTAMP,
        METH_CLASS
    ),
    method_kwargs!(
        from_timestamp_millis,
        doc::ZONEDDATETIME_FROM_TIMESTAMP_MILLIS,
        METH_CLASS
    ),
    method_kwargs!(
        from_timestamp_nanos,
        doc::ZONEDDATETIME_FROM_TIMESTAMP_NANOS,
        METH_CLASS
    ),
    method_kwargs!(replace, doc::ZONEDDATETIME_REPLACE),
    method_kwargs!(replace_date, doc::ZONEDDATETIME_REPLACE_DATE),
    method_kwargs!(replace_time, doc::ZONEDDATETIME_REPLACE_TIME),
    method_kwargs!(add, doc::ZONEDDATETIME_ADD),
    method_kwargs!(subtract, doc::ZONEDDATETIME_SUBTRACT),
    method!(difference, doc::KNOWSINSTANT_DIFFERENCE, METH_O),
    method!(start_of_day, doc::ZONEDDATETIME_START_OF_DAY),
    method!(day_length, doc::ZONEDDATETIME_DAY_LENGTH),
    method_kwargs!(round, doc::ZONEDDATETIME_ROUND),
    PyMethodDef::zeroed(),
];

unsafe fn get_year(slf: *mut PyObject) -> PyReturn {
    ZonedDateTime::extract(slf).date.year.to_py()
}

unsafe fn get_month(slf: *mut PyObject) -> PyReturn {
    ZonedDateTime::extract(slf).date.month.to_py()
}

unsafe fn get_day(slf: *mut PyObject) -> PyReturn {
    ZonedDateTime::extract(slf).date.day.to_py()
}

unsafe fn get_hour(slf: *mut PyObject) -> PyReturn {
    ZonedDateTime::extract(slf).time.hour.to_py()
}

unsafe fn get_minute(slf: *mut PyObject) -> PyReturn {
    ZonedDateTime::extract(slf).time.minute.to_py()
}

unsafe fn get_second(slf: *mut PyObject) -> PyReturn {
    ZonedDateTime::extract(slf).time.second.to_py()
}

unsafe fn get_nanos(slf: *mut PyObject) -> PyReturn {
    ZonedDateTime::extract(slf).time.nanos.to_py()
}

unsafe fn get_tz(slf: *mut PyObject) -> PyReturn {
    let key: &str = &ZonedDateTime::extract(slf).tz.key;
    key.to_py()
}

unsafe fn get_offset(slf: *mut PyObject) -> PyReturn {
    time_delta::TimeDelta::from_secs_unchecked(ZonedDateTime::extract(slf).offset_secs as i64)
        .to_obj(State::for_obj(slf).time_delta_type)
}

static mut GETSETTERS: &[PyGetSetDef] = &[
    getter!(get_year named "year", "The year component"),
    getter!(get_month named "month", "The month component"),
    getter!(get_day named "day", "The day component"),
    getter!(get_hour named "hour", "The hour component"),
    getter!(get_minute named "minute", "The minute component"),
    getter!(get_second named "second", "The second component"),
    getter!(get_nanos named "nanosecond", "The nanosecond component"),
    getter!(get_tz named "tz", "The tz ID"),
    getter!(get_offset named "offset", "The offset from UTC"),
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
