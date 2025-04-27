use core::ffi::{c_int, c_long, c_void, CStr};
use core::ptr::null_mut as NULL;
use pyo3_ffi::*;

use crate::common::math::*;
use crate::common::*;
use crate::datetime_delta::handle_exact_unit;
use crate::docstrings as doc;
use crate::time_delta::{MAX_HOURS, MAX_MICROSECONDS, MAX_MILLISECONDS, MAX_MINUTES, MAX_SECS};
use crate::{
    date::Date,
    offset_datetime::{self, OffsetDateTime},
    plain_datetime::DateTime,
    round,
    time::Time,
    time_delta::TimeDelta,
    zoned_datetime::ZonedDateTime,
    State,
};

#[derive(Debug, Eq, PartialEq, Ord, PartialOrd, Copy, Clone)]
pub(crate) struct Instant {
    pub(crate) epoch: EpochSecs,
    pub(crate) subsec: SubSecNanos,
    // FUTURE: make use of padding to cache something?
}

pub(crate) const SINGLETONS: &[(&CStr, Instant); 2] = &[
    (
        c"MIN",
        Instant {
            epoch: EpochSecs::MIN,
            subsec: SubSecNanos::MIN,
        },
    ),
    (
        c"MAX",
        Instant {
            epoch: EpochSecs::MAX,
            subsec: SubSecNanos::MAX,
        },
    ),
];

impl Instant {
    pub(crate) fn from_datetime(date: Date, time: Time) -> Self {
        Instant {
            epoch: date.epoch_at(time),
            subsec: time.subsec,
        }
    }

    pub(crate) fn to_datetime(self) -> DateTime {
        self.epoch.datetime(self.subsec)
    }

    pub(crate) fn diff(self, other: Self) -> TimeDelta {
        let (extra_sec, subsec) = self.subsec.diff(other.subsec);
        TimeDelta {
            secs: self
                .epoch
                .diff(other.epoch)
                // Safety: we know that the difference between two instants is
                // always within delta range
                .add(extra_sec)
                .unwrap(),
            subsec,
        }
    }

    pub(crate) fn timestamp_millis(&self) -> i64 {
        self.epoch.get() * 1_000 + self.subsec.get() as i64 / 1_000_000
    }

    pub(crate) fn timestamp_nanos(&self) -> i128 {
        self.epoch.get() as i128 * 1_000_000_000 + self.subsec.get() as i128
    }

    pub(crate) fn from_timestamp(timestamp: i64) -> Option<Self> {
        Some(Instant {
            epoch: EpochSecs::new(timestamp)?,
            subsec: SubSecNanos::MIN,
        })
    }

    pub(crate) fn from_timestamp_f64(timestamp: f64) -> Option<Self> {
        (EpochSecs::MIN.get() as f64..=EpochSecs::MAX.get() as f64)
            .contains(&timestamp)
            .then(|| Instant {
                epoch: EpochSecs::new_unchecked(timestamp.floor() as i64),
                subsec: SubSecNanos::from_fract(timestamp),
            })
    }

    pub(crate) fn from_timestamp_millis(millis: i64) -> Option<Self> {
        Some(Instant {
            epoch: EpochSecs::new(millis.div_euclid(1_000))?,
            // Safety: we stay under 1_000_000_000
            subsec: SubSecNanos::new_unchecked(millis.rem_euclid(1_000) as i32 * 1_000_000),
        })
    }

    pub(crate) fn from_timestamp_nanos(timestamp: i128) -> Option<Self> {
        i64::try_from(timestamp.div_euclid(1_000_000_000))
            .ok()
            .and_then(EpochSecs::new)
            .map(|secs| Instant {
                epoch: secs,
                subsec: SubSecNanos::from_remainder(timestamp),
            })
    }

    pub(crate) fn shift(&self, d: TimeDelta) -> Option<Instant> {
        let (extra_sec, subsec) = self.subsec.add(d.subsec);
        Some(Instant {
            epoch: self.epoch.shift(d.secs)?.shift(extra_sec)?,
            subsec,
        })
    }

    pub(crate) fn offset(&self, f: Offset) -> Option<Self> {
        Some(Instant {
            epoch: self.epoch.offset(f)?,
            subsec: self.subsec,
        })
    }

    pub(crate) unsafe fn to_py(
        self,
        &PyDateTime_CAPI {
            DateTime_FromDateAndTime,
            TimeZone_UTC,
            DateTimeType,
            ..
        }: &PyDateTime_CAPI,
    ) -> PyReturn {
        let DateTime {
            date: Date { year, month, day },
            time:
                Time {
                    hour,
                    minute,
                    second,
                    subsec: nanos,
                },
        } = self.to_datetime();
        DateTime_FromDateAndTime(
            year.get().into(),
            month.get().into(),
            day.into(),
            hour.into(),
            minute.into(),
            second.into(),
            (nanos.get() / 1_000) as _,
            TimeZone_UTC,
            DateTimeType,
        )
        .as_result()
    }

    // Returns None if the datetime is out of range
    unsafe fn from_py(dt: *mut PyObject, state: &State) -> PyResult<Option<Self>> {
        let tzinfo = borrow_dt_tzinfo(dt);
        if is_none(tzinfo) {
            raise_value_err("datetime cannot be naive")?;
        };
        let inst =
            Instant::from_datetime(Date::from_py_unchecked(dt), Time::from_py_dt_unchecked(dt));
        Ok(if tzinfo == state.py_api.TimeZone_UTC {
            // Fast path for the common case
            Some(inst)
        } else {
            let py_delta = methcall1(tzinfo, "utcoffset", dt)?;
            defer_decref!(py_delta);
            if is_none(py_delta) {
                raise_value_err("datetime utcoffset() is None")?;
            }
            inst.shift(
                // Safe: Python offsets are already bounded to +/- 24 hours: well within TimeDelta range.
                -TimeDelta::from_py_unsafe(py_delta),
            )
        })
    }

    pub(crate) const fn pyhash(&self) -> Py_hash_t {
        #[cfg(target_pointer_width = "64")]
        {
            hash_combine(
                self.epoch.get() as Py_hash_t,
                self.subsec.get() as Py_hash_t,
            )
        }
        #[cfg(target_pointer_width = "32")]
        hash_combine(
            self.epoch.get() as Py_hash_t,
            hash_combine(
                (self.epoch.get() >> 32) as Py_hash_t,
                self.subsec.get() as Py_hash_t,
            ),
        )
    }

    fn to_delta(self) -> TimeDelta {
        TimeDelta {
            secs: self.epoch.to_delta(),
            subsec: self.subsec,
        }
    }
}

unsafe fn __new__(_: *mut PyTypeObject, _: *mut PyObject, _: *mut PyObject) -> PyReturn {
    raise(PyExc_TypeError, "Instant cannot be instantiated directly")
}

unsafe fn from_utc(cls: *mut PyTypeObject, args: *mut PyObject, kwargs: *mut PyObject) -> PyReturn {
    let mut year: c_long = 0;
    let mut month: c_long = 0;
    let mut day: c_long = 0;
    let mut hour: c_long = 0;
    let mut minute: c_long = 0;
    let mut second: c_long = 0;
    let mut nanosecond: c_long = 0;

    parse_args_kwargs!(
        args,
        kwargs,
        c"lll|lll$l:Instant.from_utc",
        year,
        month,
        day,
        hour,
        minute,
        second,
        nanosecond
    );

    Instant::from_datetime(
        Date::from_longs(year, month, day).ok_or_value_err("Invalid date")?,
        Time::from_longs(hour, minute, second, nanosecond).ok_or_value_err("Invalid time")?,
    )
    .to_obj(cls)
}

impl PyWrapped for Instant {}

unsafe fn __repr__(slf: *mut PyObject) -> PyReturn {
    let DateTime { date, time } = Instant::extract(slf).to_datetime();
    format!("Instant({} {}Z)", date, time).to_py()
}

unsafe fn __str__(slf: *mut PyObject) -> PyReturn {
    let DateTime { date, time } = Instant::extract(slf).to_datetime();
    format!("{}T{}Z", date, time).to_py()
}

unsafe fn __richcmp__(a_obj: *mut PyObject, b_obj: *mut PyObject, op: c_int) -> PyReturn {
    let type_a = Py_TYPE(a_obj);
    let type_b = Py_TYPE(b_obj);
    let inst_a = Instant::extract(a_obj);
    let inst_b = if type_b == type_a {
        Instant::extract(b_obj)
    } else if type_b == State::for_type(type_a).zoned_datetime_type {
        ZonedDateTime::extract(b_obj).instant()
    } else if type_b == State::for_type(type_a).offset_datetime_type
        || type_b == State::for_type(type_a).system_datetime_type
    {
        OffsetDateTime::extract(b_obj).instant()
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
    hashmask(Instant::extract(slf).pyhash())
}

unsafe fn __sub__(obj_a: *mut PyObject, obj_b: *mut PyObject) -> PyReturn {
    let type_a = Py_TYPE(obj_a);
    let type_b = Py_TYPE(obj_b);

    // Easy case: UTC - UTC
    let (inst_a, inst_b) = if type_a == type_b {
        (Instant::extract(obj_a), Instant::extract(obj_b))
    // Other cases are more difficult, as they can be triggered
    // by reflexive operations with arbitrary types.
    // We need to eliminate them carefully.
    } else {
        let mod_a = PyType_GetModule(type_a);
        let mod_b = PyType_GetModule(type_b);
        if mod_a == mod_b {
            let inst_b = if type_b == State::for_mod(mod_a).zoned_datetime_type {
                ZonedDateTime::extract(obj_b).instant()
            } else if type_b == State::for_mod(mod_a).offset_datetime_type
                || type_b == State::for_mod(mod_a).system_datetime_type
            {
                OffsetDateTime::extract(obj_b).instant()
            } else {
                return _shift(obj_a, obj_b, true);
            };
            (Instant::extract(obj_a), inst_b)
        } else {
            return Ok(newref(Py_NotImplemented()));
        }
    };
    inst_a
        .diff(inst_b)
        .to_obj(State::for_type(type_a).time_delta_type)
}

unsafe fn __add__(dt: *mut PyObject, delta_obj: *mut PyObject) -> PyReturn {
    if PyType_GetModule(Py_TYPE(dt)) == PyType_GetModule(Py_TYPE(delta_obj)) {
        _shift(dt, delta_obj, false)
    } else {
        Ok(newref(Py_NotImplemented()))
    }
}

#[inline]
unsafe fn _shift(obj_a: *mut PyObject, obj_b: *mut PyObject, negate: bool) -> PyReturn {
    debug_assert_eq!(
        PyType_GetModule(Py_TYPE(obj_a)),
        PyType_GetModule(Py_TYPE(obj_b))
    );
    let type_a = Py_TYPE(obj_a);
    let mut delta = if Py_TYPE(obj_b) == State::for_type(type_a).time_delta_type {
        TimeDelta::extract(obj_b)
    } else {
        return Ok(newref(Py_NotImplemented()));
    };
    if negate {
        delta = -delta;
    }
    Instant::extract(obj_a)
        .shift(delta)
        .ok_or_value_err("Resulting datetime is out of range")?
        .to_obj(type_a)
}

#[allow(static_mut_refs)]
static mut SLOTS: &[PyType_Slot] = &[
    slotmethod!(Py_tp_new, __new__),
    slotmethod!(Py_tp_repr, __repr__, 1),
    slotmethod!(Py_tp_str, __str__, 1),
    slotmethod!(Py_tp_richcompare, __richcmp__),
    slotmethod!(Py_nb_subtract, __sub__, 2),
    slotmethod!(Py_nb_add, __add__, 2),
    PyType_Slot {
        slot: Py_tp_doc,
        pfunc: doc::INSTANT.as_ptr() as *mut c_void,
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
        slot: Py_tp_dealloc,
        pfunc: generic_dealloc as *mut c_void,
    },
    PyType_Slot {
        slot: 0,
        pfunc: NULL(),
    },
];

unsafe fn exact_eq(obj_a: *mut PyObject, obj_b: *mut PyObject) -> PyReturn {
    if Py_TYPE(obj_a) == Py_TYPE(obj_b) {
        (Instant::extract(obj_a) == Instant::extract(obj_b)).to_py()
    } else {
        raise_type_err("Can't compare different types")
    }
}

unsafe fn __reduce__(slf: *mut PyObject, _: *mut PyObject) -> PyReturn {
    let Instant { epoch, subsec } = Instant::extract(slf);
    let data = pack![epoch.get(), subsec.get()];
    (
        State::for_obj(slf).unpickle_instant,
        steal!((steal!(data.to_py()?),).to_py()?),
    )
        .to_py()
}

pub(crate) unsafe fn unpickle(module: *mut PyObject, arg: *mut PyObject) -> PyReturn {
    let mut packed = arg.to_bytes()?.ok_or_value_err("Invalid pickle data")?;
    if packed.len() != 12 {
        raise_value_err("Invalid pickle data")?;
    }
    Instant {
        epoch: EpochSecs::new_unchecked(unpack_one!(packed, i64)),
        subsec: SubSecNanos::new_unchecked(unpack_one!(packed, i32)),
    }
    .to_obj(State::for_mod(module).instant_type)
}

// Backwards compatibility: an unpickler for Instants pickled before 0.8.0
pub(crate) unsafe fn unpickle_v07(module: *mut PyObject, arg: *mut PyObject) -> PyReturn {
    let mut packed = arg.to_bytes()?.ok_or_value_err("Invalid pickle data")?;
    if packed.len() != 12 {
        raise_value_err("Invalid pickle data")?;
    }
    Instant {
        epoch: EpochSecs::new_unchecked(unpack_one!(packed, i64) + EpochSecs::MIN.get() - 86_400),
        subsec: SubSecNanos::new_unchecked(unpack_one!(packed, i32)),
    }
    .to_obj(State::for_mod(module).instant_type)
}

unsafe fn timestamp(slf: *mut PyObject, _: *mut PyObject) -> PyReturn {
    Instant::extract(slf).epoch.get().to_py()
}

unsafe fn timestamp_millis(slf: *mut PyObject, _: *mut PyObject) -> PyReturn {
    Instant::extract(slf).timestamp_millis().to_py()
}

unsafe fn timestamp_nanos(slf: *mut PyObject, _: *mut PyObject) -> PyReturn {
    Instant::extract(slf).timestamp_nanos().to_py()
}

unsafe fn from_timestamp(cls: *mut PyObject, ts: *mut PyObject) -> PyReturn {
    match ts.to_i64()? {
        Some(ts) => Instant::from_timestamp(ts),
        None => Instant::from_timestamp_f64(
            ts.to_f64()?
                .ok_or_type_err("Timestamp must be an integer or float")?,
        ),
    }
    .ok_or_value_err("Timestamp out of range")?
    .to_obj(cls.cast())
}

unsafe fn from_timestamp_millis(cls: *mut PyObject, ts: *mut PyObject) -> PyReturn {
    Instant::from_timestamp_millis(
        ts.to_i64()?
            .ok_or_type_err("Timestamp must be an integer")?,
    )
    .ok_or_value_err("Timestamp out of range")?
    .to_obj(cls.cast())
}

unsafe fn from_timestamp_nanos(cls: *mut PyObject, ts: *mut PyObject) -> PyReturn {
    Instant::from_timestamp_nanos(
        ts.to_i128()?
            .ok_or_type_err("Timestamp must be an integer")?,
    )
    .ok_or_value_err("Timestamp out of range")?
    .to_obj(cls.cast())
}

unsafe fn py_datetime(slf: *mut PyObject, _: *mut PyObject) -> PyReturn {
    Instant::extract(slf).to_py(State::for_obj(slf).py_api)
}

unsafe fn from_py_datetime(cls: *mut PyObject, dt: *mut PyObject) -> PyReturn {
    if PyDateTime_Check(dt) == 0 {
        raise_type_err("Expected a datetime object")?;
    }
    Instant::from_py(dt, State::for_type(cls.cast()))?
        .ok_or_else_value_err(|| format!("datetime out of range: {}", dt.repr()))?
        .to_obj(cls.cast())
}

unsafe fn now(cls: *mut PyObject, _: *mut PyObject) -> PyReturn {
    State::for_type(cls.cast()).time_ns()?.to_obj(cls.cast())
}

unsafe fn format_common_iso(slf: *mut PyObject, _: *mut PyObject) -> PyReturn {
    __str__(slf)
}

unsafe fn parse_common_iso(cls: *mut PyObject, s_obj: *mut PyObject) -> PyReturn {
    OffsetDateTime::parse(s_obj.to_utf8()?.ok_or_type_err("Expected a string")?)
        .ok_or_else_value_err(|| format!("Invalid format: {}", s_obj.repr()))?
        .instant()
        .to_obj(cls.cast())
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
    let instant = Instant::extract(slf);
    let &State {
        str_hours,
        str_minutes,
        str_seconds,
        str_milliseconds,
        str_microseconds,
        str_nanoseconds,
        ..
    } = State::for_type(cls);
    let mut nanos: i128 = 0;

    if !args.is_empty() {
        raise_type_err(format!("{}() takes no positional arguments", fname))?;
    }
    handle_kwargs(fname, kwargs, |key, value, eq| {
        if eq(key, str_hours) {
            nanos += handle_exact_unit(value, MAX_HOURS, "hours", 3_600_000_000_000_i128)?;
        } else if eq(key, str_minutes) {
            nanos += handle_exact_unit(value, MAX_MINUTES, "minutes", 60_000_000_000_i128)?;
        } else if eq(key, str_seconds) {
            nanos += handle_exact_unit(value, MAX_SECS, "seconds", 1_000_000_000_i128)?;
        } else if eq(key, str_milliseconds) {
            nanos += handle_exact_unit(value, MAX_MILLISECONDS, "milliseconds", 1_000_000_i128)?;
        } else if eq(key, str_microseconds) {
            nanos += handle_exact_unit(value, MAX_MICROSECONDS, "microseconds", 1_000_i128)?;
        } else if eq(key, str_nanoseconds) {
            nanos = value
                .to_i128()?
                .ok_or_value_err("nanoseconds must be an integer")?
                .checked_add(nanos)
                .ok_or_value_err("total nanoseconds out of range")?;
        } else {
            return Ok(false);
        }
        Ok(true)
    })?;
    if negate {
        nanos = -nanos;
    }

    instant
        .shift(TimeDelta::from_nanos(nanos).ok_or_value_err("Total duration out of range")?)
        .ok_or_value_err("Resulting datetime is out of range")?
        .to_obj(cls)
}

unsafe fn difference(obj_a: *mut PyObject, obj_b: *mut PyObject) -> PyReturn {
    let type_b = Py_TYPE(obj_b);
    let type_a = Py_TYPE(obj_a);
    let state = State::for_type(type_a);
    let inst_a = Instant::extract(obj_a);
    let inst_b = if type_b == Py_TYPE(obj_a) {
        Instant::extract(obj_b)
    } else if type_b == state.zoned_datetime_type {
        ZonedDateTime::extract(obj_b).instant()
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

unsafe fn to_tz(slf: &mut PyObject, tz_obj: *mut PyObject) -> PyReturn {
    let &mut State {
        zoned_datetime_type,
        exc_tz_notfound,
        ref mut tz_cache,
        ..
    } = State::for_obj_mut(slf);
    let tz = tz_cache.obj_get(tz_obj, exc_tz_notfound)?;
    Instant::extract(slf)
        .to_tz(tz)
        .ok_or_value_err("Resulting datetime is out of range")?
        .to_obj(zoned_datetime_type)
}

unsafe fn to_fixed_offset(slf_obj: *mut PyObject, args: &[*mut PyObject]) -> PyReturn {
    let cls = Py_TYPE(slf_obj);
    let slf = Instant::extract(slf_obj);
    let &State {
        offset_datetime_type,
        time_delta_type,
        ..
    } = State::for_type(cls);
    match *args {
        [] => slf
            .to_datetime()
            .with_offset_unchecked(Offset::ZERO)
            .to_obj(offset_datetime_type),
        [offset_obj] => slf
            .to_offset(offset_datetime::extract_offset(
                offset_obj,
                time_delta_type,
            )?)
            .ok_or_value_err("Resulting date is out of range")?
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
    Instant::extract(slf)
        .to_system_tz(py_api)?
        .to_obj(system_datetime_type)
}

unsafe fn format_rfc2822(slf: *mut PyObject, _: *mut PyObject) -> PyReturn {
    std::str::from_utf8_unchecked(&rfc2822::write_gmt(Instant::extract(slf))[..]).to_py()
}

unsafe fn parse_rfc2822(cls: *mut PyObject, s_obj: *mut PyObject) -> PyReturn {
    let s = s_obj.to_utf8()?.ok_or_type_err("Expected a string")?;
    let (date, time, offset) =
        rfc2822::parse(s).ok_or_else_value_err(|| format!("Invalid format: {}", s_obj.repr()))?;
    OffsetDateTime::new(date, time, offset)
        .ok_or_value_err("Instant out of range")?
        .instant()
        .to_obj(cls.cast())
}

unsafe fn round(
    slf: *mut PyObject,
    cls: *mut PyTypeObject,
    args: &[*mut PyObject],
    kwargs: &mut KwargIter,
) -> PyReturn {
    let (unit, increment, mode) =
        round::parse_args(State::for_obj(slf), args, kwargs, false, false)?;
    if unit == round::Unit::Day {
        raise_value_err(doc::CANNOT_ROUND_DAY_MSG)?;
    }
    let TimeDelta { secs, subsec } = Instant::extract(slf)
        .to_delta()
        .round(increment, mode)
        // Safety: TimeDelta has higher range than Instant,
        // so rounding cannot result in out-of-range
        .unwrap();
    Instant {
        epoch: EpochSecs::new(secs.get()).ok_or_value_err("Resulting instant out of range")?,
        subsec,
    }
    .to_obj(cls)
}

static mut METHODS: &[PyMethodDef] = &[
    method!(identity2 named "__copy__", c""),
    method!(identity2 named "__deepcopy__", c"", METH_O),
    method!(__reduce__, c""),
    method!(exact_eq, doc::EXACTTIME_EXACT_EQ, METH_O),
    method!(timestamp, doc::EXACTTIME_TIMESTAMP),
    method!(timestamp_millis, doc::EXACTTIME_TIMESTAMP_MILLIS),
    method!(timestamp_nanos, doc::EXACTTIME_TIMESTAMP_NANOS),
    method!(
        from_timestamp,
        doc::INSTANT_FROM_TIMESTAMP,
        METH_O | METH_CLASS
    ),
    PyMethodDef {
        ml_name: c"from_utc".as_ptr(),
        ml_meth: PyMethodDefPointer {
            PyCFunctionWithKeywords: {
                unsafe extern "C" fn _wrap(
                    slf: *mut PyObject,
                    args: *mut PyObject,
                    kwargs: *mut PyObject,
                ) -> *mut PyObject {
                    match from_utc(slf.cast(), args, kwargs) {
                        Ok(x) => x as *mut PyObject,
                        Err(PyErrOccurred()) => core::ptr::null_mut(),
                    }
                }
                _wrap
            },
        },
        ml_flags: METH_CLASS | METH_VARARGS | METH_KEYWORDS,
        ml_doc: doc::INSTANT_FROM_UTC.as_ptr(),
    },
    method!(
        from_timestamp_millis,
        doc::INSTANT_FROM_TIMESTAMP_MILLIS,
        METH_O | METH_CLASS
    ),
    method!(
        from_timestamp_nanos,
        doc::INSTANT_FROM_TIMESTAMP_NANOS,
        METH_O | METH_CLASS
    ),
    method!(py_datetime, doc::BASICCONVERSIONS_PY_DATETIME),
    method!(
        from_py_datetime,
        doc::INSTANT_FROM_PY_DATETIME,
        METH_O | METH_CLASS
    ),
    method!(now, doc::INSTANT_NOW, METH_CLASS | METH_NOARGS),
    method!(format_rfc2822, doc::INSTANT_FORMAT_RFC2822),
    method!(
        parse_rfc2822,
        doc::INSTANT_PARSE_RFC2822,
        METH_O | METH_CLASS
    ),
    method!(format_common_iso, doc::INSTANT_FORMAT_COMMON_ISO),
    method!(
        parse_common_iso,
        doc::INSTANT_PARSE_COMMON_ISO,
        METH_O | METH_CLASS
    ),
    method_kwargs!(add, doc::INSTANT_ADD),
    method_kwargs!(subtract, doc::INSTANT_SUBTRACT),
    method!(to_tz, doc::EXACTTIME_TO_TZ, METH_O),
    method!(to_system_tz, doc::EXACTTIME_TO_SYSTEM_TZ),
    method_vararg!(to_fixed_offset, doc::EXACTTIME_TO_FIXED_OFFSET),
    method!(difference, doc::EXACTTIME_DIFFERENCE, METH_O),
    method_kwargs!(round, doc::INSTANT_ROUND),
    PyMethodDef::zeroed(),
];

pub(crate) static mut SPEC: PyType_Spec =
    type_spec::<Instant>(c"whenever.Instant", unsafe { SLOTS });
