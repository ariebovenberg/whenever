use core::ffi::{CStr, c_int, c_long, c_void};
use core::ptr::null_mut as NULL;
use pyo3_ffi::*;

pub(crate) use crate::domain::instant::Instant;

use crate::{
    classes::{
        date::Date,
        offset_datetime::OffsetDateTime,
        plain_datetime::PlainDateTime,
        time::Time,
        time_delta::{DeltaIncrement, TimeDelta, timedelta_from_kwargs},
    },
    common::{
        fmt::{self, Suffix},
        instant::{extract_instant, parse_instant_arg},
        pattern, rfc2822, round,
        scalar::*,
    },
    docstrings as doc,
    py::*,
    pymodule::State,
};

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
    pub(crate) fn to_stdlib_datetime(
        self,
        &PyDateTime_CAPI {
            DateTime_FromDateAndTime,
            TimeZone_UTC,
            DateTimeType,
            ..
        }: &PyDateTime_CAPI,
    ) -> PyReturn {
        let PlainDateTime {
            date: Date { year, month, day },
            time:
                Time {
                    hour,
                    minute,
                    second,
                    subsec,
                },
        } = self.to_utc_plain();
        unsafe {
            // SAFETY: calling DateTime_FromDateAndTime with valid parameters
            DateTime_FromDateAndTime(
                year.get().into(),
                month.get().into(),
                day.into(),
                hour.into(),
                minute.into(),
                second.into(),
                (subsec.get() / 1_000) as _,
                TimeZone_UTC,
                DateTimeType,
            )
        }
        .own()
    }

    // Returns None if the datetime is out of range
    fn from_stdlib_datetime(dt: PyDateTime) -> PyResult<Option<Self>> {
        let inst = Date::from_stdlib_date(dt.date())
            .at(Time::from_stdlib_datetime(dt))
            .assume_utc();
        Ok({
            let offset = dt.utcoffset()?;
            if let Some(py_delta) = (*offset).cast_exact::<PyTimeDelta>() {
                // SAFETY: Python offsets are already bounded to +/- 24 hours: well within TimeDelta range.
                inst.shift(-TimeDelta::from_py_unchecked(py_delta))
            } else if offset.is_none() {
                raise_value_err("datetime is naive")?
            } else {
                raise_value_err("datetime utcoffset() returned non-delta value")?
            }
        })
    }

    pub(crate) const fn pyhash(self) -> Py_hash_t {
        if cfg!(target_pointer_width = "64") {
            hash_combine(
                self.epoch.get() as Py_hash_t,
                self.subsec.get() as Py_hash_t,
            )
        } else {
            hash_combine(
                self.epoch.get() as Py_hash_t,
                hash_combine(
                    (self.epoch.get() >> 32) as Py_hash_t,
                    self.subsec.get() as Py_hash_t,
                ),
            )
        }
    }
}

fn __new__(cls: PyClass<Instant>, args: PyTuple, kwargs: Option<PyDict>) -> PyReturn {
    if args.len() == 1 && kwargs.map_or(0, |d| d.len()) == 0 {
        let arg = args.iter().next().unwrap();
        if PyStr::isinstance(arg) {
            return parse_iso(cls, arg);
        }
        if let Some(dt) = arg.cast_allow_subclass::<PyDateTime>() {
            return Instant::from_stdlib_datetime(dt)?
                .ok_or_range_err()?
                .to_obj(cls);
        }
        raise_type_err("Instant() requires an ISO 8601 string or datetime.datetime")
    } else {
        raise_type_err(
            "Instant() can only be called with an ISO 8601 string passed
            as the sole positional argument. To construct from UTC date and time components,
            use Instant.from_utc().",
        )
    }
}

fn from_utc(cls: PyClass<Instant>, args: PyTuple, kwargs: Option<PyDict>) -> PyReturn {
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

    Date::from_longs(year, month, day)
        .ok_or_value_err("invalid date")?
        .at(Time::from_longs(hour, minute, second, nanosecond).ok_or_value_err("invalid time")?)
        .assume_utc()
        .to_obj(cls)
}

impl PyPayload for Instant {}

fn __repr__(_: PyType, i: Instant) -> PyReturn {
    let PlainDateTime { date, time } = i.to_utc_plain();
    PyAsciiStrBuilder::format((
        b"Instant(\"",
        date.format_iso(false),
        b" ",
        time.format_iso(fmt::Precision::Auto, false),
        b"Z\")",
    ))
}

fn __str__(_: PyType, i: Instant) -> PyReturn {
    let PlainDateTime { date, time } = i.to_utc_plain();
    PyAsciiStrBuilder::format((
        date.format_iso(false),
        b"T",
        time.format_iso(fmt::Precision::Auto, false),
        b"Z",
    ))
}

fn __richcmp__(cls: PyClass<Instant>, inst_a: Instant, b_obj: PyObj, op: c_int) -> PyReturn {
    let Some(inst_b) = extract_instant(b_obj, cls.state()) else {
        return not_implemented();
    };
    CompareOp::from_ffi(op).apply(inst_a, inst_b).to_py()
}

extern "C" fn __hash__(slf: PyObj) -> Py_hash_t {
    hashmask(
        // SAFETY: we know the self object is an Instant
        unsafe { slf.assume_heaptype::<Instant>() }.1.pyhash(),
    )
}

fn __sub__(obj_a: PyObj, obj_b: PyObj) -> PyReturn {
    binary_operation::<Instant>(obj_a, obj_b, "-", |operands| match operands {
        BinaryCall::SameType { cls, slf, other } => {
            Ok(Some(slf.diff(*other).to_obj(*cls.state().time_delta_type)?))
        }
        BinaryCall::ExtTypes { cls, slf, other } => {
            let state = cls.state();
            if let Some(i) = extract_instant(other, state) {
                Ok(Some(slf.diff(i).to_obj(*state.time_delta_type)?))
            } else {
                shift_inner(cls, *slf, *state.time_delta_type, other, true)
            }
        }
        BinaryCall::OtherTypes => Ok(None),
    })
}

fn __add__(obj_a: PyObj, obj_b: PyObj) -> PyReturn {
    binary_operation::<Instant>(obj_a, obj_b, "+", |operands| {
        let BinaryCall::ExtTypes { cls, slf, other } = operands else {
            return Ok(None);
        };
        shift_inner(cls, *slf, *cls.state().time_delta_type, other, false)
    })
}

#[inline(never)]
fn shift_inner(
    cls: PyClass<Instant>,
    inst: Instant,
    tdelta_cls: PyClass<TimeDelta>,
    obj_b: PyObj,
    negate: bool,
) -> PyResult<Option<Owned<PyObj>>> {
    let Some(mut delta) = obj_b.extract(tdelta_cls) else {
        return Ok(None);
    };
    if negate {
        delta = -delta;
    }
    Ok(Some(inst.shift(delta).ok_or_range_err()?.to_obj(cls)?))
}

#[allow(static_mut_refs)]
static mut SLOTS: &[PyType_Slot] = &[
    slotmethod!(Instant, Py_tp_new, __new__),
    slotmethod!(Instant, Py_tp_repr, __repr__, 1),
    slotmethod!(Instant, Py_tp_str, __str__, 1),
    slotmethod!(Instant, Py_tp_richcompare, __richcmp__),
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

fn exact_eq(cls: PyClass<Instant>, slf: Instant, obj_b: PyObj) -> PyReturn {
    if let Some(i) = obj_b.extract(cls) {
        (slf == i).to_py()
    } else {
        raise_type_err("can't compare different types")?
    }
}

fn __reduce__(cls: PyClass<Instant>, Instant { epoch, subsec }: Instant) -> PyReturn {
    let data = pack![epoch.get(), subsec.get()];
    [
        cls.state().unpickle_instant.newref(),
        [data.to_py()?].into_pytuple()?,
    ]
    .into_pytuple()
}

pub(crate) fn unpickle(state: &State, arg: PyObj) -> PyReturn {
    let binding = arg
        .cast_exact::<PyBytes>()
        .ok_or_type_err("invalid pickle data")?;
    let mut packed = binding.as_bytes();
    if packed.len() != 12 {
        raise_value_err("invalid pickle data")?;
    }
    Instant {
        epoch: EpochSecs::new_unchecked(unpack_one!(packed, i64)),
        subsec: SubSecNanos::new_unchecked(unpack_one!(packed, i32)),
    }
    .to_obj(*state.instant_type)
}

// Backwards compatibility: an unpickler for Instants pickled before 0.8.0
pub(crate) fn unpickle_pre_0_8(state: &State, arg: PyObj) -> PyReturn {
    let binding = arg
        .cast_exact::<PyBytes>()
        .ok_or_type_err("invalid pickle data")?;
    let mut packed = binding.as_bytes();
    if packed.len() != 12 {
        raise_value_err("invalid pickle data")?;
    }
    Instant {
        epoch: EpochSecs::new_unchecked(unpack_one!(packed, i64) + EpochSecs::MIN.get() - 86_400),
        subsec: SubSecNanos::new_unchecked(unpack_one!(packed, i32)),
    }
    .to_obj(*state.instant_type)
}

fn timestamp(_: PyType, slf: Instant) -> PyReturn {
    slf.epoch.get().to_py()
}

fn timestamp_millis(_: PyType, slf: Instant) -> PyReturn {
    slf.timestamp_millis().to_py()
}

fn timestamp_nanos(_: PyType, slf: Instant) -> PyReturn {
    slf.timestamp_nanos().to_py()
}

fn from_timestamp(cls: PyClass<Instant>, ts: PyObj) -> PyReturn {
    if let Some(py_int) = ts.cast_allow_subclass::<PyInt>() {
        Instant::from_timestamp(py_int.to_i64()?)
    } else if let Some(py_float) = ts.cast_allow_subclass::<PyFloat>() {
        Instant::from_timestamp_f64(py_float.to_f64()?)
    } else {
        return raise_type_err("timestamp must be an integer or float");
    }
    .ok_or_range_err()?
    .to_obj(cls)
}

fn from_timestamp_millis(cls: PyClass<Instant>, ts: PyObj) -> PyReturn {
    if let Some(py_int) = ts.cast_allow_subclass::<PyInt>() {
        Instant::from_timestamp_millis(py_int.to_i64()?)
    } else {
        return raise_type_err("timestamp must be an integer");
    }
    .ok_or_range_err()?
    .to_obj(cls)
}

fn from_timestamp_nanos(cls: PyClass<Instant>, ts: PyObj) -> PyReturn {
    if let Some(py_int) = ts.cast_allow_subclass::<PyInt>() {
        Instant::from_timestamp_nanos(py_int.to_i128()?)
    } else {
        return raise_type_err("timestamp must be an integer");
    }
    .ok_or_range_err()?
    .to_obj(cls)
}

fn to_stdlib(cls: PyClass<Instant>, slf: Instant) -> PyReturn {
    slf.to_stdlib_datetime(cls.state().py_api()?)
}

fn py_datetime(cls: PyClass<Instant>, slf: Instant) -> PyReturn {
    let state = cls.state();
    warn_with_class(
        *state.warn_deprecation,
        c"py_datetime() is deprecated. Use to_stdlib() instead.",
        1,
    )?;
    to_stdlib(cls, slf)
}

fn from_py_datetime(cls: PyClass<Instant>, obj: PyObj) -> PyReturn {
    let state = cls.state();
    warn_with_class(
        *state.warn_deprecation,
        c"from_py_datetime() is deprecated. Use Instant() constructor instead.",
        1,
    )?;
    if let Some(dt) = obj.cast_allow_subclass::<PyDateTime>() {
        Instant::from_stdlib_datetime(dt)?
            .ok_or_range_err()?
            .to_obj(cls)
    } else {
        raise_type_err("expected a datetime object")
    }
}

fn now(cls: PyClass<Instant>) -> PyReturn {
    cls.state().now()?.to_obj(cls)
}

fn format_iso(
    cls: PyClass<Instant>,
    slf: Instant,
    args: &[PyObj],
    kwargs: &mut IterKwargs,
) -> PyReturn {
    let PlainDateTime { date, time } = slf.to_utc_plain();
    fmt::format_iso(date, time, cls.state(), args, kwargs, Suffix::Zulu)
}

fn parse_iso(cls: PyClass<Instant>, s_obj: PyObj) -> PyReturn {
    OffsetDateTime::parse(
        s_obj
            .cast_allow_subclass::<PyStr>()
            // NOTE: this exception message also needs to make sense when
            // called through the constructor
            .ok_or_type_err("when parsing from ISO format, the argument must be str")?
            .as_utf8()?,
    )
    .ok_or_else_value_err(|| format!("Invalid format: {s_obj}"))?
    .to_instant()
    .to_obj(cls)
}

fn add(cls: PyClass<Instant>, slf: Instant, args: &[PyObj], kwargs: &mut IterKwargs) -> PyReturn {
    shift_method(cls, slf, args, kwargs, false)
}

fn subtract(
    cls: PyClass<Instant>,
    slf: Instant,
    args: &[PyObj],
    kwargs: &mut IterKwargs,
) -> PyReturn {
    shift_method(cls, slf, args, kwargs, true)
}

#[inline(never)]
fn shift_method(
    cls: PyClass<Instant>,
    instant: Instant,
    args: &[PyObj],
    kwargs: &mut IterKwargs,
    negate: bool,
) -> PyReturn {
    let fname = if negate { "subtract" } else { "add" };
    let state = cls.state();

    match *args {
        [arg] => {
            if kwargs.len() != 0 {
                raise_type_err(format!(
                    "{fname}() can't mix positional and keyword arguments"
                ))?;
            }
            if let Some(d) = arg.extract(*state.time_delta_type) {
                instant
                    .shift(d.negate_if(negate))
                    .ok_or_range_err()?
                    .to_obj(cls)
            } else {
                raise_type_err(format!("{fname}() argument must be a TimeDelta"))?
            }
        }
        [] => {
            let tdelta = timedelta_from_kwargs(fname, kwargs, state)?;
            instant
                .shift(tdelta.negate_if(negate))
                .ok_or_range_err()?
                .to_obj(cls)
        }
        _ => raise_type_err(format!(
            "{fname}() takes at most 1 positional argument, got {}",
            args.len()
        ))?,
    }
}

fn difference(cls: PyClass<Instant>, slf: Instant, obj_b: PyObj) -> PyReturn {
    let state = cls.state();
    let inst_b = parse_instant_arg("difference", obj_b, state)?;
    slf.diff(inst_b).to_obj(*state.time_delta_type)
}

fn to_tz(cls: PyClass<Instant>, slf: Instant, tz_obj: PyObj) -> PyReturn {
    let state = cls.state();
    slf.into_zoned_py(state.tz_store.obj_get(tz_obj)?, *state.zoned_datetime_type)
}

fn to_fixed_offset(cls: PyClass<Instant>, slf: Instant, args: &[PyObj]) -> PyReturn {
    let state = cls.state();
    match *args {
        [] => slf.to_utc_plain().assume_offset_unchecked(Offset::ZERO),
        [arg] => slf
            .to_offset(Offset::from_obj(arg, *state.time_delta_type)?)
            .ok_or_range_err()?,
        _ => raise_type_err("to_fixed_offset() takes at most 1 argument")?,
    }
    .to_obj(*state.offset_datetime_type)
}

fn to_system_tz(cls: PyClass<Instant>, slf: Instant) -> PyReturn {
    let state = cls.state();
    slf.into_zoned_py(state.tz_store.get_system_tz()?, *state.zoned_datetime_type)
}

fn format_rfc2822(_: PyType, slf: Instant) -> PyReturn {
    let fmt = rfc2822::format_gmt(slf);
    // SAFETY: we know the bytes are ASCII
    unsafe { std::str::from_utf8_unchecked(&fmt[..]) }.to_py()
}

fn parse_rfc2822(cls: PyClass<Instant>, s_obj: PyObj) -> PyReturn {
    let s = s_obj
        .cast_allow_subclass::<PyStr>()
        .ok_or_type_err("expected a string")?;
    let (date, time, offset) =
        rfc2822::parse(s.as_utf8()?).ok_or_else_value_err(|| format!("Invalid format: {s_obj}"))?;
    date.at(time)
        .assume_offset(offset)
        .ok_or_range_err()?
        .to_instant()
        .to_obj(cls)
}

fn round(cls: PyClass<Instant>, slf: Instant, args: &[PyObj], kwargs: &mut IterKwargs) -> PyReturn {
    let round::Args {
        increment, mode, ..
    } = round::Args::parse(cls.state(), args, kwargs, false)?;
    let round_increment = match increment {
        round::RoundIncrement::Day => raise_value_err(doc::CANNOT_ROUND_DAY_MSG)?,
        // SAFETY: parse() validates the increment is ≥ 1 ns and fits within a day
        round::RoundIncrement::Exact(ns) => DeltaIncrement::from_nanos(ns.get() as u128).unwrap(),
    };
    let TimeDelta { secs, subsec } = slf
        .to_delta()
        .round(round_increment, mode.to_abs_euclid(slf.epoch.get() < 0))
        // SAFETY: TimeDelta has higher range than Instant,
        // so rounding cannot result in out-of-range
        .unwrap();
    Instant {
        epoch: EpochSecs::new(secs.get()).ok_or_range_err()?,
        subsec,
    }
    .to_obj(cls)
}

fn format(_cls: PyClass<Instant>, slf: Instant, pattern_obj: PyObj) -> PyReturn {
    let pattern_pystr = pattern_obj
        .cast_exact::<PyStr>()
        .ok_or_type_err("format() argument must be str")?;
    let pattern_str = pattern_pystr.as_utf8()?;
    let elements = pattern::compile(pattern_str).into_value_err()?;
    pattern::validate_fields(&elements, pattern::CategorySet::DATE_TIME_OFFSET, "Instant")?;
    if pattern::has_12h_without_ampm(&elements) {
        warn_with_class(
            exc_user_warning(),
            c"12-hour format (ii) without AM/PM designator (a/aa) may be ambiguous",
            1,
        )?;
    }
    let PlainDateTime { date, time } = slf.to_utc_plain();
    let vals = pattern::FormatValues {
        year: date.year,
        month: date.month,
        day: date.day,
        weekday: date.day_of_week(),
        hour: time.hour,
        minute: time.minute,
        second: time.second,
        nanos: slf.subsec,
        offset_secs: Some(Offset::ZERO),
        tz_id: None,
        tz_abbrev: None,
    };
    pattern::format_to_py(&elements, &vals)
}

fn __format__(cls: PyClass<Instant>, slf: Instant, spec_obj: PyObj) -> PyReturn {
    if spec_obj.is_truthy()? {
        format(cls, slf, spec_obj)
    } else {
        __str__(cls.into(), slf)
    }
}

fn parse(cls: PyClass<Instant>, args: &[PyObj], kwargs: &mut IterKwargs) -> PyReturn {
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
    pattern::validate_fields(&elements, pattern::CategorySet::DATE_TIME_OFFSET, "Instant")?;

    let state = pattern::parse_to_state(&elements, s).into_value_err()?;

    let offset = state
        .offset_secs
        .ok_or_value_err("Instant.parse() pattern must include an offset field (x/X)")?;

    let year = state.year.ok_or_value_err(
        "Pattern must include year (YYYY/YY), month (MM/MMM/MMMM), and day (DD) fields",
    )?;
    let month = state.month.ok_or_value_err(
        "Pattern must include year (YYYY/YY), month (MM/MMM/MMMM), and day (DD) fields",
    )?;
    let day = state.day.ok_or_value_err(
        "Pattern must include year (YYYY/YY), month (MM/MMM/MMMM), and day (DD) fields",
    )?;

    let date = Date::new(year, month, day).ok_or_value_err("Invalid date")?;

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

    // offset is already validated (scalar::Offset) — no range check needed here.
    date.at(time)
        .assume_utc()
        .shift_by_offset(-offset)
        .ok_or_range_err()?
        .to_obj(cls)
}

static mut METHODS: &[PyMethodDef] = &[
    COPY_METHOD,
    DEEPCOPY_METHOD,
    method0!(Instant, __reduce__, c""),
    method1!(Instant, exact_eq, doc::EXACTTIME_EXACT_EQ),
    method0!(Instant, timestamp, doc::EXACTTIME_TIMESTAMP),
    method0!(Instant, timestamp_millis, doc::EXACTTIME_TIMESTAMP_MILLIS),
    method0!(Instant, timestamp_nanos, doc::EXACTTIME_TIMESTAMP_NANOS),
    classmethod1!(Instant, from_timestamp, doc::INSTANT_FROM_TIMESTAMP),
    classmethod1!(
        Instant,
        from_timestamp_millis,
        doc::INSTANT_FROM_TIMESTAMP_MILLIS
    ),
    classmethod1!(
        Instant,
        from_timestamp_nanos,
        doc::INSTANT_FROM_TIMESTAMP_NANOS
    ),
    // This method is defined different because it
    // makes use of the arg/kwargs processing macro.
    // Other types only use it for the __new__ method.
    PyMethodDef {
        ml_name: c"from_utc".as_ptr(),
        ml_meth: PyMethodDefPointer {
            PyCFunctionWithKeywords: {
                unsafe extern "C" fn _wrap(
                    cls: *mut PyObject,
                    args: *mut PyObject,
                    kwargs: *mut PyObject,
                ) -> *mut PyObject {
                    from_utc(
                        unsafe { PyClass::<Instant>::from_ptr_unchecked(cls.cast()) },
                        unsafe { PyTuple::from_ptr_unchecked(args) },
                        (!kwargs.is_null()).then(|| unsafe { PyDict::from_ptr_unchecked(kwargs) }),
                    )
                    .to_py_owned_ptr()
                }
                _wrap
            },
        },
        ml_flags: METH_CLASS | METH_VARARGS | METH_KEYWORDS,
        ml_doc: doc::INSTANT_FROM_UTC.as_ptr(),
    },
    method0!(Instant, to_stdlib, doc::BASICCONVERSIONS_TO_STDLIB),
    method0!(Instant, py_datetime, doc::BASICCONVERSIONS_PY_DATETIME),
    classmethod1!(
        Instant,
        from_py_datetime,
        doc::BASICCONVERSIONS_FROM_PY_DATETIME
    ),
    classmethod0!(Instant, now, doc::INSTANT_NOW),
    method0!(Instant, format_rfc2822, doc::INSTANT_FORMAT_RFC2822),
    classmethod1!(Instant, parse_rfc2822, doc::INSTANT_PARSE_RFC2822),
    method_kwargs!(Instant, format_iso, doc::INSTANT_FORMAT_ISO),
    classmethod1!(Instant, parse_iso, doc::INSTANT_PARSE_ISO),
    method_kwargs!(Instant, add, doc::INSTANT_ADD),
    method_kwargs!(Instant, subtract, doc::INSTANT_SUBTRACT),
    method1!(Instant, to_tz, doc::EXACTTIME_TO_TZ),
    method0!(Instant, to_system_tz, doc::EXACTTIME_TO_SYSTEM_TZ),
    method_vararg!(Instant, to_fixed_offset, doc::EXACTTIME_TO_FIXED_OFFSET),
    method1!(Instant, difference, doc::EXACTTIME_DIFFERENCE),
    method_kwargs!(Instant, round, doc::INSTANT_ROUND),
    method1!(Instant, format, doc::INSTANT_FORMAT),
    method1!(Instant, __format__, c""),
    classmethod_kwargs!(Instant, parse, doc::INSTANT_PARSE),
    classmethod_kwargs!(Instant, __get_pydantic_core_schema__, doc::PYDANTIC_SCHEMA),
    PyMethodDef::zeroed(),
];

pub(crate) static mut SPEC: PyType_Spec =
    type_spec::<Instant>(c"whenever.Instant", unsafe { SLOTS });
