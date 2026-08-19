use core::ffi::{CStr, c_int, c_void};
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
        compat::{parse_pattern_keyword, warn_deprecated},
        fmt,
        format_args::{self, Suffix},
        instant::{
            TimestampUnit, extract_instant, parse_instant_arg, parse_timestamp_millis,
            parse_timestamp_nanos,
        },
        pattern, pickle, rfc2822, round_args as round,
    },
    docstrings as doc,
    domain::scalar::*,
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
    pub(crate) fn to_stdlib_datetime(self, api: &PyDateTime_CAPI) -> PyReturn {
        api.new_datetime(self.to_utc_plain(), Some(api.utc_timezone()))
            .map(Owned::into_obj)
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
                inst.shift(-TimeDelta::from_stdlib_timedelta_unchecked(py_delta))
            } else if offset.is_none() {
                raise_value_err("datetime is naive")?
            } else {
                raise_value_err("datetime utcoffset() returned non-delta value")?
            }
        })
    }

    pub(crate) const fn python_hash(self) -> Py_hash_t {
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
    let mut year: i64 = 0;
    let mut month: i64 = 0;
    let mut day: i64 = 0;
    let mut hour: i64 = 0;
    let mut minute: i64 = 0;
    let mut second: i64 = 0;
    let mut nanosecond: i64 = 0;

    let fmt = if IS_LP64 {
        c"lll|lll$l:Instant.from_utc"
    } else {
        c"LLL|LLL$L:Instant.from_utc"
    };
    parse_args_kwargs!(
        args, kwargs, fmt, year, month, day, hour, minute, second, nanosecond
    );

    Date::from_i64_components(year, month, day)
        .ok_or_value_err("invalid date")?
        .at(Time::from_i64_components(hour, minute, second, nanosecond)
            .ok_or_value_err("invalid time")?)
        .assume_utc()
        .to_obj(cls)
}

impl PyPayload for Instant {}

fn __repr__(_: PyType, i: Instant) -> PyReturn {
    let PlainDateTime { date, time } = i.to_utc_plain();
    PyAsciiStrBuilder::format((
        b"Instant(\"",
        date.iso_format(false),
        b" ",
        time.iso_format(fmt::Precision::Auto, false),
        b"Z\")",
    ))
}

fn __str__(_: PyType, i: Instant) -> PyReturn {
    let PlainDateTime { date, time } = i.to_utc_plain();
    PyAsciiStrBuilder::format((
        date.iso_format(false),
        b"T",
        time.iso_format(fmt::Precision::Auto, false),
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
        unsafe { slf.assume_heaptype::<Instant>() }.1.python_hash(),
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
        pfunc: generic_dealloc::<Instant> as *mut c_void,
    },
    PyType_Slot {
        slot: 0,
        pfunc: NULL(),
    },
];

fn strict_eq(cls: PyClass<Instant>, slf: Instant, obj_b: PyObj) -> PyReturn {
    if let Some(i) = obj_b.extract(cls) {
        (slf == i).to_py()
    } else {
        raise_type_err("strict_eq() requires same-type arguments")?
    }
}

fn exact_eq(cls: PyClass<Instant>, slf: Instant, obj_b: PyObj) -> PyReturn {
    warn_deprecated(
        cls.state(),
        c"exact_eq() is deprecated; use strict_eq() instead",
        1,
    )?;
    strict_eq(cls, slf, obj_b)
}

fn __reduce__(cls: PyClass<Instant>, slf: Instant) -> PyReturn {
    let data = pickle::encode_instant(slf);
    [
        cls.state().unpickle_instant.newref(),
        [data.to_py()?].into_pytuple()?,
    ]
    .into_pytuple()
}

pub(crate) fn unpickle(state: &State, arg: PyObj) -> PyReturn {
    pickle::decode_instant(arg.expect_bytes()?)
        .ok_or_value_err(pickle::INVALID_DATA)?
        .to_obj(*state.instant_type)
}

// Backwards compatibility: an unpickler for Instants pickled before 0.8.0
pub(crate) fn unpickle_pre_0_8(state: &State, arg: PyObj) -> PyReturn {
    pickle::decode_pre_0_8_instant(arg.expect_bytes()?)
        .ok_or_value_err(pickle::INVALID_DATA)?
        .to_obj(*state.instant_type)
}

fn timestamp(
    cls: PyClass<Instant>,
    slf: Instant,
    args: &[PyObj],
    kwargs: &mut IterKwargs,
) -> PyReturn {
    handle_no_args("timestamp", args)?;
    let unit = handle_one_kwarg("timestamp", *cls.state().strs.unit, kwargs)?
        .map(|value| TimestampUnit::from_py(value, cls.state()))
        .transpose()?
        .unwrap_or(TimestampUnit::Second);
    unit.timestamp(slf).to_py()
}

fn timestamp_millis(cls: PyClass<Instant>, slf: Instant) -> PyReturn {
    warn_deprecated(
        cls.state(),
        c"timestamp_millis() is deprecated; use timestamp(unit='millisecond') instead",
        1,
    )?;
    slf.timestamp_millis().to_py()
}

fn timestamp_nanos(cls: PyClass<Instant>, slf: Instant) -> PyReturn {
    warn_deprecated(
        cls.state(),
        c"timestamp_nanos() is deprecated; use timestamp(unit='nanosecond') instead",
        1,
    )?;
    slf.timestamp_nanos().to_py()
}

fn from_timestamp(cls: PyClass<Instant>, args: &[PyObj], kwargs: &mut IterKwargs) -> PyReturn {
    let value = handle_one_arg("from_timestamp", args)?;
    let unit = handle_one_kwarg("from_timestamp", *cls.state().strs.unit, kwargs)?
        .map(|value| TimestampUnit::from_py(value, cls.state()))
        .transpose()?
        .unwrap_or(TimestampUnit::Second);
    unit.parse(value)?.to_obj(cls)
}

fn from_timestamp_millis(cls: PyClass<Instant>, ts: PyObj) -> PyReturn {
    warn_deprecated(
        cls.state(),
        c"from_timestamp_millis() is deprecated; use from_timestamp(..., unit='millisecond') instead",
        1,
    )?;
    parse_timestamp_millis(ts)?.to_obj(cls)
}

fn from_timestamp_nanos(cls: PyClass<Instant>, ts: PyObj) -> PyReturn {
    warn_deprecated(
        cls.state(),
        c"from_timestamp_nanos() is deprecated; use from_timestamp(..., unit='nanosecond') instead",
        1,
    )?;
    parse_timestamp_nanos(ts)?.to_obj(cls)
}

fn to_stdlib(cls: PyClass<Instant>, slf: Instant) -> PyReturn {
    slf.to_stdlib_datetime(cls.state().py_api()?)
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
    format_args::format_datetime_iso(date, time, cls.state(), args, kwargs, Suffix::Zulu)
}

fn parse_iso(cls: PyClass<Instant>, s_obj: PyObj) -> PyReturn {
    OffsetDateTime::parse_iso(
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

    match handle_opt_arg(fname, args)? {
        Some(arg) => {
            if kwargs.original_len() != 0 {
                raise_mixed_args(fname)?;
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
        None => {
            let tdelta = timedelta_from_kwargs(fname, kwargs, state)?;
            instant
                .shift(tdelta.negate_if(negate))
                .ok_or_range_err()?
                .to_obj(cls)
        }
    }
}

fn difference(cls: PyClass<Instant>, slf: Instant, obj_b: PyObj) -> PyReturn {
    let state = cls.state();
    let inst_b = parse_instant_arg("difference", obj_b, state)?;
    slf.diff(inst_b).to_obj(*state.time_delta_type)
}

fn to_tz(cls: PyClass<Instant>, slf: Instant, tz_obj: PyObj) -> PyReturn {
    let state = cls.state();
    slf.into_zoned_obj(state.load_tz(tz_obj)?, *state.zoned_datetime_type)
}

fn to_fixed_offset(cls: PyClass<Instant>, slf: Instant, args: &[PyObj]) -> PyReturn {
    let state = cls.state();
    match handle_opt_arg("to_fixed_offset", args)? {
        None => slf.to_utc_plain().assume_offset_unchecked(Offset::ZERO),
        Some(arg) => slf
            .to_offset(Offset::from_py(arg, state)?)
            .ok_or_range_err()?,
    }
    .to_obj(*state.offset_datetime_type)
}

fn to_system_tz(cls: PyClass<Instant>, slf: Instant) -> PyReturn {
    let state = cls.state();
    warn_deprecated(
        state,
        c"to_system_tz() is deprecated; use to_tz(SYSTEM_TZ) instead",
        1,
    )?;
    slf.into_zoned_obj(state.tz_store.get_system_tz()?, *state.zoned_datetime_type)
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
    } = round::Args::parse(args, kwargs, cls.state(), round::ArgsContext::Standard)?;
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

fn format(cls: PyClass<Instant>, slf: Instant, pattern_obj: PyObj) -> PyReturn {
    let pattern_pystr = pattern_obj
        .cast_exact::<PyStr>()
        .ok_or_type_err("format() argument must be str")?;
    let pattern_str = pattern_pystr.as_utf8()?;
    let pattern = pattern::CompiledPattern::compile(pattern_str).into_value_err()?;
    pattern.validate(
        pattern::CategorySet::DATE_TIME_OFFSET,
        "Instant",
        *cls.state().warn_whenever,
        *cls.state().warn_deprecation,
    )?;
    pattern.format(
        &slf.to_utc_plain()
            .pattern_values()
            .with_offset(Offset::ZERO),
    )
}

fn __format__(cls: PyClass<Instant>, slf: Instant, spec_obj: PyObj) -> PyReturn {
    if spec_obj.is_truthy()? {
        format(cls, slf, spec_obj)
    } else {
        __str__(cls.into(), slf)
    }
}

fn parse(cls: PyClass<Instant>, args: &[PyObj], kwargs: &mut IterKwargs) -> PyReturn {
    let s_obj = handle_one_arg("parse", args)?;
    let s_pystr = s_obj
        .cast_exact::<PyStr>()
        .ok_or_type_err("parse() argument must be str")?;
    let s = s_pystr.as_utf8()?;

    let fmt_obj = parse_pattern_keyword(kwargs, cls.state())?;
    let fmt_pystr = fmt_obj
        .cast_exact::<PyStr>()
        .ok_or_type_err("pattern must be str")?;
    let fmt_bytes = fmt_pystr.as_utf8()?;

    let pattern = pattern::CompiledPattern::compile(fmt_bytes).into_value_err()?;
    pattern.validate(
        pattern::CategorySet::DATE_TIME_OFFSET,
        "Instant",
        *cls.state().warn_whenever,
        *cls.state().warn_deprecation,
    )?;
    let parsed = pattern.parse(s).into_value_err()?;
    let offset = parsed
        .offset_secs
        .ok_or_value_err("Instant.parse() pattern must include an offset field (x/X)")?;
    let date = parsed
        .date("Pattern must include year (YYYY/YY), month (MM/MMM/MMMM), and day (DD) fields")?;
    let time = parsed.time()?;
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
    method1!(Instant, exact_eq, doc::EXACTTIME_STRICT_EQ),
    method1!(Instant, strict_eq, doc::EXACTTIME_STRICT_EQ),
    method_kwargs!(Instant, timestamp, doc::EXACTTIME_TIMESTAMP),
    method0!(Instant, timestamp_millis, doc::EXACTTIME_TIMESTAMP_MILLIS),
    method0!(Instant, timestamp_nanos, doc::EXACTTIME_TIMESTAMP_NANOS),
    classmethod_kwargs!(Instant, from_timestamp, doc::INSTANT_FROM_TIMESTAMP),
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
