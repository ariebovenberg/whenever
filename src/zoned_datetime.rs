use core::ffi::{c_int, c_long, c_void, CStr};
use core::{mem, ptr::null_mut as NULL};
use pyo3_ffi::*;
use std::fmt::{self, Display, Formatter};

use crate::common::*;
use crate::datetime_delta::set_units_from_kwargs;
use crate::local_datetime::set_components_from_kwargs;
use crate::{
    date::Date,
    date_delta::DateDelta,
    datetime_delta::DateTimeDelta,
    instant::{Instant, MAX_INSTANT, MIN_INSTANT},
    local_datetime::DateTime,
    offset_datetime::{self, OffsetDateTime},
    time::Time,
    time_delta::{self, TimeDelta},
    State,
};

#[derive(Debug, Eq, PartialEq, Ord, PartialOrd, Copy, Clone)]
pub(crate) struct ZonedDateTime {
    date: Date,
    time: Time,
    offset_secs: i32,
    zoneinfo: *mut PyObject,
}

pub(crate) const SINGLETONS: &[(&CStr, ZonedDateTime); 0] = &[];

impl ZonedDateTime {
    pub(crate) unsafe fn new(
        date: Date,
        time: Time,
        offset_secs: i32,
        zoneinfo: *mut PyObject,
    ) -> Option<ZonedDateTime> {
        let ordinal_secs = i64::from(date.ord()) * i64::from(S_PER_DAY)
            + i64::from(time.total_seconds() - offset_secs);
        (MIN_INSTANT..=MAX_INSTANT)
            .contains(&ordinal_secs)
            .then_some(Self {
                date,
                time,
                offset_secs,
                zoneinfo,
            })
    }

    pub(crate) unsafe fn from_local(
        py_api: &PyDateTime_CAPI,
        date: Date,
        time: Time,
        zoneinfo: *mut PyObject,
        dis: Disambiguate,
    ) -> PyResult<Result<Self, Ambiguity>> {
        use Disambiguate::*;
        use OffsetResult::*;
        Ok(Ok(
            match OffsetResult::for_tz(py_api, date, time, zoneinfo)? {
                Unambiguous(offset_secs) => ZonedDateTime::new(date, time, offset_secs, zoneinfo),
                Fold(offset0, offset1) => {
                    let offset_secs = match dis {
                        Compatible | Earlier => offset0,
                        Later => offset1,
                        Raise => return Ok(Err(Ambiguity::Fold)),
                    };
                    ZonedDateTime::new(date, time, offset_secs, zoneinfo)
                }
                Gap(offset0, offset1) => {
                    let (offset_secs, shift) = match dis {
                        Compatible | Later => (offset1, offset1 - offset0),
                        Earlier => (offset0, offset0 - offset1),
                        Raise => return Ok(Err(Ambiguity::Gap)),
                    };
                    DateTime { date, time }
                        .small_shift_unchecked(shift)
                        .with_tz(offset_secs, zoneinfo)
                }
            }
            .ok_or_value_err("Resulting datetime is out of range")?,
        ))
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
}

impl DateTime {
    pub(crate) unsafe fn with_tz(
        self,
        offset_secs: i32,
        zoneinfo: *mut PyObject,
    ) -> Option<ZonedDateTime> {
        ZonedDateTime::new(self.date, self.time, offset_secs, zoneinfo)
    }
}

impl Instant {
    pub(crate) unsafe fn to_tz(
        self,
        &PyDateTime_CAPI {
            DateTime_FromTimestamp,
            DateTimeType,
            ..
        }: &PyDateTime_CAPI,
        zoneinfo: *mut PyObject,
    ) -> PyResult<ZonedDateTime> {
        // FUTURE: compare performance with alternative methods
        let dt = DateTime_FromTimestamp(
            DateTimeType,
            steal!((steal!(self.timestamp().to_py()?), zoneinfo).to_py()?),
            NULL(),
        )
        .as_result()?;
        defer_decref!(dt);

        // Don't need to use the checked constructor since we know
        // the UTC datetime is valid.
        Ok(ZonedDateTime {
            date: Date {
                year: PyDateTime_GET_YEAR(dt) as u16,
                month: PyDateTime_GET_MONTH(dt) as u8,
                day: PyDateTime_GET_DAY(dt) as u8,
            },
            time: Time {
                hour: PyDateTime_DATE_GET_HOUR(dt) as u8,
                minute: PyDateTime_DATE_GET_MINUTE(dt) as u8,
                second: PyDateTime_DATE_GET_SECOND(dt) as u8,
                nanos: self.subsec_nanos(),
            },
            offset_secs: offset_from_py_dt(dt)?,
            zoneinfo,
        })
    }
}

impl PyWrapped for ZonedDateTime {
    #[inline]
    unsafe fn to_obj(self, type_: *mut PyTypeObject) -> PyReturn {
        generic_alloc(type_, self).map(|o| {
            Py_INCREF(self.zoneinfo);
            o
        })
    }
}

impl Display for ZonedDateTime {
    fn fmt(&self, f: &mut Formatter<'_>) -> fmt::Result {
        let &ZonedDateTime {
            date,
            time,
            offset_secs,
            zoneinfo,
        } = self;
        write!(
            f,
            "{}T{}{}[{}]",
            date,
            time,
            offset_fmt(offset_secs),
            unsafe { zoneinfo_key(zoneinfo) }
        )
    }
}

unsafe fn zoneinfo_key(zoneinfo: *mut PyObject) -> String {
    let key_obj = PyObject_GetAttrString(zoneinfo, c"key".as_ptr());
    defer_decref!(key_obj);
    match key_obj.to_str() {
        Ok(Some(s)) => s,
        _ => "???",
    }
    .to_string()
}

unsafe fn __new__(cls: *mut PyTypeObject, args: *mut PyObject, kwargs: *mut PyObject) -> PyReturn {
    let &State {
        zoneinfo_type,
        py_api,
        exc_repeated,
        exc_skipped,
        str_raise,
        ..
    } = State::for_type(cls);
    let mut year: c_long = 0;
    let mut month: c_long = 0;
    let mut day: c_long = 0;
    let mut hour: c_long = 0;
    let mut minute: c_long = 0;
    let mut second: c_long = 0;
    let mut nanos: c_long = 0;
    let mut tz: *mut PyObject = NULL();
    let mut disambiguate: *mut PyObject = str_raise;

    // OPTIMIZE: parse them manually, which is more efficient
    if PyArg_ParseTupleAndKeywords(
        args,
        kwargs,
        c"lll|lll$lUU:ZonedDateTime".as_ptr(),
        vec![
            c"year".as_ptr() as *mut _,
            c"month".as_ptr() as *mut _,
            c"day".as_ptr() as *mut _,
            c"hour".as_ptr() as *mut _,
            c"minute".as_ptr() as *mut _,
            c"second".as_ptr() as *mut _,
            c"nanosecond".as_ptr() as *mut _,
            c"tz".as_ptr() as *mut _,
            c"disambiguate".as_ptr() as *mut _,
            NULL(),
        ]
        .as_mut_ptr(),
        &mut year,
        &mut month,
        &mut day,
        &mut hour,
        &mut minute,
        &mut second,
        &mut nanos,
        &mut tz,
        &mut disambiguate,
    ) == 0
    {
        return Err(py_err!());
    }

    if tz.is_null() {
        return Err(type_err!("tz argument is required"));
    }
    let zoneinfo = call1(zoneinfo_type, tz)?;
    defer_decref!(zoneinfo);

    let date = Date::from_longs(year, month, day).ok_or_value_err("Invalid date")?;
    let time = Time::from_longs(hour, minute, second, nanos).ok_or_value_err("Invalid time")?;
    let dis = Disambiguate::from_py(disambiguate)?;
    ZonedDateTime::from_local(py_api, date, time, zoneinfo, dis)?
        .map_err(|a| match a {
            Ambiguity::Fold => py_err!(
                exc_repeated,
                "{} {} is repeated in timezone {}",
                date,
                time,
                tz.repr()
            ),
            Ambiguity::Gap => py_err!(
                exc_skipped,
                "{} {} is skipped in timezone {}",
                date,
                time,
                tz.repr()
            ),
        })?
        .to_obj(cls)
}

unsafe extern "C" fn dealloc(slf: *mut PyObject) {
    // We assume that no circular references are possible between
    // ZonedDateTime and ZoneInfo objects:
    // They are both immutable types and guaranteed not to be subclasses.
    // FUTURE: get 100% certainty about this.
    Py_DECREF(ZonedDateTime::extract(slf).zoneinfo);
    generic_dealloc(slf)
}

unsafe fn __repr__(slf: *mut PyObject) -> PyReturn {
    let ZonedDateTime {
        date,
        time,
        offset_secs,
        zoneinfo,
    } = ZonedDateTime::extract(slf);
    format!(
        "ZonedDateTime({} {}{}[{}])",
        date,
        time,
        offset_fmt(offset_secs),
        zoneinfo_key(zoneinfo)
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
unsafe fn _shift(obj_a: *mut PyObject, obj_b: *mut PyObject, negate: bool) -> PyReturn {
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
        py_api,
        ..
    } = State::for_type(type_a);
    if type_b == time_delta_type {
        let zdt = ZonedDateTime::extract(obj_a);
        let mut delta = TimeDelta::extract(obj_b);
        if negate {
            delta = -delta;
        };
        zdt.instant()
            .shift(delta.total_nanos())
            .ok_or_value_err("Resulting datetime is out of range")?
            .to_tz(py_api, zdt.zoneinfo)?
            .to_obj(type_a)
    } else if type_b == date_delta_type || type_b == datetime_delta_type {
        Err(type_err!(
            "Addition/subtraction of calendar units on a ZonedDateTime requires \
             explicit disambiguation. Use the `add`/`subtract` methods instead. \
             For example, instead of `dt + delta` use `dt.add(delta, disambiguate=...)`."
        ))?
    } else {
        Ok(newref(Py_NotImplemented()))
    }
}

unsafe fn __add__(slf: *mut PyObject, arg: *mut PyObject) -> PyReturn {
    if PyType_GetModule(Py_TYPE(slf)) == PyType_GetModule(Py_TYPE(arg)) {
        _shift(slf, arg, false)
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
                return _shift(obj_a, obj_b, true);
            };
            debug_assert_eq!(type_a, State::for_type(type_a).zoned_datetime_type);
            (ZonedDateTime::extract(obj_a).instant(), inst_b)
        } else {
            return Ok(newref(Py_NotImplemented()));
        }
    };
    TimeDelta::from_nanos_unchecked(inst_a.total_nanos() - inst_b.total_nanos())
        .to_obj(State::for_type(type_a).time_delta_type)
}

static mut SLOTS: &[PyType_Slot] = &[
    slotmethod!(Py_tp_new, __new__),
    slotmethod!(Py_tp_str, __str__, 1),
    slotmethod!(Py_tp_repr, __repr__, 1),
    slotmethod!(Py_tp_richcompare, __richcmp__),
    slotmethod!(Py_nb_add, __add__, 2),
    slotmethod!(Py_nb_subtract, __sub__, 2),
    PyType_Slot {
        slot: Py_tp_doc,
        pfunc: c"A datetime type with IANA tz ID".as_ptr() as *mut c_void,
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
        Err(type_err!(
            "Argument must be ZonedDateTime, got {}",
            obj_b.repr()
        ))
    }
}

unsafe fn to_tz(slf: &mut PyObject, tz: &mut PyObject) -> PyReturn {
    let cls = Py_TYPE(slf);
    let &State {
        zoneinfo_type,
        py_api,
        ..
    } = State::for_type(cls);
    let new_zoneinfo = call1(zoneinfo_type, tz)?;
    defer_decref!(new_zoneinfo);
    ZonedDateTime::extract(slf)
        .instant()
        .to_tz(py_api, new_zoneinfo)?
        .to_obj(cls)
}

pub(crate) unsafe fn unpickle(module: &mut PyObject, args: &[*mut PyObject]) -> PyReturn {
    let &[data, tz] = args else {
        Err(type_err!("Invalid pickle data"))?
    };
    let &State {
        zoneinfo_type,
        zoned_datetime_type,
        ..
    } = State::for_mod(module);
    let mut packed = data.to_bytes()?.ok_or_type_err("Invalid pickle data")?;
    let zoneinfo = call1(zoneinfo_type, tz)?;
    defer_decref!(zoneinfo);
    if packed.len() != 15 {
        Err(type_err!("Invalid pickle data"))?;
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
        zoneinfo,
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
        ..
    } = State::for_obj(slf);
    methcall1(
        zdt.zoneinfo,
        "fromutc",
        steal!(DateTime_FromDateAndTime(
            year.into(),
            month.into(),
            day.into(),
            hour.into(),
            minute.into(),
            second.into(),
            (nanos / 1_000) as _,
            zdt.zoneinfo,
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
        _ => Err(type_err!("to_fixed_offset() takes at most 1 argument")),
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
        py_api,
        str_disambiguate,
        exc_skipped,
        exc_repeated,
        ..
    } = State::for_obj(slf);

    let &[arg] = args else {
        Err(type_err!(
            "replace_date() takes exactly 1 argument but {} were given",
            args.len()
        ))?
    };

    let dis = Disambiguate::from_only_kwarg(kwargs, str_disambiguate, "replace_date")?;
    let ZonedDateTime { time, zoneinfo, .. } = ZonedDateTime::extract(slf);
    if Py_TYPE(arg) == date_type {
        ZonedDateTime::from_local(py_api, Date::extract(arg), time, zoneinfo, dis)?
            .map_err(|a| match a {
                Ambiguity::Fold => py_err!(
                    exc_repeated,
                    "The new date is repeated in the current timezone"
                ),
                Ambiguity::Gap => py_err!(
                    exc_skipped,
                    "The new date is skipped in the current timezone"
                ),
            })?
            .to_obj(cls)
    } else {
        Err(type_err!("date must be a whenever.Date instance"))
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
        py_api,
        str_disambiguate,
        exc_skipped,
        exc_repeated,
        ..
    } = State::for_obj(slf);

    let &[arg] = args else {
        Err(type_err!(
            "replace_time() takes exactly 1 argument but {} were given",
            args.len()
        ))?
    };

    let dis = Disambiguate::from_only_kwarg(kwargs, str_disambiguate, "replace_time")?;
    let ZonedDateTime { date, zoneinfo, .. } = ZonedDateTime::extract(slf);
    if Py_TYPE(arg) == time_type {
        ZonedDateTime::from_local(py_api, date, Time::extract(arg), zoneinfo, dis)?
            .map_err(|a| match a {
                Ambiguity::Fold => py_err!(
                    exc_repeated,
                    "The new time is repeated in the current timezone"
                ),
                Ambiguity::Gap => py_err!(
                    exc_skipped,
                    "The new time is skipped in the current timezone"
                ),
            })?
            .to_obj(cls)
    } else {
        Err(type_err!("time must be a whenever.Time instance"))
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
        Err(type_err!("replace() takes no positional arguments"))?;
    }
    let state = State::for_type(cls);
    let ZonedDateTime {
        date,
        time,
        mut zoneinfo,
        ..
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
        if eq(key, state.str_tz) {
            zoneinfo = call1(state.zoneinfo_type, value)?;
            defer_decref!(zoneinfo);
        } else if eq(key, state.str_disambiguate) {
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
    ZonedDateTime::from_local(
        state.py_api,
        date,
        time,
        zoneinfo,
        dis.ok_or_type_err("disambiguate keyword argument is required")?,
    )?
    .map_err(|a| match a {
        Ambiguity::Fold => py_err!(
            state.exc_repeated,
            "{} {} is repeated in timezone '{}'",
            date,
            time,
            zoneinfo_key(zoneinfo)
        ),
        Ambiguity::Gap => py_err!(
            state.exc_skipped,
            "{} {} is skipped in timezone '{}'",
            date,
            time,
            zoneinfo_key(zoneinfo)
        ),
    })?
    .to_obj(cls)
}

unsafe fn now(cls: *mut PyObject, tz: *mut PyObject) -> PyReturn {
    let state = State::for_type(cls.cast());
    let &State {
        py_api:
            &PyDateTime_CAPI {
                DateTime_FromTimestamp,
                DateTimeType,
                ..
            },
        zoneinfo_type,
        ..
    } = state;
    let zoneinfo = call1(zoneinfo_type, tz)? as *mut PyObject;
    defer_decref!(zoneinfo);
    let (timestamp, subsec) = state.time_ns()?;
    // OPTIMIZE: faster way without fromtimestamp?
    let dt = DateTime_FromTimestamp(
        DateTimeType,
        steal!((steal!(timestamp.to_py()?), zoneinfo).to_py()?),
        NULL(),
    )
    .as_result()?;
    defer_decref!(dt);
    ZonedDateTime {
        date: Date {
            year: PyDateTime_GET_YEAR(dt) as u16,
            month: PyDateTime_GET_MONTH(dt) as u8,
            day: PyDateTime_GET_DAY(dt) as u8,
        },
        time: Time {
            hour: PyDateTime_DATE_GET_HOUR(dt) as u8,
            minute: PyDateTime_DATE_GET_MINUTE(dt) as u8,
            second: PyDateTime_DATE_GET_SECOND(dt) as u8,
            nanos: subsec,
        },
        offset_secs: offset_from_py_dt(dt)?,
        zoneinfo,
    }
    .to_obj(cls.cast())
}

unsafe fn from_py_datetime(cls: *mut PyObject, dt: *mut PyObject) -> PyReturn {
    let &State {
        py_api,
        zoneinfo_type,
        ..
    } = State::for_type(cls.cast());
    if PyDateTime_Check(dt) == 0 {
        Err(type_err!("Argument must be a datetime.datetime instance"))?;
    }
    let tzinfo = get_dt_tzinfo(dt);

    // NOTE: it has to be exactly a `ZoneInfo`, since subclasses
    // could theoretically introduce circular references.
    // Since ZonedDateTime doesn't implement the GC protocol,
    // this could lead to memory leaks.
    if Py_TYPE(tzinfo) != zoneinfo_type.cast() {
        Err(value_err!(
            "tzinfo must be of type ZoneInfo (exactly), got {}",
            (Py_TYPE(tzinfo) as *mut PyObject).repr()
        ))?;
    }

    let fold = PyDateTime_DATE_GET_FOLD(dt);
    let date = Date {
        year: PyDateTime_GET_YEAR(dt) as _,
        month: PyDateTime_GET_MONTH(dt) as _,
        day: PyDateTime_GET_DAY(dt) as _,
    };
    let time = Time {
        hour: PyDateTime_DATE_GET_HOUR(dt) as _,
        minute: PyDateTime_DATE_GET_MINUTE(dt) as _,
        second: PyDateTime_DATE_GET_SECOND(dt) as _,
        nanos: PyDateTime_DATE_GET_MICROSECOND(dt) as u32 * 1_000,
    };
    use OffsetResult::*;
    match OffsetResult::for_tz(py_api, date, time, tzinfo)? {
        Unambiguous(offset_secs) => ZonedDateTime::new(date, time, offset_secs, tzinfo),
        Fold(offset0, offset1) => ZonedDateTime::new(
            date,
            time,
            if fold == 0 { offset0 } else { offset1 },
            tzinfo,
        ),
        Gap(offset0, offset1) => {
            let (offset_secs, shift) = if fold == 0 {
                (offset1, offset1 - offset0)
            } else {
                (offset0, offset0 - offset1)
            };
            DateTime { date, time }
                .small_shift_unchecked(shift)
                .with_tz(offset_secs, tzinfo)
        }
    }
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
        zoneinfo,
    } = ZonedDateTime::extract(slf);
    let data = pack![year, month, day, hour, minute, second, nanos, offset_secs];
    (
        State::for_obj(slf).unpickle_zoned_datetime,
        steal!((
            steal!(data.to_py()?),
            steal!(PyObject_GetAttrString(zoneinfo, c"key".as_ptr()).as_result()?),
        )
            .to_py()?),
    )
        .to_py()
}

// checks the args comply with (ts, /, *, tz: str)
#[inline]
unsafe fn check_from_timestamp_args_return_zoneinfo(
    args: &[*mut PyObject],
    kwargs: &mut KwargIter,
    &State {
        zoneinfo_type,
        str_tz,
        ..
    }: &State,
    fname: &str,
) -> PyReturn {
    match (args, kwargs.next()) {
        (&[_], Some((key, value))) if kwargs.len() == 1 => {
            if key.kwarg_eq(str_tz) {
                call1(zoneinfo_type, value)
            } else {
                Err(type_err!(
                    "{}() got an unexpected keyword argument {}",
                    fname,
                    key.repr()
                ))
            }
        }
        (&[_], None) => Err(type_err!(
            "{}() missing 1 required keyword-only argument: 'tz'",
            fname
        )),
        (&[], _) => Err(type_err!(
            "{}() missing 1 required positional argument",
            fname
        )),
        _ => Err(type_err!(
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
    let state = State::for_type(cls);
    let zoneinfo =
        check_from_timestamp_args_return_zoneinfo(args, kwargs, state, "from_timestamp")?;
    defer_decref!(zoneinfo);

    match args[0].to_i64()? {
        Some(ts) => Instant::from_timestamp(ts),
        None => Instant::from_timestamp_f64(
            args[0]
                .to_f64()?
                .ok_or_type_err("Timestamp must be an integer or float")?,
        ),
    }
    .ok_or_value_err("timestamp is out of range")?
    .to_tz(state.py_api, zoneinfo)?
    .to_obj(cls)
}

unsafe fn from_timestamp_millis(
    _: *mut PyObject,
    cls: *mut PyTypeObject,
    args: &[*mut PyObject],
    kwargs: &mut KwargIter,
) -> PyReturn {
    let state = State::for_type(cls);
    let zoneinfo =
        check_from_timestamp_args_return_zoneinfo(args, kwargs, state, "from_timestamp_millis")?;
    defer_decref!(zoneinfo);
    Instant::from_timestamp_millis(
        args[0]
            .to_i64()?
            .ok_or_type_err("timestamp must be an integer")?,
    )
    .ok_or_value_err("timestamp is out of range")?
    .to_tz(state.py_api, zoneinfo)?
    .to_obj(cls)
}

unsafe fn from_timestamp_nanos(
    _: *mut PyObject,
    cls: *mut PyTypeObject,
    args: &[*mut PyObject],
    kwargs: &mut KwargIter,
) -> PyReturn {
    let state = State::for_type(cls);
    let zoneinfo =
        check_from_timestamp_args_return_zoneinfo(args, kwargs, state, "from_timestamp_nanos")?;
    defer_decref!(zoneinfo);
    Instant::from_timestamp_nanos(
        args[0]
            .to_i128()?
            .ok_or_type_err("timestamp must be an integer")?,
    )
    .ok_or_value_err("timestamp is out of range")?
    .to_tz(state.py_api, zoneinfo)?
    .to_obj(cls)
}

unsafe fn is_ambiguous(slf: *mut PyObject, _: *mut PyObject) -> PyReturn {
    let ZonedDateTime {
        date,
        time,
        zoneinfo,
        ..
    } = ZonedDateTime::extract(slf);
    matches!(
        OffsetResult::for_tz(State::for_obj(slf).py_api, date, time, zoneinfo)?,
        OffsetResult::Fold(_, _)
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
    let raise = || value_err!("Invalid format: {}", s_obj.repr());
    // at least: "YYYY-MM-DD HH:MM:SSZ[_]"
    if s.len() < 23 || s[10] != b'T' {
        return Err(raise());
    }
    let date = Date::parse_partial(s).ok_or_else(raise)?;
    *s = &s[1..]; // skip the separator
    let time = Time::parse_partial(s).ok_or_else(raise)?;

    // at least "Z[_]" remains
    if s.len() < 4 {
        return Err(raise());
    }
    let offset_secs = parse_offset_partial(s).ok_or_else(raise)?;
    if s.len() < 3 || s.len() > 255 || s[0] != b'[' || s[s.len() - 1] != b']' || !s.is_ascii() {
        return Err(raise());
    }
    let &State {
        py_api,
        zoneinfo_type,
        exc_invalid_offset,
        ..
    } = State::for_type(cls.cast());
    let zoneinfo = call1(
        zoneinfo_type,
        steal!(std::str::from_utf8_unchecked(&s[1..s.len() - 1]).to_py()?),
    )?;
    defer_decref!(zoneinfo);
    let offset_is_valid = match OffsetResult::for_tz(py_api, date, time, zoneinfo)? {
        OffsetResult::Unambiguous(o) => o == offset_secs,
        OffsetResult::Gap(o1, o2) | OffsetResult::Fold(o1, o2) => {
            o1 == offset_secs || o2 == offset_secs
        }
    };
    if offset_is_valid {
        ZonedDateTime::new(date, time, offset_secs, zoneinfo)
            .ok_or_value_err("Datetime out of range")?
            .to_obj(cls.cast())
    } else {
        Err(py_err!(
            exc_invalid_offset,
            "Invalid offset for timezone {}",
            zoneinfo_key(zoneinfo)
        ))
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
    let mut nanos = 0;

    match *args {
        [arg] => {
            match kwargs.next() {
                Some((key, value)) if kwargs.len() == 1 && key.kwarg_eq(state.str_disambiguate) => {
                    dis = Some(Disambiguate::from_py(value)?)
                }
                None => {}
                _ => Err(type_err!(
                    "{}() can't mix positional and keyword arguments",
                    fname
                ))?,
            };
            if Py_TYPE(arg) == state.time_delta_type {
                nanos = TimeDelta::extract(arg).total_nanos();
            } else if Py_TYPE(arg) == state.date_delta_type {
                let dd = DateDelta::extract(arg);
                months = dd.months;
                days = dd.days;
            } else if Py_TYPE(arg) == state.datetime_delta_type {
                let dt = DateTimeDelta::extract(arg);
                months = dt.ddelta.months;
                days = dt.ddelta.days;
                nanos = dt.tdelta.total_nanos();
            } else {
                Err(type_err!("{}() argument must be a delta", fname))?
            }
        }
        [] => {
            handle_kwargs(fname, kwargs, |key, value, eq| {
                if eq(key, state.str_disambiguate) {
                    dis = Some(Disambiguate::from_py(value)?);
                    Ok(true)
                } else {
                    set_units_from_kwargs(key, value, &mut months, &mut days, &mut nanos, state, eq)
                }
            })?;
        }
        _ => Err(type_err!(
            "{}() takes at most 1 positional argument, got {}",
            fname,
            args.len()
        ))?,
    }
    if negate {
        months = -months;
        days = -days;
        nanos = -nanos;
    }
    // First, shift the calendar units
    let zdt = if months != 0 || days != 0 {
        let ZonedDateTime {
            date,
            time,
            zoneinfo,
            ..
        } = ZonedDateTime::extract(slf);
        ZonedDateTime::from_local(
            state.py_api,
            date.shift(0, months, days)
                .ok_or_value_err("Resulting date is out of range")?,
            time,
            zoneinfo,
            dis.ok_or_else(|| {
                type_err!(
                    "{}() requires a 'disambiguate' keyword argument when given calendar units",
                    fname
                )
            })?,
        )?
        .map_err(|amb| match amb {
            Ambiguity::Fold => py_err!(
                state.exc_repeated,
                "The resulting datetime is repeated in tz {}",
                zoneinfo_key(zoneinfo)
            ),
            Ambiguity::Gap => py_err!(
                state.exc_skipped,
                "The resulting datetime is skipped in tz {}",
                zoneinfo_key(zoneinfo)
            ),
        })?
    } else {
        ZonedDateTime::extract(slf)
    };

    zdt.instant()
        .shift(nanos)
        .ok_or_value_err("Result is out of range")?
        .to_tz(state.py_api, zdt.zoneinfo)?
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
        Err(type_err!(
            "difference() argument must be an OffsetDateTime, 
             Instant, ZonedDateTime, or SystemDateTime"
        ))?
    };
    TimeDelta::from_nanos_unchecked(inst_a.total_nanos() - inst_b.total_nanos())
        .to_obj(state.time_delta_type)
}

static mut METHODS: &[PyMethodDef] = &[
    method!(identity2 named "__copy__", ""),
    method!(identity2 named "__deepcopy__", "", METH_O),
    method!(to_tz, "Convert to a `ZonedDateTime` with given tz", METH_O),
    method!(exact_eq, "Exact equality", METH_O),
    method!(py_datetime, "Convert to a `datetime.datetime`"),
    method!(instant, "Get the underlying instant"),
    method!(to_system_tz, "Convert to a datetime in the system timezone"),
    method!(date, "The date component"),
    method!(time, "The time component"),
    method!(
        format_common_iso,
        "Format in the common ISO format (RFC9557 profile)"
    ),
    method!(
        parse_common_iso,
        "Parse the common ISO format (RFC9557 profile)",
        METH_O | METH_CLASS
    ),
    method!(__reduce__, ""),
    method!(
        now,
        "Create a new instance representing the current time",
        METH_O | METH_CLASS
    ),
    method!(
        from_py_datetime,
        "Create a new instance from a `datetime.datetime`",
        METH_O | METH_CLASS
    ),
    method!(local, "Get the local date and time"),
    method!(timestamp, "Convert to a UNIX timestamp"),
    method!(
        timestamp_millis,
        "Convert to a UNIX timestamp in milliseconds"
    ),
    method!(
        timestamp_nanos,
        "Convert to a UNIX timestamp in nanoseconds"
    ),
    method!(is_ambiguous, "Check if the datetime is ambiguous"),
    method_kwargs!(
        from_timestamp,
        "Create a new instance from a UNIX timestamp",
        METH_CLASS
    ),
    method_kwargs!(
        from_timestamp_millis,
        "Create a new instance from a UNIX timestamp in milliseconds",
        METH_CLASS
    ),
    method_kwargs!(
        from_timestamp_nanos,
        "Create a new instance from a UNIX timestamp in nanoseconds",
        METH_CLASS
    ),
    method_kwargs!(
        replace,
        "Return a new instance with the specified fields replaced"
    ),
    method_kwargs!(replace_date, "Return a new instance with the date replaced"),
    method_kwargs!(replace_time, "Return a new instance with the time replaced"),
    method_vararg!(to_fixed_offset, "Convert to an equivalent offset datetime"),
    method_kwargs!(add, "Add various time/calendar units"),
    method_kwargs!(subtract, "Subtract various time/calendar units"),
    method!(
        difference,
        "Get the difference between two instances",
        METH_O
    ),
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
    PyObject_GetAttrString(ZonedDateTime::extract(slf).zoneinfo, c"key".as_ptr()).as_result()
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

type_spec!(ZonedDateTime, SLOTS);
