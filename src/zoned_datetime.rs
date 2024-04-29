use core::ffi::{c_char, c_int, c_long, c_void};
use core::{mem, ptr, ptr::null_mut as NULL};
use pyo3_ffi::*;
use std::fmt::{self, Display, Formatter};
use std::time::SystemTime;

use crate::common::*;
use crate::{
    date::{self, Date},
    date_delta::DateDelta,
    local_datetime,
    naive_datetime::{self, DateTime},
    offset_datetime::{self, OffsetDateTime},
    time::{self, Time},
    time_delta::{self, TimeDelta},
    utc_datetime::{self, Instant},
    State,
};

#[derive(Debug, Eq, PartialEq, Ord, PartialOrd, Copy, Clone)]
pub(crate) struct ZonedDateTime {
    pub(crate) date: Date,
    pub(crate) time: Time,
    pub(crate) offset_secs: i32, // the offset is already priced into the date and time
    pub(crate) zoneinfo: *mut PyObject,
}

#[repr(C)]
pub(crate) struct PyZonedDateTime {
    _ob_base: PyObject,
    dt: ZonedDateTime,
}

impl ZonedDateTime {
    pub(crate) unsafe fn extract(obj: *mut PyObject) -> Self {
        (*obj.cast::<PyZonedDateTime>()).dt
    }

    pub(crate) unsafe fn from_local(
        py_api: &PyDateTime_CAPI,
        date: Date,
        time: Time,
        zoneinfo: *mut PyObject,
        dis: Disambiguate,
    ) -> Result<Self, Ambiguity> {
        use OffsetResult as R;
        match OffsetResult::for_tz(py_api, date, time, zoneinfo) {
            R::Unambiguous(offset_secs) => Ok(ZonedDateTime {
                date,
                time,
                offset_secs,
                zoneinfo,
            }),
            R::Fold(offset0, offset1) => match dis {
                Disambiguate::Compatible | Disambiguate::Earlier => Ok(offset0),
                Disambiguate::Later => Ok(offset1),
                Disambiguate::Raise => Err(Ambiguity::Fold),
            }
            .map(|offset_secs| ZonedDateTime {
                date,
                time,
                offset_secs,
                zoneinfo,
            }),
            R::Gap(offset0, offset1) => match dis {
                Disambiguate::Compatible | Disambiguate::Later => Ok((offset1, offset1 - offset0)),
                Disambiguate::Earlier => Ok((offset0, offset0 - offset1)),
                Disambiguate::Raise => Err(Ambiguity::Gap),
            }
            .map(|(offset_secs, shift)| {
                ZonedDateTime {
                    date,
                    time,
                    offset_secs,
                    zoneinfo,
                }
                .small_naive_shift(shift)
            }),
        }
    }

    pub(crate) const fn to_instant(&self) -> Instant {
        Instant::from_datetime(self.date, self.time).shift_secs_unchecked(-self.offset_secs as i64)
    }

    const fn small_naive_shift(&self, secs: i32) -> Self {
        debug_assert!(secs.abs() < 86400 * 2);
        let Self { date, time, .. } = self;
        let day_seconds = time.seconds() + secs;
        let (new_date, new_time) = match day_seconds.div_euclid(86400) {
            0 => (*date, time.set_seconds(day_seconds as u32)),
            1 => (
                date.increment(),
                time.set_seconds((day_seconds - 86400) as u32),
            ),
            -1 => (
                date.decrement(),
                time.set_seconds((day_seconds + 86400) as u32),
            ),
            // more than 1 day difference is unlikely--but possible
            2 => (
                date.increment().increment(),
                time.set_seconds((day_seconds - 86400 * 2) as u32),
            ),
            -2 => (
                date.decrement().decrement(),
                time.set_seconds((day_seconds + 86400 * 2) as u32),
            ),
            _ => unreachable!(),
        };
        ZonedDateTime {
            date: new_date,
            time: new_time,
            ..*self
        }
    }

    pub(crate) unsafe fn from_utc(
        &PyDateTime_CAPI {
            DateTime_FromDateAndTime,
            DateTimeType,
            ..
        }: &PyDateTime_CAPI,
        Date { year, month, day }: Date,
        Time {
            hour,
            minute,
            second,
            nanos,
        }: Time,
        zoneinfo: *mut PyObject,
    ) -> Self {
        let new_py_dt = PyObject_CallMethodOneArg(
            zoneinfo,
            py_str("fromutc"),
            DateTime_FromDateAndTime(
                year.into(),
                month.into(),
                day.into(),
                hour.into(),
                minute.into(),
                second.into(),
                0, // no sub-second ZoneInfo offsets exist
                zoneinfo,
                DateTimeType,
            ),
        );

        ZonedDateTime {
            date: Date {
                year: PyDateTime_GET_YEAR(new_py_dt) as u16,
                month: PyDateTime_GET_MONTH(new_py_dt) as u8,
                day: PyDateTime_GET_DAY(new_py_dt) as u8,
            },
            time: Time {
                hour: PyDateTime_DATE_GET_HOUR(new_py_dt) as u8,
                minute: PyDateTime_DATE_GET_MINUTE(new_py_dt) as u8,
                second: PyDateTime_DATE_GET_SECOND(new_py_dt) as u8,
                nanos,
            },
            offset_secs: offset_from_py_dt(new_py_dt),
            zoneinfo,
        }
    }

    pub(crate) const fn to_offset(&self) -> OffsetDateTime {
        OffsetDateTime {
            date: self.date,
            time: self.time,
            offset_secs: self.offset_secs,
        }
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
            "{} {}{}[{}]",
            date,
            time,
            offset_fmt(offset_secs),
            unsafe { zoneinfo_key(zoneinfo) }
        )
    }
}

unsafe fn zoneinfo_key<'a>(zoneinfo: *mut PyObject) -> &'a str {
    let mut size = 0;
    // TODO: does this leak?
    let p = PyUnicode_AsUTF8AndSize(PyObject_GetAttrString(zoneinfo, c_str!("key")), &mut size);
    std::str::from_utf8_unchecked(std::slice::from_raw_parts(p.cast(), size as usize))
}

unsafe extern "C" fn __new__(
    type_: *mut PyTypeObject,
    args: *mut PyObject,
    kwargs: *mut PyObject,
) -> *mut PyObject {
    let &State {
        zoneinfo_type,
        datetime_api: api,
        exc_ambiguous,
        exc_skipped,
        str_raise,
        ..
    } = State::for_type(type_);
    let mut year: c_long = 0;
    let mut month: c_long = 0;
    let mut day: c_long = 0;
    let mut hour: c_long = 0;
    let mut minute: c_long = 0;
    let mut second: c_long = 0;
    let mut nanos: c_long = 0;
    let mut tz: *mut PyObject = NULL();
    let mut disambiguate: *mut PyObject = str_raise;

    // FUTURE: parse them manually, which is more efficient
    if PyArg_ParseTupleAndKeywords(
        args,
        kwargs,
        c_str!("lll|llllU$U:ZonedDateTime"),
        vec![
            c_str!("year") as *mut c_char,
            c_str!("month") as *mut c_char,
            c_str!("day") as *mut c_char,
            c_str!("hour") as *mut c_char,
            c_str!("minute") as *mut c_char,
            c_str!("second") as *mut c_char,
            c_str!("nanosecond") as *mut c_char,
            c_str!("tz") as *mut c_char,
            c_str!("disambiguate") as *mut c_char,
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
        return NULL();
    }

    if tz.is_null() {
        raise!(PyExc_TypeError, "tz argument is required");
    }
    let zoneinfo = newref(py_try!(PyObject_CallOneArg(zoneinfo_type.cast(), tz)));

    // TODO: Stricter date validation due to offset?
    let date = unwrap_or_raise!(
        Date::from_longs(year, month, day),
        PyExc_ValueError,
        "Invalid date"
    );
    let time = unwrap_or_raise!(
        Time::from_longs(hour, minute, second, nanos),
        PyExc_ValueError,
        "Invalid time"
    );
    let dis = unwrap_or_raise!(
        Disambiguate::parse(pystr_to_utf8!(
            disambiguate,
            "disambiguate must be a string"
        )),
        PyExc_ValueError,
        "Invalid disambiguate value"
    );
    match ZonedDateTime::from_local(api, date, time, zoneinfo, dis) {
        Ok(dt) => new_unchecked(type_, dt).cast(),
        Err(Ambiguity::Fold) => {
            raise!(
                exc_ambiguous.cast(),
                "%s is ambiguous in timezone %U",
                format!("{} {}\0", date, time).as_ptr().cast::<c_char>(),
                tz
            );
        }
        Err(Ambiguity::Gap) => {
            raise!(
                exc_skipped.cast(),
                "%s is skipped in timezone %U",
                format!("{} {}\0", date, time).as_ptr().cast::<c_char>(),
                tz
            );
        }
    }
}

pub(crate) unsafe fn new_unchecked(type_: *mut PyTypeObject, dt: ZonedDateTime) -> *mut PyObject {
    // TODO: incref zoneinfo?
    let f: allocfunc = (*type_).tp_alloc.expect("tp_alloc is not set");
    let slf = py_try!(f(type_, 0).cast::<PyZonedDateTime>());
    ptr::addr_of_mut!((*slf).dt).write(dt);
    slf.cast()
}

unsafe extern "C" fn dealloc(slf: *mut PyObject) {
    Py_DECREF(ZonedDateTime::extract(slf).zoneinfo);
    let tp_free = PyType_GetSlot(Py_TYPE(slf), Py_tp_free);
    debug_assert_ne!(tp_free, NULL());
    let f: freefunc = std::mem::transmute(tp_free);
    f(slf.cast());
}

unsafe extern "C" fn __repr__(slf: *mut PyObject) -> *mut PyObject {
    py_str(&format!("ZonedDateTime({})", ZonedDateTime::extract(slf)))
}

unsafe extern "C" fn __str__(slf: *mut PyObject) -> *mut PyObject {
    py_str(&format!("{}", ZonedDateTime::extract(slf)))
}

unsafe extern "C" fn __richcmp__(
    a_obj: *mut PyObject,
    b_obj: *mut PyObject,
    op: c_int,
) -> *mut PyObject {
    // TODO: test reflexivity
    let type_a = Py_TYPE(a_obj);
    let type_b = Py_TYPE(b_obj);
    let inst_a = ZonedDateTime::extract(a_obj).to_instant();
    let inst_b = if type_b == type_a {
        ZonedDateTime::extract(b_obj).to_instant()
    } else if type_b == State::for_type(type_a).utc_datetime_type {
        Instant::extract(b_obj)
    } else {
        return newref(Py_NotImplemented());
    };
    py_bool(match op {
        pyo3_ffi::Py_EQ => inst_a == inst_b,
        pyo3_ffi::Py_NE => inst_a != inst_b,
        pyo3_ffi::Py_LT => inst_a < inst_b,
        pyo3_ffi::Py_LE => inst_a <= inst_b,
        pyo3_ffi::Py_GT => inst_a > inst_b,
        pyo3_ffi::Py_GE => inst_a >= inst_b,
        _ => unreachable!(),
    })
}

unsafe extern "C" fn __hash__(slf: *mut PyObject) -> Py_hash_t {
    ZonedDateTime::extract(slf).to_instant().pyhash()
}

#[inline]
unsafe extern "C" fn _shift(
    slf: *mut PyObject,
    delta_obj: *mut PyObject,
    negate: bool,
) -> *mut PyObject {
    let type_ = Py_TYPE(slf);
    let &State {
        time_delta_type,
        date_delta_type,
        datetime_api: py_api,
        ..
    } = State::for_type(type_);
    let zdt = ZonedDateTime::extract(slf);
    if Py_TYPE(delta_obj) == time_delta_type {
        let mut delta = TimeDelta::extract(delta_obj);
        if negate {
            delta = -delta;
        };
        let DateTime { date, time } = unwrap_or_raise!(
            Instant::from_nanos(zdt.to_instant().total_nanos() + delta.total_nanos()),
            PyExc_ValueError,
            "Resulting datetime is out of range"
        )
        .to_datetime();
        new_unchecked(
            type_,
            ZonedDateTime::from_utc(py_api, date, time, zdt.zoneinfo),
        )
        .cast()
    } else if Py_TYPE(delta_obj) == date_delta_type {
        let DateDelta {
            mut months,
            mut days,
        } = DateDelta::extract(delta_obj);
        if negate {
            months = -months;
            days = -days;
        };
        // Prevent re-resolving in case there is no shift.
        // otherwise, ambiguous dates may shift unexpectedly.
        if months == 0 && days == 0 {
            return newref(slf);
        }
        let ZonedDateTime {
            date,
            time,
            zoneinfo,
            ..
        } = zdt;
        let new = ZonedDateTime::from_local(
            py_api,
            unwrap_or_raise!(
                date.shift(0, months, days),
                PyExc_ValueError,
                "Resulting date is out of range"
            ),
            time,
            zoneinfo,
            Disambiguate::Compatible,
        )
        .unwrap(); // No error possible in "Compatible" mode
        new_unchecked(type_, new)
    } else {
        newref(Py_NotImplemented())
    }
}

unsafe extern "C" fn __add__(slf: *mut PyObject, arg: *mut PyObject) -> *mut PyObject {
    _shift(slf, arg, false)
}

unsafe extern "C" fn __sub__(obj_a: *mut PyObject, obj_b: *mut PyObject) -> *mut PyObject {
    let type_a = Py_TYPE(obj_a);
    let type_b = Py_TYPE(obj_b);

    // Easy case: ZonedDT - ZonedDT
    let (inst_a, inst_b) = if type_a == type_b {
        (
            ZonedDateTime::extract(obj_a).to_instant(),
            ZonedDateTime::extract(obj_b).to_instant(),
        )
    // Other cases are more difficult, as they can be triggered
    // by reflexive operations with arbitrary types.
    // We need to eliminate them carefully.
    } else {
        let mod_a = PyType_GetModule(type_a);
        let mod_b = PyType_GetModule(type_b);
        if mod_a == mod_b {
            // at this point we know that `a` is a `ZonedDT`
            let inst_a = ZonedDateTime::extract(obj_a).to_instant();
            let inst_b = if type_b == State::for_mod(mod_a).utc_datetime_type {
                Instant::extract(obj_b)
            } else if type_b == State::for_mod(mod_a).offset_datetime_type {
                OffsetDateTime::extract(obj_b).to_instant()
            } else if type_b == State::for_mod(mod_a).local_datetime_type {
                OffsetDateTime::extract(obj_b).to_instant()
            } else {
                return _shift(obj_a, obj_b, true);
            };
            (inst_a, inst_b)
        } else {
            return newref(Py_NotImplemented());
        }
    };
    time_delta::new_unchecked(
        State::for_type(type_a).time_delta_type,
        TimeDelta::from_nanos_unchecked(inst_a.total_nanos() - inst_b.total_nanos()),
    )
}

static mut SLOTS: &[PyType_Slot] = &[
    PyType_Slot {
        slot: Py_tp_new,
        pfunc: __new__ as *mut c_void,
    },
    PyType_Slot {
        slot: Py_tp_doc,
        pfunc: "A datetime type with IANA tz ID\0".as_ptr() as *mut c_void,
    },
    PyType_Slot {
        slot: Py_tp_str,
        pfunc: __str__ as *mut c_void,
    },
    PyType_Slot {
        slot: Py_tp_repr,
        pfunc: __repr__ as *mut c_void,
    },
    PyType_Slot {
        slot: Py_tp_richcompare,
        pfunc: __richcmp__ as *mut c_void,
    },
    PyType_Slot {
        slot: Py_nb_add,
        pfunc: __add__ as *mut c_void,
    },
    PyType_Slot {
        slot: Py_nb_subtract,
        pfunc: __sub__ as *mut c_void,
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

unsafe extern "C" fn exact_eq(obj_a: *mut PyObject, obj_b: *mut PyObject) -> *mut PyObject {
    if Py_TYPE(obj_a) == Py_TYPE(obj_b) {
        newref(py_bool(
            ZonedDateTime::extract(obj_a) == ZonedDateTime::extract(obj_b),
        ))
    } else {
        raise!(
            PyExc_TypeError,
            "Argument must be ZonedDateTime, got %R",
            obj_b
        )
    }
}

unsafe extern "C" fn in_tz(slf: *mut PyObject, tz: *mut PyObject) -> *mut PyObject {
    let type_ = Py_TYPE(slf);
    let &State {
        zoneinfo_type,
        datetime_api: py_api,
        ..
    } = State::for_type(type_);
    let new_zoneinfo = newref(py_try!(PyObject_CallOneArg(zoneinfo_type.cast(), tz)));
    let zdt = ZonedDateTime::extract(slf);
    let ZonedDateTime { date, time, .. } = zdt.small_naive_shift(-zdt.offset_secs);

    new_unchecked(
        type_,
        ZonedDateTime::from_utc(py_api, date, time, new_zoneinfo),
    )
    .cast()
}

pub(crate) unsafe extern "C" fn unpickle(
    module: *mut PyObject,
    args: *mut *mut PyObject,
    nargs: Py_ssize_t,
) -> *mut PyObject {
    if PyVectorcall_NARGS(nargs as usize) != 2 {
        raise!(PyExc_TypeError, "Invalid pickle data");
    }
    let &State {
        zoneinfo_type,
        zoned_datetime_type,
        ..
    } = State::for_mod(module);
    let mut packed = pybytes_extract!(*args);
    let zoneinfo = PyObject_CallOneArg(zoneinfo_type.cast(), *args.offset(1));
    let new = new_unchecked(
        zoned_datetime_type,
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
        },
    );
    if !packed.is_empty() {
        raise!(PyExc_ValueError, "Invalid pickle data");
    }
    new
}

unsafe extern "C" fn py_datetime(slf: *mut PyObject, _: *mut PyObject) -> *mut PyObject {
    let ZonedDateTime {
        date: Date { year, month, day },
        time:
            Time {
                hour,
                minute,
                second,
                nanos,
            },
        zoneinfo,
        ..
    } = ZonedDateTime::extract(slf);
    let &State {
        datetime_api: api, ..
    } = State::for_type(Py_TYPE(slf));
    (api.DateTime_FromDateAndTimeAndFold)(
        year.into(),
        month.into(),
        day.into(),
        hour.into(),
        minute.into(),
        second.into(),
        (nanos / 1_000) as c_int,
        zoneinfo,
        0,
        api.DateTimeType,
    )
}

unsafe extern "C" fn in_utc(slf: *mut PyObject, _: *mut PyObject) -> *mut PyObject {
    utc_datetime::new_unchecked(
        State::for_obj(slf).utc_datetime_type,
        ZonedDateTime::extract(slf).to_instant(),
    )
}

unsafe extern "C" fn in_fixed_offset(
    slf_obj: *mut PyObject,
    args: *mut *mut PyObject,
    nargs: Py_ssize_t,
) -> *mut PyObject {
    let cls = Py_TYPE(slf_obj);
    let slf = ZonedDateTime::extract(slf_obj);
    let &State {
        offset_datetime_type,
        time_delta_type,
        ..
    } = State::for_type(cls);
    if nargs == 0 {
        return offset_datetime::new_unchecked(
            offset_datetime_type,
            OffsetDateTime {
                date: slf.date,
                time: slf.time,
                offset_secs: slf.offset_secs,
            },
        );
    } else if nargs > 1 {
        raise!(
            PyExc_TypeError,
            "in_fixed_offset() takes at most 1 argument"
        );
    }
    let offset_secs = to_py!(offset_datetime::extract_offset(*args, time_delta_type,));
    let ZonedDateTime { date, time, .. } = slf.small_naive_shift(offset_secs - slf.offset_secs);
    offset_datetime::new_unchecked(
        offset_datetime_type,
        OffsetDateTime {
            date,
            time,
            offset_secs,
        },
    )
}

unsafe extern "C" fn in_local_system(slf: *mut PyObject, _: *mut PyObject) -> *mut PyObject {
    let &State {
        datetime_api: py_api,
        local_datetime_type,
        ..
    } = State::for_obj(slf);
    local_datetime::new_unchecked(
        local_datetime_type,
        ZonedDateTime::extract(slf)
            .to_offset()
            .to_local_system(py_api),
    )
}

unsafe extern "C" fn date(slf: *mut PyObject, _: *mut PyObject) -> *mut PyObject {
    date::new_unchecked(
        State::for_obj(slf).date_type,
        ZonedDateTime::extract(slf).date,
    )
}

unsafe extern "C" fn time(slf: *mut PyObject, _: *mut PyObject) -> *mut PyObject {
    time::new_unchecked(
        State::for_obj(slf).time_type,
        ZonedDateTime::extract(slf).time,
    )
}

unsafe extern "C" fn with_date(
    slf: *mut PyObject,
    cls: *mut PyTypeObject,
    args: *const *mut PyObject,
    nargs: Py_ssize_t,
    kwnames: *mut PyObject,
) -> *mut PyObject {
    let &State {
        date_type,
        datetime_api: py_api,
        str_disambiguate,
        exc_skipped,
        exc_ambiguous,
        ..
    } = State::for_obj(slf);

    if PyVectorcall_NARGS(nargs as usize) != 1 {
        raise!(
            PyExc_TypeError,
            "with_date() takes 1 positional argument but %lld were given",
            nargs
        );
    }

    let dis = if kwnames.is_null() || PyTuple_GET_SIZE(kwnames) == 0 {
        Disambiguate::Raise
    } else if PyTuple_GET_SIZE(kwnames) > 1 {
        raise!(
            PyExc_TypeError,
            "with_date() expected at most 2 arguments, got %lld",
            PyTuple_GET_SIZE(kwnames) + 1
        );
    } else if PyTuple_GET_ITEM(kwnames, 0) == str_disambiguate {
        unwrap_or_raise!(
            Disambiguate::parse(pystr_to_utf8!(
                *args.offset(1),
                "disambiguate must be a string"
            )),
            PyExc_ValueError,
            "Invalid disambiguate value"
        )
    } else {
        raise!(
            PyExc_TypeError,
            "with_date() got an unexpected keyword argument %R",
            PyTuple_GET_ITEM(kwnames, 0)
        );
    };

    let ZonedDateTime { time, zoneinfo, .. } = ZonedDateTime::extract(slf);
    if Py_TYPE(*args) == date_type {
        match ZonedDateTime::from_local(py_api, Date::extract(*args), time, zoneinfo, dis) {
            Ok(d) => new_unchecked(cls, d).cast(),
            Err(Ambiguity::Fold) => raise!(
                exc_ambiguous.cast(),
                "The new date is ambiguous in the current timezone"
            ),
            Err(Ambiguity::Gap) => raise!(
                exc_skipped.cast(),
                "The new date is skipped in the current timezone"
            ),
        }
    } else {
        raise!(PyExc_TypeError, "date must be a Date instance");
    }
}

unsafe extern "C" fn with_time(
    slf: *mut PyObject,
    cls: *mut PyTypeObject,
    args: *const *mut PyObject,
    nargs: Py_ssize_t,
    kwnames: *mut PyObject,
) -> *mut PyObject {
    let &State {
        time_type,
        datetime_api: py_api,
        str_disambiguate,
        exc_skipped,
        exc_ambiguous,
        ..
    } = State::for_obj(slf);

    if PyVectorcall_NARGS(nargs as usize) != 1 {
        raise!(
            PyExc_TypeError,
            "with_time() takes 1 positional argument but %lld were given",
            nargs
        );
    }

    let dis = if kwnames.is_null() || PyTuple_GET_SIZE(kwnames) == 0 {
        Disambiguate::Raise
    } else if PyTuple_GET_SIZE(kwnames) > 1 {
        raise!(
            PyExc_TypeError,
            "with_time() expected at most 2 arguments, got %lld",
            PyTuple_GET_SIZE(kwnames) + 1
        );
    } else if PyTuple_GET_ITEM(kwnames, 0) == str_disambiguate {
        unwrap_or_raise!(
            Disambiguate::parse(pystr_to_utf8!(
                *args.offset(1),
                "disambiguate must be a string"
            )),
            PyExc_ValueError,
            "Invalid disambiguate value"
        )
    } else {
        raise!(
            PyExc_TypeError,
            "with_time() got an unexpected keyword argument %R",
            PyTuple_GET_ITEM(kwnames, 0)
        );
    };

    let ZonedDateTime { date, zoneinfo, .. } = ZonedDateTime::extract(slf);
    if Py_TYPE(*args) == time_type {
        match ZonedDateTime::from_local(py_api, date, Time::extract(*args), zoneinfo, dis) {
            Ok(d) => new_unchecked(cls, d).cast(),
            Err(Ambiguity::Fold) => raise!(
                exc_ambiguous.cast(),
                "The new time is ambiguous in the current timezone"
            ),
            Err(Ambiguity::Gap) => raise!(
                exc_skipped.cast(),
                "The new time is skipped in the current timezone"
            ),
        }
    } else {
        raise!(PyExc_TypeError, "time must be a Time instance");
    }
}

unsafe extern "C" fn default_format(slf: *mut PyObject, _: *mut PyObject) -> *mut PyObject {
    __str__(slf)
}

unsafe extern "C" fn replace(
    slf: *mut PyObject,
    type_: *mut PyTypeObject,
    args: *const *mut PyObject,
    nargs: Py_ssize_t,
    kwnames: *mut PyObject,
) -> *mut PyObject {
    if PyVectorcall_NARGS(nargs as usize) != 0 {
        raise!(PyExc_TypeError, "replace() takes no positional arguments");
    }
    let &State {
        str_year,
        str_month,
        str_day,
        str_hour,
        str_minute,
        str_second,
        str_nanosecond,
        str_tz,
        str_disambiguate,
        datetime_api: py_api,
        exc_skipped,
        exc_ambiguous,
        zoneinfo_type,
        ..
    } = State::for_type(type_);
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
    let mut nanos = time.nanos.into();
    let mut dis = Disambiguate::Raise;

    if !kwnames.is_null() {
        for i in 0..=Py_SIZE(kwnames).saturating_sub(1) {
            let name = PyTuple_GET_ITEM(kwnames, i);
            let value = *args.offset(i);
            if name == str_year {
                year = pyint_as_long!(value);
            } else if name == str_month {
                month = pyint_as_long!(value);
            } else if name == str_day {
                day = pyint_as_long!(value);
            } else if name == str_hour {
                hour = pyint_as_long!(value);
            } else if name == str_minute {
                minute = pyint_as_long!(value);
            } else if name == str_second {
                second = pyint_as_long!(value);
            } else if name == str_nanosecond {
                nanos = pyint_as_long!(value);
            } else if name == str_tz {
                zoneinfo = py_try!(PyObject_CallOneArg(zoneinfo_type.cast(), value));
            } else if name == str_disambiguate {
                dis = unwrap_or_raise!(
                    Disambiguate::parse(pystr_to_utf8!(value, "disambiguate must be a string")),
                    PyExc_ValueError,
                    "Invalid disambiguate value"
                );
            } else {
                raise!(
                    PyExc_TypeError,
                    "replace() got an unexpected keyword argument %R",
                    name
                );
            }
        }
    };
    let date = unwrap_or_raise!(
        Date::from_longs(year, month, day),
        PyExc_ValueError,
        "Invalid date"
    );
    let time = unwrap_or_raise!(
        Time::from_longs(hour, minute, second, nanos),
        PyExc_ValueError,
        "Invalid time"
    );
    match ZonedDateTime::from_local(py_api, date, time, zoneinfo, dis) {
        Ok(d) => new_unchecked(type_, d).cast(),
        Err(Ambiguity::Fold) => {
            raise!(
                exc_ambiguous.cast(),
                "%s is ambiguous in timezone %U",
                format!("{} {}\0", date, time).as_ptr().cast::<c_char>(),
                PyObject_GetAttrString(zoneinfo, c_str!("key"))
            );
        }
        Err(Ambiguity::Gap) => {
            raise!(
                exc_skipped.cast(),
                "%s is skipped in timezone %U",
                format!("{} {}\0", date, time).as_ptr().cast::<c_char>(),
                PyObject_GetAttrString(zoneinfo, c_str!("key"))
            );
        }
    }
}

unsafe extern "C" fn now(cls: *mut PyObject, tz: *mut PyObject) -> *mut PyObject {
    let &State {
        datetime_api:
            &PyDateTime_CAPI {
                DateTime_FromTimestamp,
                DateTimeType,
                ..
            },
        zoneinfo_type,
        ..
    } = State::for_type(cls.cast());
    let zoneinfo = py_try!(PyObject_CallOneArg(zoneinfo_type.cast(), tz));
    let (timestamp, subsec) = match SystemTime::now().duration_since(SystemTime::UNIX_EPOCH) {
        Ok(dur) => (dur.as_secs() as f64, dur.subsec_nanos()),
        _ => raise!(PyExc_OSError, "SystemTime before UNIX EPOCH"),
    };
    // TODO: faster way without fromtimestamp?
    let dt = py_try!(DateTime_FromTimestamp(
        DateTimeType,
        PyTuple_Pack(2, PyFloat_FromDouble(timestamp), zoneinfo),
        NULL()
    ));
    new_unchecked(
        cls.cast(),
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
            offset_secs: offset_from_py_dt(dt),
            zoneinfo,
        },
    )
    .cast()
}

// TODO: can remove?
unsafe fn _is_skipped_time(
    &PyDateTime_CAPI {
        DateTimeType,
        DateTime_FromDateAndTimeAndFold,
        ..
    }: &PyDateTime_CAPI,
    dt: *mut PyObject,
) -> bool {
    let fold = PyDateTime_DATE_GET_FOLD(dt);
    let other_dt = DateTime_FromDateAndTimeAndFold(
        PyDateTime_GET_YEAR(dt),
        PyDateTime_GET_MONTH(dt),
        PyDateTime_GET_DAY(dt),
        PyDateTime_DATE_GET_HOUR(dt),
        PyDateTime_DATE_GET_MINUTE(dt),
        PyDateTime_DATE_GET_SECOND(dt),
        0,
        PyDateTime_DATE_GET_TZINFO(dt),
        if fold == 0 { 1 } else { 0 },
        DateTimeType,
    );
    let (dt0, dt1) = if fold == 0 {
        (dt, other_dt)
    } else {
        (other_dt, dt)
    };
    let offset0 = offset_from_py_dt(dt0);
    let offset1 = offset_from_py_dt(dt1);
    Py_DECREF(other_dt);
    offset0 < offset1
}

unsafe extern "C" fn from_py_datetime(cls: *mut PyObject, dt: *mut PyObject) -> *mut PyObject {
    let &State {
        datetime_api: py_api,
        zoneinfo_type,
        exc_skipped,
        ..
    } = State::for_type(cls.cast());
    if PyDateTime_Check(dt) == 0 {
        raise!(
            PyExc_TypeError,
            "Argument must be a datetime.datetime instance"
        );
    }
    let tzinfo = PyDateTime_DATE_GET_TZINFO(dt);
    if PyObject_IsInstance(tzinfo, zoneinfo_type.cast()) == 0 {
        raise!(
            PyExc_ValueError,
            "tzinfo must be a ZoneInfo, got %R",
            tzinfo
        );
    }

    // TODO: simply handle skipped time according to fold
    if _is_skipped_time(py_api, dt) {
        raise!(
            exc_skipped.cast(),
            "The datetime %S is skipped in the timezone %R",
            dt,
            PyObject_GetAttrString(tzinfo, c_str!("key"))
        );
    }

    new_unchecked(
        cls.cast(),
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
                nanos: PyDateTime_DATE_GET_MICROSECOND(dt) as u32 * 1_000,
            },
            offset_secs: offset_from_py_dt(dt),
            zoneinfo: tzinfo,
        },
    )
    .cast()
}

unsafe extern "C" fn naive(slf: *mut PyObject, _: *mut PyObject) -> *mut PyObject {
    let ZonedDateTime { date, time, .. } = ZonedDateTime::extract(slf);
    naive_datetime::new_unchecked(
        State::for_obj(slf).naive_datetime_type,
        DateTime { date, time },
    )
    .cast()
}

unsafe extern "C" fn timestamp(slf: *mut PyObject, _: *mut PyObject) -> *mut PyObject {
    PyLong_FromLongLong(ZonedDateTime::extract(slf).to_instant().timestamp())
}

unsafe extern "C" fn timestamp_millis(slf: *mut PyObject, _: *mut PyObject) -> *mut PyObject {
    PyLong_FromLongLong(ZonedDateTime::extract(slf).to_instant().timestamp_millis())
}

unsafe extern "C" fn timestamp_nanos(slf: *mut PyObject, _: *mut PyObject) -> *mut PyObject {
    py_int128(ZonedDateTime::extract(slf).to_instant().timestamp_nanos())
}

unsafe extern "C" fn __reduce__(slf: *mut PyObject, _: *mut PyObject) -> *mut PyObject {
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
    PyTuple_Pack(
        2,
        State::for_obj(slf).unpickle_zoned_datetime,
        py_try!(PyTuple_Pack(
            2,
            py_bytes(&pack![
                year,
                month,
                day,
                hour,
                minute,
                second,
                nanos,
                offset_secs
            ]),
            PyObject_GetAttrString(zoneinfo, c_str!("key"))
        )),
    )
}

// checks the args comply with (ts, /, *, tz: str)
unsafe fn check_from_timestamp_args_return_zoneinfo(
    args: *const *mut PyObject,
    nargs: Py_ssize_t,
    kwnames: *mut PyObject,
    &State {
        zoneinfo_type,
        str_tz,
        ..
    }: &State,
) -> *mut PyObject {
    if PyVectorcall_NARGS(nargs as usize) != 1 {
        raise!(
            PyExc_TypeError,
            "from_timestamp() takes 1 positional argument but %lld were given",
            nargs
        );
    };
    let nkwargs = if kwnames.is_null() {
        0
    } else {
        PyTuple_GET_SIZE(kwnames)
    };
    if nkwargs != 1 {
        raise!(
            PyExc_TypeError,
            "from_timestamp() expected 2 arguments, got %lld",
            nargs + nkwargs
        );
    } else if PyTuple_GET_ITEM(kwnames, 0) == str_tz {
        py_try!(PyObject_CallOneArg(zoneinfo_type.cast(), *args.offset(1)))
    } else {
        raise!(
            PyExc_TypeError,
            "from_timestamp() got an unexpected keyword argument %R",
            PyTuple_GET_ITEM(kwnames, 0)
        );
    }
}

unsafe extern "C" fn from_timestamp(
    _: *mut PyObject,
    cls: *mut PyTypeObject,
    args: *const *mut PyObject,
    nargs: Py_ssize_t,
    kwnames: *mut PyObject,
) -> *mut PyObject {
    let state = State::for_type(cls);
    let zoneinfo = py_try!(check_from_timestamp_args_return_zoneinfo(
        args, nargs, kwnames, state
    ));
    let DateTime { date, time } = unwrap_or_raise!(
        Instant::from_timestamp(pyint_as_i64!(*args)),
        PyExc_ValueError,
        "timestamp is out of range"
    )
    .to_datetime();
    new_unchecked(
        cls,
        ZonedDateTime::from_utc(state.datetime_api, date, time, zoneinfo),
    )
    .cast()
}

unsafe extern "C" fn from_timestamp_millis(
    _: *mut PyObject,
    cls: *mut PyTypeObject,
    args: *const *mut PyObject,
    nargs: Py_ssize_t,
    kwnames: *mut PyObject,
) -> *mut PyObject {
    let state = State::for_type(cls);
    let zoneinfo = py_try!(check_from_timestamp_args_return_zoneinfo(
        args, nargs, kwnames, state
    ));
    let DateTime { date, time } = unwrap_or_raise!(
        Instant::from_timestamp_millis(pyint_as_i64!(*args)),
        PyExc_ValueError,
        "timestamp is out of range"
    )
    .to_datetime();
    new_unchecked(
        cls,
        ZonedDateTime::from_utc(state.datetime_api, date, time, zoneinfo),
    )
    .cast()
}

unsafe extern "C" fn from_timestamp_nanos(
    _: *mut PyObject,
    cls: *mut PyTypeObject,
    args: *const *mut PyObject,
    nargs: Py_ssize_t,
    kwnames: *mut PyObject,
) -> *mut PyObject {
    let state = State::for_type(cls);
    let zoneinfo = py_try!(check_from_timestamp_args_return_zoneinfo(
        args, nargs, kwnames, state
    ));
    let DateTime { date, time } = unwrap_or_raise!(
        Instant::from_timestamp_nanos(i128_extract!(*args, "timestamp must be an integer")),
        PyExc_ValueError,
        "timestamp is out of range"
    )
    .to_datetime();
    new_unchecked(
        cls,
        ZonedDateTime::from_utc(state.datetime_api, date, time, zoneinfo),
    )
    .cast()
}

unsafe extern "C" fn is_ambiguous(slf: *mut PyObject, _: *mut PyObject) -> *mut PyObject {
    let ZonedDateTime {
        date,
        time,
        zoneinfo,
        ..
    } = ZonedDateTime::extract(slf);
    py_bool(
        match OffsetResult::for_tz(State::for_obj(slf).datetime_api, date, time, zoneinfo) {
            OffsetResult::Fold(_, _) => true,
            _ => false,
        },
    )
}

// parse ±HH:MM[:SS] (consuming as much as possible of the input)
fn parse_offset_partial(s: &mut &[u8]) -> Option<i32> {
    debug_assert!(s.len() >= 6);
    if s[3] != b':' {
        return None;
    }
    // the sign (always present)
    let sign = match s[0] {
        b'+' => 1,
        b'-' => -1,
        _ => return None,
    };
    // the HH:MM part
    // FUTURE: technically, this eliminates 2x:00 offsets. There
    // are no such offsets in the IANA database, but they are possible...
    let secs = (get_digit!(s, 1, ..=b'1') * 10 + get_digit!(s, 2)) as i32 * 3600
        + (get_digit!(s, 4, ..=b'5') * 10 + get_digit!(s, 5)) as i32 * 60;
    // the optional seconds part
    match s.get(6) {
        Some(b':') => {
            if s.len() > 8 {
                let result =
                    Some(secs + get_digit!(s, 7, ..=b'5') as i32 * 10 + get_digit!(s, 8) as i32);
                *s = &s[9..];
                result
            } else {
                None
            }
        }
        _ => {
            *s = &s[6..]; // TODO does this work for the empty case?
            Some(secs)
        }
    }
    .map(|s| sign * s)
}

unsafe extern "C" fn from_default_format(
    cls: *mut PyObject,
    s_obj: *mut PyObject,
) -> *mut PyObject {
    let s = &mut pystr_to_utf8!(s_obj, "Expected a string");
    // at least: "YYYY-MM-DD HH:MM:SS+HH:MM[?]"
    if s.len() < 28 || s[10] != b' ' {
        raise!(PyExc_ValueError, "Invalid format: %R", s_obj);
    }
    let date = unwrap_or_raise!(
        Date::parse_partial(s),
        PyExc_ValueError,
        "Invalid format: %R",
        s_obj
    );
    *s = &s[1..]; // skip the separator
    let time = unwrap_or_raise!(
        Time::parse_partial(s),
        PyExc_ValueError,
        "Invalid format: %R",
        s_obj
    );

    // at least "+HH:MM"
    if s.len() < 6 {
        raise!(PyExc_ValueError, "Invalid format: %R", s_obj);
    }
    let offset_secs = unwrap_or_raise!(
        parse_offset_partial(s),
        PyExc_ValueError,
        "Invalid format: %R",
        s_obj
    );
    if s.len() < 3 || s[0] != b'[' || s[s.len() - 1] != b']' {
        raise!(PyExc_ValueError, "Invalid format: %R", s_obj);
    }
    let &State {
        datetime_api: py_api,
        zoneinfo_type,
        exc_invalid_offset,
        ..
    } = State::for_type(cls.cast());
    let zoneinfo = py_try!(PyObject_CallOneArg(
        zoneinfo_type.cast(),
        py_str(std::str::from_utf8_unchecked(&s[1..s.len() - 1])),
    ));
    let offset_invalid = match OffsetResult::for_tz(py_api, date, time, zoneinfo) {
        OffsetResult::Unambiguous(o) => o != offset_secs,
        OffsetResult::Gap(o1, o2) | OffsetResult::Fold(o1, o2) => {
            o1 != offset_secs && o2 != offset_secs
        }
    };
    if offset_invalid {
        raise!(
            exc_invalid_offset.cast(),
            "Invalid offset for timezone %R",
            zoneinfo
        );
    }
    new_unchecked(
        cls.cast(),
        ZonedDateTime {
            date,
            time,
            offset_secs,
            zoneinfo,
        },
    )
}

static mut METHODS: &[PyMethodDef] = &[
    method!(identity named "__copy__", ""),
    method!(identity named "__deepcopy__", "", METH_O),
    method!(in_tz, "Convert to a `ZonedDateTime` with given tz", METH_O),
    method!(exact_eq, "Exact equality", METH_O),
    method!(py_datetime, "Convert to a `datetime.datetime`"),
    method!(in_utc, "Convert to a `UTCDateTime`"),
    method!(in_local_system, "Convert to a datetime in the local system"),
    method!(date, "The date component"),
    method!(time, "The time component"),
    method!(default_format, "Format as a string"),
    method!(__reduce__, ""),
    classmethod!(
        now,
        "Create a new instance representing the current time",
        METH_O
    ),
    classmethod!(
        from_py_datetime,
        "Create a new instance from a `datetime.datetime`",
        METH_O
    ),
    method!(naive, "Convert to a `NaiveDateTime`"),
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
    classmethod!(from_default_format, "", METH_O),
    PyMethodDef {
        ml_name: c_str!("from_timestamp"),
        ml_meth: PyMethodDefPointer {
            PyCMethod: from_timestamp,
        },
        ml_flags: METH_CLASS | METH_METHOD | METH_FASTCALL | METH_KEYWORDS,
        ml_doc: c_str!("Create a new instance from a UNIX timestamp"),
    },
    PyMethodDef {
        ml_name: c_str!("from_timestamp_millis"),
        ml_meth: PyMethodDefPointer {
            PyCMethod: from_timestamp_millis,
        },
        ml_flags: METH_CLASS | METH_METHOD | METH_FASTCALL | METH_KEYWORDS,
        ml_doc: c_str!("Create a new instance from a UNIX timestamp in milliseconds"),
    },
    PyMethodDef {
        ml_name: c_str!("from_timestamp_nanos"),
        ml_meth: PyMethodDefPointer {
            PyCMethod: from_timestamp_nanos,
        },
        ml_flags: METH_CLASS | METH_METHOD | METH_FASTCALL | METH_KEYWORDS,
        ml_doc: c_str!("Create a new instance from a UNIX timestamp in nanoseconds"),
    },
    PyMethodDef {
        ml_name: c_str!("replace"),
        ml_meth: PyMethodDefPointer { PyCMethod: replace },
        ml_flags: METH_METHOD | METH_FASTCALL | METH_KEYWORDS,
        ml_doc: c_str!("Return a new instance with the specified fields replaced"),
    },
    PyMethodDef {
        ml_name: c_str!("with_date"),
        ml_meth: PyMethodDefPointer {
            PyCMethod: with_date,
        },
        ml_flags: METH_METHOD | METH_FASTCALL | METH_KEYWORDS,
        ml_doc: c_str!("Return a new instance with the date replaced"),
    },
    PyMethodDef {
        ml_name: c_str!("with_time"),
        ml_meth: PyMethodDefPointer {
            PyCMethod: with_time,
        },
        ml_flags: METH_METHOD | METH_FASTCALL | METH_KEYWORDS,
        ml_doc: c_str!("Return a new instance with the time replaced"),
    },
    PyMethodDef {
        ml_name: c_str!("in_fixed_offset"),
        ml_meth: PyMethodDefPointer {
            _PyCFunctionFast: in_fixed_offset,
        },
        ml_flags: METH_FASTCALL,
        ml_doc: c_str!("Convert to an equivalent offset datetime"),
    },
    PyMethodDef::zeroed(),
];

unsafe extern "C" fn get_year(slf: *mut PyObject, _: *mut c_void) -> *mut PyObject {
    PyLong_FromLong(ZonedDateTime::extract(slf).date.year.into())
}

unsafe extern "C" fn get_month(slf: *mut PyObject, _: *mut c_void) -> *mut PyObject {
    PyLong_FromLong(ZonedDateTime::extract(slf).date.month.into())
}

unsafe extern "C" fn get_day(slf: *mut PyObject, _: *mut c_void) -> *mut PyObject {
    PyLong_FromLong(ZonedDateTime::extract(slf).date.day.into())
}

unsafe extern "C" fn get_hour(slf: *mut PyObject, _: *mut c_void) -> *mut PyObject {
    PyLong_FromLong(ZonedDateTime::extract(slf).time.hour.into())
}

unsafe extern "C" fn get_minute(slf: *mut PyObject, _: *mut c_void) -> *mut PyObject {
    PyLong_FromLong(ZonedDateTime::extract(slf).time.minute.into())
}

unsafe extern "C" fn get_second(slf: *mut PyObject, _: *mut c_void) -> *mut PyObject {
    PyLong_FromLong(ZonedDateTime::extract(slf).time.second.into())
}

unsafe extern "C" fn get_nanos(slf: *mut PyObject, _: *mut c_void) -> *mut PyObject {
    PyLong_FromLong(ZonedDateTime::extract(slf).time.nanos as _)
}

unsafe extern "C" fn get_tz(slf: *mut PyObject, _: *mut c_void) -> *mut PyObject {
    newref(PyObject_GetAttrString(
        ZonedDateTime::extract(slf).zoneinfo,
        c_str!("key"),
    ))
}

unsafe extern "C" fn get_offset(slf: *mut PyObject, _: *mut c_void) -> *mut PyObject {
    time_delta::new_unchecked(
        State::for_type(Py_TYPE(slf)).time_delta_type,
        time_delta::TimeDelta::from_secs_unchecked(ZonedDateTime::extract(slf).offset_secs as i64),
    )
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

pub(crate) static mut SPEC: PyType_Spec = PyType_Spec {
    name: c_str!("whenever.ZonedDateTime"),
    basicsize: mem::size_of::<PyZonedDateTime>() as _,
    itemsize: 0,
    flags: Py_TPFLAGS_DEFAULT as _,
    slots: unsafe { SLOTS as *const [_] as *mut _ },
};
