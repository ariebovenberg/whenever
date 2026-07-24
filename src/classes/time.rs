#[cfg(test)]
use crate::common::{fmt::Sink, parse::Scan};
use crate::{
    classes::plain_datetime::PlainDateTime,
    common::{fmt, pattern, pickle, round, scalar::*},
    docstrings as doc,
    py::*,
    pymodule::State,
};
use core::ffi::{CStr, c_int, c_long, c_void};
use pyo3_ffi::*;
use std::ptr::null_mut as NULL;

pub use crate::domain::time::Time;
pub(crate) use crate::domain::time::TimeBoundaryUnit;

impl Time {
    pub(crate) fn to_stdlib_time(
        self,
        &PyDateTime_CAPI {
            Time_FromTime,
            TimeType,
            ..
        }: &PyDateTime_CAPI,
    ) -> PyReturn {
        let Time {
            hour,
            minute,
            second,
            subsec,
        } = self;
        // SAFETY: calling C API with valid arguments
        unsafe {
            Time_FromTime(
                hour.into(),
                minute.into(),
                second.into(),
                (subsec.get() / 1_000) as c_int,
                Py_None(),
                TimeType,
            )
        }
        .own()
    }

    pub(crate) const fn python_hash(self) -> Py_hash_t {
        #[cfg(target_pointer_width = "64")]
        {
            ((self.hour as Py_hash_t) << 48)
                | ((self.minute as Py_hash_t) << 40)
                | ((self.second as Py_hash_t) << 32)
                | (self.subsec.get() as Py_hash_t)
        }
        #[cfg(target_pointer_width = "32")]
        {
            hash_combine(
                (self.hour as Py_hash_t) << 16
                    | (self.minute as Py_hash_t) << 8
                    | (self.second as Py_hash_t),
                self.subsec.get() as Py_hash_t,
            )
        }
    }

    pub(crate) fn from_longs(
        hour: c_long,
        minute: c_long,
        second: c_long,
        nanos: c_long,
    ) -> Option<Self> {
        if (0..24).contains(&hour) && (0..60).contains(&minute) && (0..60).contains(&second) {
            Some(Time {
                hour: hour as u8,
                minute: minute as u8,
                second: second as u8,
                subsec: SubSecNanos::from_long(nanos)?,
            })
        } else {
            None
        }
    }

    pub(crate) fn from_stdlib_time(t: PyTime) -> Self {
        Time {
            hour: t.hour() as _,
            minute: t.minute() as _,
            second: t.second() as _,
            // SAFETY: microseconds are always sub-second
            subsec: SubSecNanos::new_unchecked((t.microsecond() * 1_000) as _),
        }
    }

    pub(crate) fn from_stdlib_datetime(dt: PyDateTime) -> Self {
        Time {
            hour: dt.hour() as _,
            minute: dt.minute() as _,
            second: dt.second() as _,
            // SAFETY: microseconds are always sub-second
            subsec: SubSecNanos::new_unchecked((dt.microsecond() * 1_000) as _),
        }
    }
}

impl PyPayload for Time {}

pub(crate) const SINGLETONS: &[(&CStr, Time); 4] = &[
    (c"MIN", Time::MIN),
    (c"MIDNIGHT", Time::MIN),
    (
        c"NOON",
        Time {
            hour: 12,
            minute: 0,
            second: 0,
            subsec: SubSecNanos::MIN,
        },
    ),
    (c"MAX", Time::MAX),
];

fn __new__(cls: PyClass<Time>, args: PyTuple, kwargs: Option<PyDict>) -> PyReturn {
    if args.len() == 1 && kwargs.map_or(0, |d| d.len()) == 0 {
        let obj = args.iter().next().unwrap();
        if PyStr::isinstance(obj) {
            return parse_iso(cls, obj);
        }
        if let Some(t) = obj.cast_allow_subclass::<PyTime>() {
            return Time::from_stdlib_time(t).to_obj(cls);
        }
    }
    let mut hour: c_long = 0;
    let mut minute: c_long = 0;
    let mut second: c_long = 0;
    let mut nanosecond: c_long = 0;

    parse_args_kwargs!(
        args,
        kwargs,
        c"|lll$l:Time",
        hour,
        minute,
        second,
        nanosecond
    );

    Time::from_longs(hour, minute, second, nanosecond)
        .ok_or_value_err("invalid time component value")?
        .to_obj(cls)
}

extern "C" fn __hash__(slf: PyObj) -> Py_hash_t {
    // SAFETY: self type is always passed to __hash__
    hashmask(unsafe { slf.assume_heaptype::<Time>() }.1.python_hash())
}

fn __richcmp__(cls: PyClass<Time>, slf: Time, arg: PyObj, op: c_int) -> PyReturn {
    match arg.extract(cls) {
        Some(b) => CompareOp::from_ffi(op).apply(slf, b).to_py(),
        None => not_implemented(),
    }
}

fn __str__(_: PyType, slf: Time) -> PyReturn {
    PyAsciiStrBuilder::format(slf.iso_format(fmt::Precision::Auto, false))
}

fn __repr__(_: PyType, slf: Time) -> PyReturn {
    PyAsciiStrBuilder::format((
        b"Time(\"",
        slf.iso_format(fmt::Precision::Auto, false),
        b"\")",
    ))
}

#[allow(static_mut_refs)]
static mut SLOTS: &[PyType_Slot] = &[
    slotmethod!(Time, Py_tp_new, __new__),
    slotmethod!(Time, Py_tp_str, __str__, 1),
    slotmethod!(Time, Py_tp_repr, __repr__, 1),
    slotmethod!(Time, Py_tp_richcompare, __richcmp__),
    PyType_Slot {
        slot: Py_tp_doc,
        pfunc: doc::TIME.as_ptr() as *mut c_void,
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
        slot: Py_tp_hash,
        pfunc: __hash__ as *mut c_void,
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

fn to_stdlib(cls: PyClass<Time>, slf: Time) -> PyReturn {
    slf.to_stdlib_time(cls.state().py_api()?)
}

fn py_time(cls: PyClass<Time>, slf: Time) -> PyReturn {
    warn_with_class(
        *cls.state().warn_deprecation,
        c"py_time() is deprecated. Use to_stdlib() instead.",
        1,
    )?;
    to_stdlib(cls, slf)
}

fn from_py_time(cls: PyClass<Time>, arg: PyObj) -> PyReturn {
    warn_with_class(
        *cls.state().warn_deprecation,
        c"from_py_time() is deprecated. Use Time() constructor instead.",
        1,
    )?;
    Time::from_stdlib_time(
        arg.cast_allow_subclass::<PyTime>()
            .ok_or_type_err("argument must be a datetime.time")?,
    )
    .to_obj(cls)
}

fn format_iso(cls: PyClass<Time>, slf: Time, args: &[PyObj], kwargs: &mut IterKwargs) -> PyReturn {
    if !args.is_empty() {
        raise_type_err("format_iso() takes no positional arguments")?;
    }

    // As-efficient-as-possible assignment of keyword arguments
    let mut unit = fmt::Precision::Auto;
    let mut basic = false;
    let state = cls.state();
    handle_kwargs("format_iso", kwargs, |key, value, eq| {
        if eq(key, *state.str_unit) {
            unit = fmt::Precision::from_py(value, state)?;
        } else if eq(key, *state.str_basic) {
            basic = value.expect_bool("basic")?;
        } else {
            return Ok(false);
        }
        Ok(true)
    })?;

    PyAsciiStrBuilder::format(slf.iso_format(unit, basic))
}

fn parse_iso(cls: PyClass<Time>, s: PyObj) -> PyReturn {
    Time::parse_iso(
        s.cast_allow_subclass::<PyStr>()
            // NOTE: this exception message also needs to make sense when
            // called through the constructor
            .ok_or_type_err("when parsing from ISO format, the argument must be str")?
            .as_utf8()?,
    )
    .ok_or_else_value_err(|| format!("Invalid format: {s}"))?
    .to_obj(cls)
}

fn __reduce__(cls: PyClass<Time>, slf: Time) -> PyReturn {
    let data = pickle::encode_time(slf);
    [
        cls.state().unpickle_time.newref(),
        [data.to_py()?].into_pytuple()?,
    ]
    .into_pytuple()
}

fn on(cls: PyClass<Time>, slf: Time, arg: PyObj) -> PyReturn {
    let state = cls.state();

    if let Some(date) = arg.extract(*state.date_type) {
        PlainDateTime { date, time: slf }.to_obj(*state.plain_datetime_type)
    } else {
        raise_type_err("argument must be a date")
    }
}

fn replace(cls: PyClass<Time>, slf: Time, args: &[PyObj], kwargs: &mut IterKwargs) -> PyReturn {
    let state = cls.state();
    if !args.is_empty() {
        raise_type_err("replace() takes no positional arguments")
    } else {
        let mut hour = slf.hour.into();
        let mut minute = slf.minute.into();
        let mut second = slf.second.into();
        let mut nanos = slf.subsec.get() as _;
        handle_kwargs("replace", kwargs, |k, v, eq| {
            if eq(k, *state.str_hour) {
                hour = v.expect_int("hour")?.to_long()?;
            } else if eq(k, *state.str_minute) {
                minute = v.expect_int("minute")?.to_long()?;
            } else if eq(k, *state.str_second) {
                second = v.expect_int("second")?.to_long()?;
            } else if eq(k, *state.str_nanosecond) {
                nanos = v.expect_int("nanosecond")?.to_long()?;
            } else {
                return Ok(false);
            }
            Ok(true)
        })?;
        Time::from_longs(hour, minute, second, nanos)
            .ok_or_value_err("invalid time component value")?
            .to_obj(cls)
    }
}

fn round(cls: PyClass<Time>, slf: Time, args: &[PyObj], kwargs: &mut IterKwargs) -> PyReturn {
    let round::Args {
        increment, mode, ..
    } = round::Args::parse(args, kwargs, cls.state(), round::ArgsContext::Standard)?;
    let increment_ns = match increment {
        round::RoundIncrement::Day => raise_value_err("cannot round Time to day")?,
        round::RoundIncrement::Exact(incr) => incr.get(),
    };
    slf.round(increment_ns, mode).0.to_obj(cls)
}

fn format(_cls: PyClass<Time>, slf: Time, pattern_obj: PyObj) -> PyReturn {
    let pattern_pystr = pattern_obj
        .cast_exact::<PyStr>()
        .ok_or_type_err("format() argument must be str")?;
    let pattern_str = pattern_pystr.as_utf8()?;
    let elements = pattern::compile(pattern_str).into_value_err()?;
    pattern::validate_fields(&elements, pattern::CategorySet::TIME, "Time")?;
    if pattern::has_12h_without_ampm(&elements) {
        warn_with_class(
            exc_user_warning(),
            c"12-hour format (ii) without AM/PM designator (a/aa) may be ambiguous",
            1,
        )?;
    }
    let vals = pattern::FormatValues {
        year: Year::MIN,
        month: Month::MIN,
        day: 1,
        weekday: Weekday::Monday,
        hour: slf.hour,
        minute: slf.minute,
        second: slf.second,
        nanos: slf.subsec,
        offset_secs: None,
        tz_id: None,
        tz_abbrev: None,
    };
    pattern::format_to_py(&elements, &vals)
}

fn __format__(cls: PyClass<Time>, slf: Time, spec_obj: PyObj) -> PyReturn {
    if spec_obj.is_truthy()? {
        format(cls, slf, spec_obj)
    } else {
        __str__(cls.into(), slf)
    }
}

fn parse(cls: PyClass<Time>, args: &[PyObj], kwargs: &mut IterKwargs) -> PyReturn {
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

    let elements = pattern::compile(fmt_bytes).into_value_err()?;
    pattern::validate_fields(&elements, pattern::CategorySet::TIME, "Time")?;

    let state = pattern::parse_to_state(&elements, s).into_value_err()?;

    let hour = state.hour.unwrap_or(0);
    let minute = state.minute.unwrap_or(0);
    let second = state.second.unwrap_or(0);

    if hour >= 24 || minute >= 60 || second >= 60 {
        raise_value_err("Invalid time")?;
    }

    Time {
        hour,
        minute,
        second,
        subsec: state.nanos,
    }
    .to_obj(cls)
}

static mut METHODS: &[PyMethodDef] = &[
    COPY_METHOD,
    DEEPCOPY_METHOD,
    method0!(Time, __reduce__, c""),
    method0!(Time, to_stdlib, doc::TIME_TO_STDLIB),
    method0!(Time, py_time, doc::TIME_PY_TIME),
    method_kwargs!(Time, replace, doc::TIME_REPLACE),
    method_kwargs!(Time, format_iso, doc::TIME_FORMAT_ISO),
    classmethod1!(Time, parse_iso, doc::TIME_PARSE_ISO),
    classmethod1!(Time, from_py_time, doc::TIME_FROM_PY_TIME),
    method1!(Time, on, doc::TIME_ON),
    method_kwargs!(Time, round, doc::TIME_ROUND),
    method1!(Time, format, doc::TIME_FORMAT),
    method1!(Time, __format__, c""),
    classmethod_kwargs!(Time, parse, doc::TIME_PARSE),
    classmethod_kwargs!(Time, __get_pydantic_core_schema__, doc::PYDANTIC_SCHEMA),
    PyMethodDef::zeroed(),
];

pub(crate) fn unpickle(state: &State, arg: PyObj) -> PyReturn {
    pickle::decode_time(arg.expect_bytes()?)
        .ok_or_type_err(pickle::INVALID_DATA)?
        .to_obj(*state.time_type)
}

fn hour(_: PyType, slf: Time) -> PyReturn {
    slf.hour.to_py()
}

fn minute(_: PyType, slf: Time) -> PyReturn {
    slf.minute.to_py()
}

fn second(_: PyType, slf: Time) -> PyReturn {
    slf.second.to_py()
}

fn nanosecond(_: PyType, slf: Time) -> PyReturn {
    slf.subsec.get().to_py()
}

static mut GETSETTERS: &[PyGetSetDef] = &[
    getter!(Time, hour, doc::TIME_HOUR),
    getter!(Time, minute, doc::TIME_MINUTE),
    getter!(Time, second, doc::TIME_SECOND),
    getter!(Time, nanosecond, doc::TIME_NANOSECOND),
    PyGetSetDef {
        name: NULL(),
        get: None,
        set: None,
        doc: NULL(),
        closure: NULL(),
    },
];

pub(crate) static mut SPEC: PyType_Spec = type_spec::<Time>(c"whenever.Time", unsafe { SLOTS });

#[cfg(test)]
mod tests {
    use super::*;
    use crate::common::fmt::Chunk;

    impl Sink for Vec<u8> {
        fn write(&mut self, bytes: &[u8]) {
            self.extend_from_slice(bytes);
        }
        fn write_byte(&mut self, b: u8) {
            self.push(b);
        }
    }

    #[test]
    fn format_iso() {
        let t1 = Time {
            hour: 1,
            minute: 2,
            second: 3,
            subsec: SubSecNanos::MIN,
        };
        let t2 = Time {
            hour: 12,
            minute: 34,
            second: 56,
            subsec: SubSecNanos::new_unchecked(123_400_000),
        };
        let t3 = Time {
            hour: 12,
            minute: 34,
            second: 56,
            subsec: SubSecNanos::new_unchecked(8),
        };
        let t4 = Time {
            hour: 12,
            minute: 34,
            second: 56,
            subsec: SubSecNanos::new_unchecked(34_090),
        };

        fn testcase(t: Time, basic: bool, unit: fmt::Precision, expect: &[u8]) {
            let mut buf = Vec::new();
            let fmt = t.iso_format(unit, basic);
            fmt.write(&mut buf);
            assert_eq!(
                &buf,
                expect,
                "{} != {} (basic:{})",
                std::str::from_utf8(&buf).unwrap(),
                std::str::from_utf8(expect).unwrap(),
                basic
            );
            assert_eq!(
                fmt.len(),
                expect.len(),
                "length mismatch for {}",
                std::str::from_utf8(expect).unwrap()
            );
        }

        testcase(t1, false, fmt::Precision::Auto, b"01:02:03");
        testcase(t1, true, fmt::Precision::Millisecond, b"010203.000");
        testcase(t2, false, fmt::Precision::Microsecond, b"12:34:56.123400");
        testcase(t2, true, fmt::Precision::Nanosecond, b"123456.123400000");
        testcase(t3, false, fmt::Precision::Nanosecond, b"12:34:56.000000008");
        testcase(t4, true, fmt::Precision::Auto, b"123456.00003409");
        testcase(t4, false, fmt::Precision::Millisecond, b"12:34:56.000");
        testcase(t4, false, fmt::Precision::Second, b"12:34:56");
        testcase(t4, true, fmt::Precision::Minute, b"1234");
        testcase(t4, false, fmt::Precision::Minute, b"12:34");
        testcase(t4, false, fmt::Precision::Hour, b"12");
        testcase(t4, true, fmt::Precision::Hour, b"12");
    }

    #[test]
    fn parse_leap_seconds_extended_format() {
        // Leap second normalization in extended format
        let t = Time::parse_iso(b"01:02:60").unwrap();
        assert_eq!(t.hour, 1);
        assert_eq!(t.minute, 2);
        assert_eq!(t.second, 59);
        assert_eq!(t.subsec, SubSecNanos::MIN);

        // With fractional seconds
        let t = Time::parse_iso(b"23:59:60.999999999").unwrap();
        assert_eq!(t.hour, 23);
        assert_eq!(t.minute, 59);
        assert_eq!(t.second, 59);
        assert_eq!(t.subsec, SubSecNanos::new_unchecked(999_999_999));

        let t = Time::parse_iso(b"12:34:60.123456").unwrap();
        assert_eq!(t.hour, 12);
        assert_eq!(t.minute, 34);
        assert_eq!(t.second, 59);
        assert_eq!(t.subsec, SubSecNanos::new_unchecked(123_456_000));

        // Comma as decimal separator
        let t = Time::parse_iso(b"12:34:60,5").unwrap();
        assert_eq!(t.hour, 12);
        assert_eq!(t.minute, 34);
        assert_eq!(t.second, 59);
        assert_eq!(t.subsec, SubSecNanos::new_unchecked(500_000_000));
    }

    #[test]
    fn parse_leap_seconds_basic_format() {
        // Leap second normalization in basic format
        let t = Time::parse_iso(b"010260").unwrap();
        assert_eq!(t.hour, 1);
        assert_eq!(t.minute, 2);
        assert_eq!(t.second, 59);
        assert_eq!(t.subsec, SubSecNanos::MIN);

        // With fractional seconds
        let t = Time::parse_iso(b"235960.999999999").unwrap();
        assert_eq!(t.hour, 23);
        assert_eq!(t.minute, 59);
        assert_eq!(t.second, 59);
        assert_eq!(t.subsec, SubSecNanos::new_unchecked(999_999_999));

        let t = Time::parse_iso(b"123460.123456").unwrap();
        assert_eq!(t.hour, 12);
        assert_eq!(t.minute, 34);
        assert_eq!(t.second, 59);
        assert_eq!(t.subsec, SubSecNanos::new_unchecked(123_456_000));

        // Comma as decimal separator
        let t = Time::parse_iso(b"123460,5").unwrap();
        assert_eq!(t.hour, 12);
        assert_eq!(t.minute, 34);
        assert_eq!(t.second, 59);
        assert_eq!(t.subsec, SubSecNanos::new_unchecked(500_000_000));
    }

    #[test]
    fn parse_leap_seconds_edge_cases() {
        // Midnight leap second
        let t = Time::parse_iso(b"00:00:60").unwrap();
        assert_eq!(t.hour, 0);
        assert_eq!(t.minute, 0);
        assert_eq!(t.second, 59);

        // End of day leap second
        let t = Time::parse_iso(b"23:59:60").unwrap();
        assert_eq!(t.hour, 23);
        assert_eq!(t.minute, 59);
        assert_eq!(t.second, 59);

        // Various minutes with leap seconds
        for minute in 0..60 {
            let input = format!("12:{:02}:60", minute);
            let t = Time::parse_iso(input.as_bytes()).unwrap();
            assert_eq!(t.hour, 12);
            assert_eq!(t.minute, minute);
            assert_eq!(t.second, 59);
        }
    }

    #[test]
    fn parse_invalid_seconds() {
        // 61 and above should be rejected
        assert!(Time::parse_iso(b"01:02:61").is_none());
        assert!(Time::parse_iso(b"01:02:62").is_none());
        assert!(Time::parse_iso(b"01:02:99").is_none());
        assert!(Time::parse_iso(b"010261").is_none());
        assert!(Time::parse_iso(b"010262").is_none());
        assert!(Time::parse_iso(b"010299").is_none());
    }

    #[test]
    fn parse_normal_seconds_still_work() {
        // Ensure normal seconds 00-59 still parse correctly
        for sec in 0..60 {
            let input = format!("12:34:{:02}", sec);
            let t = Time::parse_iso(input.as_bytes()).unwrap();
            assert_eq!(t.hour, 12);
            assert_eq!(t.minute, 34);
            assert_eq!(t.second, sec);

            let input = format!("1234{:02}", sec);
            let t = Time::parse_iso(input.as_bytes()).unwrap();
            assert_eq!(t.hour, 12);
            assert_eq!(t.minute, 34);
            assert_eq!(t.second, sec);
        }
    }

    #[test]
    fn read_iso_extended_leap_seconds() {
        // Test the read_iso_extended function directly
        let mut scan = Scan::new(b"12:34:60");
        let t = Time::read_iso_extended(&mut scan).unwrap();
        assert_eq!(t.second, 59);
        assert!(scan.is_done());

        let mut scan = Scan::new(b"12:34:60.123");
        let t = Time::read_iso_extended(&mut scan).unwrap();
        assert_eq!(t.second, 59);
        assert_eq!(t.subsec, SubSecNanos::new_unchecked(123_000_000));
        assert!(scan.is_done());
    }

    #[test]
    fn read_iso_basic_leap_seconds() {
        // Test the read_iso_basic function directly
        let mut scan = Scan::new(b"123460");
        let t = Time::read_iso_basic(&mut scan).unwrap();
        assert_eq!(t.second, 59);
        assert!(scan.is_done());

        let mut scan = Scan::new(b"123460.123");
        let t = Time::read_iso_basic(&mut scan).unwrap();
        assert_eq!(t.second, 59);
        assert_eq!(t.subsec, SubSecNanos::new_unchecked(123_000_000));
        assert!(scan.is_done());
    }
}
