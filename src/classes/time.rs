use crate::{
    classes::plain_datetime::DateTime,
    common::{
        fmt::{self, Sink, format_2_digits},
        parse::Scan,
        round,
        scalar::*,
    },
    docstrings as doc,
    py::*,
    pymodule::State,
};
use core::ffi::{CStr, c_int, c_long, c_void};
use pyo3_ffi::*;
use std::{
    fmt::{Display, Formatter},
    ptr::null_mut as NULL,
};

#[derive(Debug, Eq, PartialEq, Ord, PartialOrd, Copy, Clone)]
pub struct Time {
    pub(crate) hour: u8,
    pub(crate) minute: u8,
    pub(crate) second: u8,
    pub(crate) subsec: SubSecNanos,
}

impl Time {
    pub(crate) const fn pyhash(&self) -> Py_hash_t {
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

    pub(crate) const fn total_seconds(&self) -> u32 {
        self.hour as u32 * 3600 + self.minute as u32 * 60 + self.second as u32
    }

    pub(crate) const fn from_sec_subsec(sec: u32, subsec: SubSecNanos) -> Self {
        Time {
            hour: (sec / 3600) as u8,
            minute: ((sec % 3600) / 60) as u8,
            second: (sec % 60) as u8,
            subsec,
        }
    }

    pub(crate) const fn total_nanos(&self) -> u64 {
        self.subsec.get() as u64 + self.total_seconds() as u64 * 1_000_000_000
    }

    pub(crate) fn from_total_nanos_unchecked(nanos: u64) -> Self {
        Time {
            hour: (nanos / 3_600_000_000_000) as u8,
            minute: ((nanos % 3_600_000_000_000) / 60_000_000_000) as u8,
            second: ((nanos % 60_000_000_000) / 1_000_000_000) as u8,
            subsec: SubSecNanos::from_remainder(nanos),
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

    /// Read a time string in the ISO 8601 extended format (i.e. with ':' separators)
    pub(crate) fn read_iso_extended(s: &mut Scan) -> Option<Self> {
        // FUTURE: potential double checks coming from some callers
        let hour = s.digits00_23()?;
        let (minute, second, subsec) = match s.advance_on(b':') {
            // The "extended" format with mandatory ':' between components
            Some(true) => {
                let min = s.digits00_59()?;
                // seconds are still optional at this point
                let (sec, subsec) = match s.advance_on(b':') {
                    Some(true) => s.digits00_60_leap().zip(s.subsec())?,
                    _ => (0, SubSecNanos::MIN),
                };
                (min, sec, subsec)
            }
            // No components besides hour
            _ => (0, 0, SubSecNanos::MIN),
        };
        Some(Time {
            hour,
            minute,
            second,
            subsec,
        })
    }

    pub(crate) fn read_iso_basic(s: &mut Scan) -> Option<Self> {
        let hour = s.digits00_23()?;
        let (minute, second, subsec) = match s.digits00_59() {
            Some(m) => {
                let (sec, sub) = match s.digits00_60_leap() {
                    Some(n) => (n, s.subsec().unwrap_or(SubSecNanos::MIN)),
                    None => (0, SubSecNanos::MIN),
                };
                (m, sec, sub)
            }
            None => (0, 0, SubSecNanos::MIN),
        };
        Some(Time {
            hour,
            minute,
            second,
            subsec,
        })
    }

    pub(crate) fn read_iso(s: &mut Scan) -> Option<Self> {
        match s.get(2) {
            Some(b':') => Self::read_iso_extended(s),
            _ => Self::read_iso_basic(s),
        }
    }

    pub(crate) fn parse_iso(s: &[u8]) -> Option<Self> {
        Scan::new(s).parse_all(Self::read_iso)
    }

    /// For efficiency reasons, formatting is done in two steps:
    /// (1) Just enough processing to determine the length of the output string
    /// (2) Writing the actual output to a (correctly sized) buffer
    pub(crate) fn format_iso(self, unit: fmt::Unit, basic: bool) -> IsoFormat {
        let (subsec_str, subsec_len) = self.subsec.format_iso();
        IsoFormat {
            time: self,
            basic,
            subsec_str,
            subsec_len,
            unit,
        }
    }

    /// Round the time to the specified increment
    ///
    /// Returns the rounded time and whether it has wrapped around to the next day (0 or 1)
    /// The increment is given in ns must be a divisor of 24 hours
    pub(crate) fn round(self, increment: u64, mode: round::Mode) -> (Self, u64) {
        debug_assert!(86_400_000_000_000 % increment == 0);
        let total_nanos = self.total_nanos();
        let quotient = total_nanos / increment;
        let remainder = total_nanos % increment;

        let threshold = match mode {
            round::Mode::HalfEven => 1.max(increment / 2 + (quotient % 2 == 0) as u64),
            round::Mode::Ceil => 1,
            round::Mode::Floor => increment + 1,
            round::Mode::HalfFloor => increment / 2 + 1,
            round::Mode::HalfCeil => 1.max(increment / 2),
        };
        let round_up = remainder >= threshold;
        let ns_since_midnight = (quotient + round_up as u64) * increment;
        (
            Self::from_total_nanos_unchecked(ns_since_midnight % 86_400_000_000_000),
            ns_since_midnight / 86_400_000_000_000,
        )
    }

    pub(crate) fn from_py(t: PyTime) -> Self {
        Time {
            hour: t.hour() as _,
            minute: t.minute() as _,
            second: t.second() as _,
            // SAFETY: microseconds are always sub-second
            subsec: SubSecNanos::new_unchecked((t.microsecond() * 1_000) as _),
        }
    }

    pub(crate) fn from_py_dt(dt: PyDateTime) -> Self {
        Time {
            hour: dt.hour() as _,
            minute: dt.minute() as _,
            second: dt.second() as _,
            // SAFETY: microseconds are always sub-second
            subsec: SubSecNanos::new_unchecked((dt.microsecond() * 1_000) as _),
        }
    }

    pub(crate) const MIDNIGHT: Time = Time {
        hour: 0,
        minute: 0,
        second: 0,
        subsec: SubSecNanos::MIN,
    };
}

#[derive(Debug, Clone, Copy)]
pub(crate) struct IsoFormat {
    time: Time,
    basic: bool,
    unit: fmt::Unit,
    subsec_str: [u8; 10],
    subsec_len: usize,
}

impl fmt::Chunk for IsoFormat {
    fn len(&self) -> usize {
        (match self.unit {
            fmt::Unit::Hour => 2,
            fmt::Unit::Minute => 4,
            fmt::Unit::Second => 6,
            fmt::Unit::Millisecond => 10,
            fmt::Unit::Microsecond => 13,
            fmt::Unit::Nanosecond => 16,
            fmt::Unit::Auto => 6 + self.subsec_len,
        }) + if self.basic || self.unit == fmt::Unit::Hour {
            0
        } else if self.unit == fmt::Unit::Minute {
            1
        } else {
            2
        }
    }

    fn write(&self, buf: &mut impl Sink) {
        let &IsoFormat {
            time:
                Time {
                    hour,
                    minute,
                    second,
                    ..
                },
            basic,
            unit,
            subsec_str,
            subsec_len,
        } = self;
        buf.write(format_2_digits(hour).as_ref());
        if unit == fmt::Unit::Hour {
            return;
        }
        if !basic {
            buf.write_byte(b':');
        }
        buf.write(format_2_digits(minute).as_ref());
        if unit == fmt::Unit::Minute {
            return;
        }
        if !basic {
            buf.write_byte(b':');
        }
        buf.write(format_2_digits(second).as_ref());
        if unit == fmt::Unit::Second {
            return;
        }
        let len_to_write = match unit {
            fmt::Unit::Auto => subsec_len,
            fmt::Unit::Nanosecond => 10,
            fmt::Unit::Microsecond => 7,
            fmt::Unit::Millisecond => 4,
            _ => unreachable!(), // already handled above
        };
        buf.write(&subsec_str[..len_to_write]);
    }
}

impl PySimpleAlloc for Time {}

// FUTURE: a trait for faster formatting since timestamp are small and
// limited in length?
impl Display for Time {
    fn fmt(&self, f: &mut Formatter<'_>) -> std::fmt::Result {
        write!(
            f,
            "{:02}:{:02}:{:02}{}",
            self.hour, self.minute, self.second, self.subsec
        )
    }
}

pub(crate) const SINGLETONS: &[(&CStr, Time); 4] = &[
    (c"MIN", Time::MIDNIGHT),
    (c"MIDNIGHT", Time::MIDNIGHT),
    (
        c"NOON",
        Time {
            hour: 12,
            minute: 0,
            second: 0,
            subsec: SubSecNanos::MIN,
        },
    ),
    (
        c"MAX",
        Time {
            hour: 23,
            minute: 59,
            second: 59,
            subsec: SubSecNanos::MAX,
        },
    ),
];

fn __new__(cls: HeapType<Time>, args: PyTuple, kwargs: Option<PyDict>) -> PyReturn {
    if args.len() == 1 && kwargs.map_or(0, |d| d.len()) == 0 {
        let obj = args.iter().next().unwrap();
        if PyStr::isinstance(obj) {
            return parse_iso(cls, args.iter().next().unwrap());
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
        .ok_or_value_err("Invalid time component value")?
        .to_obj(cls)
}

extern "C" fn __hash__(slf: PyObj) -> Py_hash_t {
    // SAFETY: self type is always passed to __hash__
    hashmask(unsafe { slf.assume_heaptype::<Time>() }.1.pyhash())
}

fn __richcmp__(cls: HeapType<Time>, slf: Time, arg: PyObj, op: c_int) -> PyReturn {
    match arg.extract(cls) {
        Some(b) => match op {
            pyo3_ffi::Py_EQ => slf == b,
            pyo3_ffi::Py_NE => slf != b,
            pyo3_ffi::Py_LT => slf < b,
            pyo3_ffi::Py_LE => slf <= b,
            pyo3_ffi::Py_GT => slf > b,
            pyo3_ffi::Py_GE => slf >= b,
            _ => unreachable!(),
        }
        .to_py(),
        None => not_implemented(),
    }
}

fn __str__(_: PyType, slf: Time) -> PyReturn {
    PyAsciiStrBuilder::format(slf.format_iso(fmt::Unit::Auto, false))
}

fn __repr__(_: PyType, slf: Time) -> PyReturn {
    PyAsciiStrBuilder::format((b"Time(\"", slf.format_iso(fmt::Unit::Auto, false), b"\")"))
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

fn py_time(cls: HeapType<Time>, slf: Time) -> PyReturn {
    let Time {
        hour,
        minute,
        second,
        subsec,
    } = slf;
    let &PyDateTime_CAPI {
        Time_FromTime,
        TimeType,
        ..
    } = cls.state().py_api;
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
    .rust_owned()
}

fn from_py_time(cls: HeapType<Time>, arg: PyObj) -> PyReturn {
    Time::from_py(
        arg.cast_allow_subclass::<PyTime>()
            .ok_or_type_err("argument must be a datetime.time")?,
    )
    .to_obj(cls)
}

fn format_iso(cls: HeapType<Time>, slf: Time, args: &[PyObj], kwargs: &mut IterKwargs) -> PyReturn {
    if !args.is_empty() {
        raise_type_err("format_iso() takes no positional arguments")?;
    }

    // As-efficient-as-possible assignment of keyword arguments
    let mut unit = fmt::Unit::Auto;
    let mut basic = false;
    let &State {
        str_unit,
        str_basic,
        str_hour,
        str_minute,
        str_second,
        str_millisecond,
        str_microsecond,
        str_nanosecond,
        str_auto,
        ..
    } = cls.state();
    handle_kwargs("format_iso", kwargs, |key, value, eq| {
        if eq(key, str_unit) {
            unit = fmt::Unit::from_py(
                value,
                str_hour,
                str_minute,
                str_second,
                str_millisecond,
                str_microsecond,
                str_nanosecond,
                str_auto,
            )?;
        } else if eq(key, str_basic) {
            if value.is_true() {
                basic = true;
            } else if value.is_false() {
                basic = false;
            } else {
                raise_value_err("basic must be True or False")?;
            }
        } else {
            return Ok(false);
        }
        Ok(true)
    })?;

    PyAsciiStrBuilder::format(slf.format_iso(unit, basic))
}

fn parse_iso(cls: HeapType<Time>, s: PyObj) -> PyReturn {
    Time::parse_iso(
        s.cast_allow_subclass::<PyStr>()
            // NOTE: this exception message also needs to make sense when
            // called through the constructor
            .ok_or_type_err("When parsing from ISO format, the argument must be str")?
            .as_utf8()?,
    )
    .ok_or_else_value_err(|| format!("Invalid format: {s}"))?
    .to_obj(cls)
}

fn format_common_iso(
    cls: HeapType<Time>,
    slf: Time,
    args: &[PyObj],
    kwargs: &mut IterKwargs,
) -> PyReturn {
    deprecation_warn(c"format_common_iso() has been renamed to format_iso()")?;
    format_iso(cls, slf, args, kwargs)
}

fn parse_common_iso(cls: HeapType<Time>, arg: PyObj) -> PyReturn {
    deprecation_warn(c"parse_common_iso() has been renamed to parse_iso()")?;
    parse_iso(cls, arg)
}

fn __reduce__(cls: HeapType<Time>, slf: Time) -> PyResult<Owned<PyTuple>> {
    let Time {
        hour,
        minute,
        second,
        subsec: nanos,
    } = slf;
    let data = pack![hour, minute, second, nanos.get()];
    (
        cls.state().unpickle_time.newref(),
        (data.to_py()?,).into_pytuple()?,
    )
        .into_pytuple()
}
fn on(cls: HeapType<Time>, slf: Time, arg: PyObj) -> PyReturn {
    let &State {
        plain_datetime_type,
        date_type,
        ..
    } = cls.state();

    if let Some(date) = arg.extract(date_type) {
        DateTime { date, time: slf }.to_obj(plain_datetime_type)
    } else {
        raise_type_err("argument must be a date")
    }
}

fn replace(cls: HeapType<Time>, slf: Time, args: &[PyObj], kwargs: &mut IterKwargs) -> PyReturn {
    let &State {
        str_hour,
        str_minute,
        str_second,
        str_nanosecond,
        ..
    } = cls.state();
    if !args.is_empty() {
        raise_type_err("replace() takes no positional arguments")
    } else {
        let mut hour = slf.hour.into();
        let mut minute = slf.minute.into();
        let mut second = slf.second.into();
        let mut nanos = slf.subsec.get() as _;
        handle_kwargs("replace", kwargs, |key, value, eq| {
            if eq(key, str_hour) {
                hour = value
                    .cast_allow_subclass::<PyInt>()
                    .ok_or_type_err("hour must be an integer")?
                    .to_long()?;
            } else if eq(key, str_minute) {
                minute = value
                    .cast_allow_subclass::<PyInt>()
                    .ok_or_type_err("minute must be an integer")?
                    .to_long()?;
            } else if eq(key, str_second) {
                second = value
                    .cast_allow_subclass::<PyInt>()
                    .ok_or_type_err("second must be an integer")?
                    .to_long()?;
            } else if eq(key, str_nanosecond) {
                nanos = value
                    .cast_allow_subclass::<PyInt>()
                    .ok_or_type_err("nanosecond must be an integer")?
                    .to_long()?;
            } else {
                return Ok(false);
            }
            Ok(true)
        })?;
        Time::from_longs(hour, minute, second, nanos)
            .ok_or_value_err("Invalid time component value")?
            .to_obj(cls)
    }
}

fn round(cls: HeapType<Time>, slf: Time, args: &[PyObj], kwargs: &mut IterKwargs) -> PyReturn {
    let (unit, increment, mode) = round::parse_args(cls.state(), args, kwargs, false, false)?;
    if unit == round::Unit::Day {
        raise_value_err("Cannot round Time to day")?;
    } else if unit == round::Unit::Hour && 86_400_000_000_000 % increment != 0 {
        raise_value_err("increment must be a divisor of 24")?;
    }
    slf.round(increment as u64, mode).0.to_obj(cls)
}

static mut METHODS: &[PyMethodDef] = &[
    method0!(Time, __copy__, c""),
    method1!(Time, __deepcopy__, c""),
    method0!(Time, __reduce__, c""),
    method0!(Time, py_time, doc::TIME_PY_TIME),
    method_kwargs!(Time, replace, doc::TIME_REPLACE),
    method_kwargs!(Time, format_iso, doc::TIME_FORMAT_ISO),
    method_kwargs!(Time, format_common_iso, c""), // deprecated alias
    classmethod1!(Time, parse_iso, doc::TIME_PARSE_ISO),
    classmethod1!(Time, parse_common_iso, c""), // deprecated alias
    classmethod1!(Time, from_py_time, doc::TIME_FROM_PY_TIME),
    method1!(Time, on, doc::TIME_ON),
    method_kwargs!(Time, round, doc::TIME_ROUND),
    classmethod_kwargs!(Time, __get_pydantic_core_schema__, doc::PYDANTIC_SCHEMA),
    PyMethodDef::zeroed(),
];

pub(crate) fn unpickle(state: &State, arg: PyObj) -> PyReturn {
    let py_bytes = arg
        .cast_exact::<PyBytes>()
        .ok_or_type_err("Invalid pickle data")?;

    let mut data = py_bytes.as_bytes()?;
    if data.len() != 7 {
        raise_type_err("Invalid pickle data")?
    }
    Time {
        hour: unpack_one!(data, u8),
        minute: unpack_one!(data, u8),
        second: unpack_one!(data, u8),
        subsec: SubSecNanos::new_unchecked(unpack_one!(data, i32)),
    }
    .to_obj(state.time_type)
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
    getter!(Time, hour, "The hour component"),
    getter!(Time, minute, "The minute component"),
    getter!(Time, second, "The second component"),
    getter!(Time, nanosecond, "The nanosecond component"),
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

        fn testcase(t: Time, basic: bool, unit: fmt::Unit, expect: &[u8]) {
            let mut buf = Vec::new();
            let fmt = t.format_iso(unit, basic);
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

        testcase(t1, false, fmt::Unit::Auto, b"01:02:03");
        testcase(t1, true, fmt::Unit::Millisecond, b"010203.000");
        testcase(t2, false, fmt::Unit::Microsecond, b"12:34:56.123400");
        testcase(t2, true, fmt::Unit::Nanosecond, b"123456.123400000");
        testcase(t3, false, fmt::Unit::Nanosecond, b"12:34:56.000000008");
        testcase(t4, true, fmt::Unit::Auto, b"123456.00003409");
        testcase(t4, false, fmt::Unit::Millisecond, b"12:34:56.000");
        testcase(t4, false, fmt::Unit::Second, b"12:34:56");
        testcase(t4, true, fmt::Unit::Minute, b"1234");
        testcase(t4, false, fmt::Unit::Minute, b"12:34");
        testcase(t4, false, fmt::Unit::Hour, b"12");
        testcase(t4, true, fmt::Unit::Hour, b"12");
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
