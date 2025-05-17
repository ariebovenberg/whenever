use crate::{
    classes::{
        date::{self, unpickle as _unpkl_date},
        date_delta::{self, days, months, unpickle as _unpkl_ddelta, weeks, years},
        datetime_delta::{self, unpickle as _unpkl_dtdelta},
        instant::{self, unpickle as _unpkl_inst, unpickle_pre_0_8 as _unpkl_utc},
        monthday::{self, unpickle as _unpkl_md},
        offset_datetime::{self, unpickle as _unpkl_offset},
        plain_datetime::{self, unpickle as _unpkl_local},
        system_datetime::{self, unpickle as _unpkl_system},
        time::{self, unpickle as _unpkl_time},
        time_delta::{
            self, hours, microseconds, milliseconds, minutes, nanoseconds, seconds,
            unpickle as _unpkl_tdelta,
        },
        yearmonth::{self, unpickle as _unpkl_ym},
        zoned_datetime::{self, unpickle as _unpkl_zoned},
    },
    docstrings as doc,
    tz::cache::TzStore,
};
use core::{
    ffi::{c_int, c_void},
    mem,
    ptr::null_mut as NULL,
};
use pyo3_ffi::*;

use crate::{
    common::{pyobject::*, pytype::*},
    pymodule::patch::{Patch, _patch_time_frozen, _patch_time_keep_ticking, _unpatch_time},
    pymodule::tzconf::*,
    pymodule::utils::*,
};

#[allow(static_mut_refs)]
pub(crate) static mut MODULE_DEF: PyModuleDef = PyModuleDef {
    m_base: PyModuleDef_HEAD_INIT,
    m_name: c"whenever".as_ptr(),
    m_doc: c"Modern datetime library for Python".as_ptr(),
    m_size: mem::size_of::<State>() as _,
    m_methods: unsafe { METHODS.as_mut_ptr() },
    m_slots: unsafe { MODULE_SLOTS.as_mut_ptr() },
    m_traverse: Some(module_traverse),
    m_clear: Some(module_clear),
    m_free: Some(module_free),
};

static mut METHODS: &mut [PyMethodDef] = &mut [
    modmethod1!(_unpkl_date, c""),
    modmethod1!(_unpkl_ym, c""),
    modmethod1!(_unpkl_md, c""),
    modmethod1!(_unpkl_time, c""),
    modmethod_vararg!(_unpkl_ddelta, c""),
    modmethod1!(_unpkl_tdelta, c""),
    modmethod_vararg!(_unpkl_dtdelta, c""),
    modmethod1!(_unpkl_local, c""),
    modmethod1!(_unpkl_inst, c""),
    modmethod1!(_unpkl_utc, c""), // for backwards compatibility
    modmethod1!(_unpkl_offset, c""),
    modmethod_vararg!(_unpkl_zoned, c""),
    modmethod1!(_unpkl_system, c""),
    // FUTURE: set __module__ on these
    modmethod1!(years, doc::YEARS),
    modmethod1!(months, doc::MONTHS),
    modmethod1!(weeks, doc::WEEKS),
    modmethod1!(days, doc::DAYS),
    modmethod1!(hours, doc::HOURS),
    modmethod1!(minutes, doc::MINUTES),
    modmethod1!(seconds, doc::SECONDS),
    modmethod1!(milliseconds, doc::MILLISECONDS),
    modmethod1!(microseconds, doc::MICROSECONDS),
    modmethod1!(nanoseconds, doc::NANOSECONDS),
    method!(_patch_time_frozen, c"", METH_O),
    method!(_patch_time_keep_ticking, c"", METH_O),
    method!(_unpatch_time, c""),
    method!(_set_tzpath, c"", METH_O),
    method!(_clear_tz_cache, c""),
    method!(_clear_tz_cache_by_keys, c"", METH_O),
    PyMethodDef::zeroed(),
];

macro_rules! wrap_errcode {
    ($meth:ident) => {{
        unsafe extern "C" fn _wrap(arg: *mut PyObject) -> c_int {
            match $meth(arg) {
                Ok(_) => 0,
                Err(_) => -1,
            }
        }
        _wrap
    }};
}

static mut MODULE_SLOTS: &mut [PyModuleDef_Slot] = &mut [
    PyModuleDef_Slot {
        slot: Py_mod_exec,
        value: wrap_errcode!(module_exec) as *mut c_void,
    },
    #[cfg(Py_3_13)]
    PyModuleDef_Slot {
        slot: Py_mod_multiple_interpreters,
        // awaiting https://github.com/python/cpython/pull/102995
        value: Py_MOD_PER_INTERPRETER_GIL_SUPPORTED,
    },
    // FUTURE: set this once we've ensured that:
    // - tz cache is threadsafe
    // - we safely handle non-threadsafe modules: datetime, zoneinfo
    #[cfg(Py_3_13)]
    PyModuleDef_Slot {
        slot: Py_mod_gil,
        value: Py_MOD_GIL_USED,
    },
    PyModuleDef_Slot {
        slot: 0,
        value: NULL(),
    },
];

#[cold]
unsafe fn module_exec(module: *mut PyObject) -> PyResult<()> {
    let state = State::for_mod_mut(module);
    let module_name = "whenever".to_py()?;
    defer_decref!(module_name);

    new_class(
        module,
        module_name,
        &raw mut date::SPEC,
        c"_unpkl_date",
        date::SINGLETONS,
        &mut state.date_type,
        &mut state.unpickle_date,
    )?;
    new_class(
        module,
        module_name,
        &raw mut yearmonth::SPEC,
        c"_unpkl_ym",
        yearmonth::SINGLETONS,
        &mut state.yearmonth_type,
        &mut state.unpickle_yearmonth,
    )?;
    new_class(
        module,
        module_name,
        &raw mut monthday::SPEC,
        c"_unpkl_md",
        monthday::SINGLETONS,
        &mut state.monthday_type,
        &mut state.unpickle_monthday,
    )?;
    new_class(
        module,
        module_name,
        &raw mut time::SPEC,
        c"_unpkl_time",
        time::SINGLETONS,
        &mut state.time_type,
        &mut state.unpickle_time,
    )?;
    new_class(
        module,
        module_name,
        &raw mut date_delta::SPEC,
        c"_unpkl_ddelta",
        date_delta::SINGLETONS,
        &mut state.date_delta_type,
        &mut state.unpickle_date_delta,
    )?;
    new_class(
        module,
        module_name,
        &raw mut time_delta::SPEC,
        c"_unpkl_tdelta",
        time_delta::SINGLETONS,
        &mut state.time_delta_type,
        &mut state.unpickle_time_delta,
    )?;
    new_class(
        module,
        module_name,
        &raw mut datetime_delta::SPEC,
        c"_unpkl_dtdelta",
        datetime_delta::SINGLETONS,
        &mut state.datetime_delta_type,
        &mut state.unpickle_datetime_delta,
    )?;
    new_class(
        module,
        module_name,
        &raw mut plain_datetime::SPEC,
        c"_unpkl_local",
        plain_datetime::SINGLETONS,
        &mut state.plain_datetime_type,
        &mut state.unpickle_plain_datetime,
    )?;
    new_class(
        module,
        module_name,
        &raw mut instant::SPEC,
        c"_unpkl_inst",
        instant::SINGLETONS,
        &mut state.instant_type,
        &mut state.unpickle_instant,
    )?;
    new_class(
        module,
        module_name,
        &raw mut offset_datetime::SPEC,
        c"_unpkl_offset",
        offset_datetime::SINGLETONS,
        &mut state.offset_datetime_type,
        &mut state.unpickle_offset_datetime,
    )?;
    new_class(
        module,
        module_name,
        &raw mut zoned_datetime::SPEC,
        c"_unpkl_zoned",
        zoned_datetime::SINGLETONS,
        &mut state.zoned_datetime_type,
        &mut state.unpickle_zoned_datetime,
    )?;
    new_class(
        module,
        module_name,
        &raw mut system_datetime::SPEC,
        c"_unpkl_system",
        system_datetime::SINGLETONS,
        &mut state.system_datetime_type,
        &mut state.unpickle_system_datetime,
    )?;
    patch_dunder_module(module, module_name, c"_unpkl_utc")?;

    PyDateTime_IMPORT();
    state.py_api = match PyDateTimeAPI().as_ref() {
        Some(api) => api,
        None => Err(PyErrOccurred())?,
    };
    // NOTE: getting strptime from the C API `DateTimeType` results in crashes
    // with subinterpreters. Thus we import it through Python.
    let datetime_cls = import_from(c"datetime", c"datetime")?;
    defer_decref!(datetime_cls);
    state.strptime = PyObj::from_ptr_unchecked(
        PyObject_GetAttrString(datetime_cls, c"strptime".as_ptr()).as_result()?,
    );
    state.time_ns = import_from(c"time", c"time_ns")?;

    let weekday_enum = new_enum(
        PyObj::from_ptr_unchecked(module),
        "Weekday",
        &[
            (c"MONDAY", 1),
            (c"TUESDAY", 2),
            (c"WEDNESDAY", 3),
            (c"THURSDAY", 4),
            (c"FRIDAY", 5),
            (c"SATURDAY", 6),
            (c"SUNDAY", 7),
        ],
    )?;

    state.weekday_enum_members = [
        weekday_enum.getattr(c"MONDAY")?.into_py(),
        weekday_enum.getattr(c"TUESDAY")?.into_py(),
        weekday_enum.getattr(c"WEDNESDAY")?.into_py(),
        weekday_enum.getattr(c"THURSDAY")?.into_py(),
        weekday_enum.getattr(c"FRIDAY")?.into_py(),
        weekday_enum.getattr(c"SATURDAY")?.into_py(),
        weekday_enum.getattr(c"SUNDAY")?.into_py(),
    ];

    state.str_years = intern(c"years")?;
    state.str_months = intern(c"months")?;
    state.str_weeks = intern(c"weeks")?;
    state.str_days = intern(c"days")?;
    state.str_hours = intern(c"hours")?;
    state.str_minutes = intern(c"minutes")?;
    state.str_seconds = intern(c"seconds")?;
    state.str_milliseconds = intern(c"milliseconds")?;
    state.str_microseconds = intern(c"microseconds")?;
    state.str_nanoseconds = intern(c"nanoseconds")?;
    state.str_year = intern(c"year")?;
    state.str_month = intern(c"month")?;
    state.str_day = intern(c"day")?;
    state.str_hour = intern(c"hour")?;
    state.str_minute = intern(c"minute")?;
    state.str_second = intern(c"second")?;
    state.str_millisecond = intern(c"millisecond")?;
    state.str_microsecond = intern(c"microsecond")?;
    state.str_nanosecond = intern(c"nanosecond")?;
    state.str_compatible = intern(c"compatible")?;
    state.str_raise = intern(c"raise")?;
    state.str_earlier = intern(c"earlier")?;
    state.str_later = intern(c"later")?;
    state.str_tz = intern(c"tz")?;
    state.str_disambiguate = intern(c"disambiguate")?;
    state.str_offset = intern(c"offset")?;
    state.str_ignore_dst = intern(c"ignore_dst")?;
    state.str_unit = intern(c"unit")?;
    state.str_increment = intern(c"increment")?;
    state.str_mode = intern(c"mode")?;
    state.str_floor = intern(c"floor")?;
    state.str_ceil = intern(c"ceil")?;
    state.str_half_floor = intern(c"half_floor")?;
    state.str_half_ceil = intern(c"half_ceil")?;
    state.str_half_even = intern(c"half_even")?;
    state.str_format = intern(c"format")?;

    state.exc_repeated = new_exception(
        module,
        c"whenever.RepeatedTime",
        doc::REPEATEDTIME,
        PyExc_ValueError,
    )?;
    state.exc_skipped = new_exception(
        module,
        c"whenever.SkippedTime",
        doc::SKIPPEDTIME,
        PyExc_ValueError,
    )?;
    state.exc_invalid_offset = new_exception(
        module,
        c"whenever.InvalidOffsetError",
        doc::INVALIDOFFSETERROR,
        PyExc_ValueError,
    )?;
    state.exc_implicitly_ignoring_dst = new_exception(
        module,
        c"whenever.ImplicitlyIgnoringDST",
        doc::IMPLICITLYIGNORINGDST,
        PyExc_TypeError,
    )?;
    state.exc_tz_notfound = new_exception(
        module,
        c"whenever.TimeZoneNotFoundError",
        doc::TIMEZONENOTFOUNDERROR,
        PyExc_ValueError,
    )?;

    state.time_patch = Patch::new()?;

    // Fields with heap allocated data.
    // We write these fields manually, to avoid triggering a "drop" of the previous value
    // which isn't there, since Python just allocated this memory for us.
    (&raw mut state.tz_store).write(TzStore::new()?);
    (&raw mut state.zoneinfo_type).write(LazyImport::new(c"zoneinfo", c"ZoneInfo"));
    Ok(())
}

unsafe fn traverse(target: *mut PyObject, visit: visitproc, arg: *mut c_void) {
    if !target.is_null() {
        (visit)(target, arg);
    }
}
unsafe fn traverse_type(
    target: *mut PyTypeObject,
    visit: visitproc,
    arg: *mut c_void,
    num_singletons: usize,
) {
    if !target.is_null() {
        // XXX: This trick SEEMS to let us avoid adding GC support to our types.
        // Since our types are atomic and immutable this should be allowed...
        // ...BUT there is a reference cycle between the class and the
        // singleton instances (e.g. the Date.MAX instance and Date class itself)
        // Visiting the type once for each singleton should make GC aware of this.
        for _ in 0..(num_singletons + 1) {
            (visit)(target.cast(), arg);
        }
    }
}

unsafe extern "C" fn module_traverse(
    module: *mut PyObject,
    visit: visitproc,
    arg: *mut c_void,
) -> c_int {
    let state = State::for_mod(module);

    // types
    for (class, num_singletons) in [
        (state.date_type.inner, date::SINGLETONS.len()),
        (state.yearmonth_type.inner, yearmonth::SINGLETONS.len()),
        (state.monthday_type.inner, monthday::SINGLETONS.len()),
        (state.time_type.inner, time::SINGLETONS.len()),
        (state.date_delta_type.inner, date_delta::SINGLETONS.len()),
        (state.time_delta_type.inner, time_delta::SINGLETONS.len()),
        (
            state.datetime_delta_type.inner,
            datetime_delta::SINGLETONS.len(),
        ),
        (
            state.plain_datetime_type.inner,
            plain_datetime::SINGLETONS.len(),
        ),
        (state.instant_type.inner, instant::SINGLETONS.len()),
        (
            state.offset_datetime_type.inner,
            offset_datetime::SINGLETONS.len(),
        ),
        (
            state.zoned_datetime_type.inner,
            zoned_datetime::SINGLETONS.len(),
        ),
        (
            state.system_datetime_type.inner,
            system_datetime::SINGLETONS.len(),
        ),
    ] {
        traverse_type(class.as_ptr().cast(), visit, arg, num_singletons);
    }

    // enum members
    for &member in state.weekday_enum_members.iter() {
        traverse(member.as_ptr(), visit, arg);
    }

    // exceptions
    for exc in [
        state.exc_repeated,
        state.exc_skipped,
        state.exc_invalid_offset,
        state.exc_implicitly_ignoring_dst,
        state.exc_tz_notfound,
    ] {
        traverse(exc.as_ptr(), visit, arg);
    }

    // Imported modules
    traverse(state.strptime.as_ptr(), visit, arg);
    traverse(state.time_ns, visit, arg);

    state.zoneinfo_type.traverse(visit, arg);

    0
}

#[cold]
unsafe extern "C" fn module_clear(module: *mut PyObject) -> c_int {
    let state = State::for_mod_mut(module);
    // types
    Py_CLEAR((&raw mut state.date_type).cast());
    Py_CLEAR((&raw mut state.yearmonth_type).cast());
    Py_CLEAR((&raw mut state.monthday_type).cast());
    Py_CLEAR((&raw mut state.time_type).cast());
    Py_CLEAR((&raw mut state.date_delta_type).cast());
    Py_CLEAR((&raw mut state.time_delta_type).cast());
    Py_CLEAR((&raw mut state.datetime_delta_type).cast());
    Py_CLEAR((&raw mut state.plain_datetime_type).cast());
    Py_CLEAR((&raw mut state.instant_type).cast());
    Py_CLEAR((&raw mut state.offset_datetime_type).cast());
    Py_CLEAR((&raw mut state.zoned_datetime_type).cast());
    Py_CLEAR((&raw mut state.system_datetime_type).cast());

    // enum members
    Py_CLEAR((&raw mut state.weekday_enum_members[0]).cast());
    Py_CLEAR((&raw mut state.weekday_enum_members[1]).cast());
    Py_CLEAR((&raw mut state.weekday_enum_members[2]).cast());
    Py_CLEAR((&raw mut state.weekday_enum_members[3]).cast());
    Py_CLEAR((&raw mut state.weekday_enum_members[4]).cast());
    Py_CLEAR((&raw mut state.weekday_enum_members[5]).cast());
    Py_CLEAR((&raw mut state.weekday_enum_members[6]).cast());

    // interned strings
    Py_CLEAR((&raw mut state.str_years).cast());
    Py_CLEAR((&raw mut state.str_months).cast());
    Py_CLEAR((&raw mut state.str_weeks).cast());
    Py_CLEAR((&raw mut state.str_days).cast());
    Py_CLEAR((&raw mut state.str_hours).cast());
    Py_CLEAR((&raw mut state.str_minutes).cast());
    Py_CLEAR((&raw mut state.str_seconds).cast());
    Py_CLEAR((&raw mut state.str_milliseconds).cast());
    Py_CLEAR((&raw mut state.str_microseconds).cast());
    Py_CLEAR((&raw mut state.str_nanoseconds).cast());
    Py_CLEAR((&raw mut state.str_year).cast());
    Py_CLEAR((&raw mut state.str_month).cast());
    Py_CLEAR((&raw mut state.str_day).cast());
    Py_CLEAR((&raw mut state.str_hour).cast());
    Py_CLEAR((&raw mut state.str_minute).cast());
    Py_CLEAR((&raw mut state.str_second).cast());
    Py_CLEAR((&raw mut state.str_millisecond).cast());
    Py_CLEAR((&raw mut state.str_microsecond).cast());
    Py_CLEAR((&raw mut state.str_nanosecond).cast());
    Py_CLEAR((&raw mut state.str_compatible).cast());
    Py_CLEAR((&raw mut state.str_raise).cast());
    Py_CLEAR((&raw mut state.str_earlier).cast());
    Py_CLEAR((&raw mut state.str_later).cast());
    Py_CLEAR((&raw mut state.str_tz).cast());
    Py_CLEAR((&raw mut state.str_disambiguate).cast());
    Py_CLEAR((&raw mut state.str_offset).cast());
    Py_CLEAR((&raw mut state.str_ignore_dst).cast());
    Py_CLEAR((&raw mut state.str_unit).cast());
    Py_CLEAR((&raw mut state.str_increment).cast());
    Py_CLEAR((&raw mut state.str_mode).cast());
    Py_CLEAR((&raw mut state.str_floor).cast());
    Py_CLEAR((&raw mut state.str_ceil).cast());
    Py_CLEAR((&raw mut state.str_half_floor).cast());
    Py_CLEAR((&raw mut state.str_half_ceil).cast());
    Py_CLEAR((&raw mut state.str_half_even).cast());
    Py_CLEAR((&raw mut state.str_format).cast());

    // exceptions
    Py_CLEAR((&raw mut state.exc_repeated).cast());
    Py_CLEAR((&raw mut state.exc_skipped).cast());
    Py_CLEAR((&raw mut state.exc_invalid_offset).cast());
    Py_CLEAR((&raw mut state.exc_implicitly_ignoring_dst).cast());
    Py_CLEAR((&raw mut state.exc_tz_notfound).cast());

    // imported stuff
    Py_CLEAR((&raw mut state.strptime).cast());
    Py_CLEAR(&raw mut state.time_ns);

    0
}

#[cold]
unsafe extern "C" fn module_free(module: *mut c_void) {
    let state = State::for_mod_mut(module.cast());
    // We clean up heap allocated stuff here because module_clear is
    // not *guaranteed* to be called
    (&raw mut state.tz_store).drop_in_place();
    (&raw mut state.zoneinfo_type).drop_in_place();
}

pub(crate) struct State {
    // types
    pub(crate) date_type: HeapType<date::Date>,
    pub(crate) yearmonth_type: HeapType<yearmonth::YearMonth>,
    pub(crate) monthday_type: HeapType<monthday::MonthDay>,
    pub(crate) time_type: HeapType<time::Time>,
    pub(crate) date_delta_type: HeapType<date_delta::DateDelta>,
    pub(crate) time_delta_type: HeapType<time_delta::TimeDelta>,
    pub(crate) datetime_delta_type: HeapType<datetime_delta::DateTimeDelta>,
    pub(crate) plain_datetime_type: HeapType<plain_datetime::DateTime>,
    pub(crate) instant_type: HeapType<instant::Instant>,
    pub(crate) offset_datetime_type: HeapType<offset_datetime::OffsetDateTime>,
    pub(crate) zoned_datetime_type: HeapType<zoned_datetime::ZonedDateTime>,
    pub(crate) system_datetime_type: HeapType<offset_datetime::OffsetDateTime>,

    // weekday enum
    pub(crate) weekday_enum_members: [PyObj; 7],

    // exceptions
    pub(crate) exc_repeated: PyObj,
    pub(crate) exc_skipped: PyObj,
    pub(crate) exc_invalid_offset: PyObj,
    pub(crate) exc_implicitly_ignoring_dst: PyObj,
    pub(crate) exc_tz_notfound: PyObj,

    // unpickling functions
    // TODO safety
    pub(crate) unpickle_date: PyObj,
    pub(crate) unpickle_yearmonth: PyObj,
    pub(crate) unpickle_monthday: PyObj,
    pub(crate) unpickle_time: PyObj,
    pub(crate) unpickle_date_delta: PyObj,
    pub(crate) unpickle_time_delta: PyObj,
    pub(crate) unpickle_datetime_delta: PyObj,
    pub(crate) unpickle_plain_datetime: PyObj,
    pub(crate) unpickle_instant: PyObj,
    pub(crate) unpickle_offset_datetime: PyObj,
    pub(crate) unpickle_zoned_datetime: PyObj,
    pub(crate) unpickle_system_datetime: PyObj,

    pub(crate) py_api: &'static PyDateTime_CAPI,

    // imported stuff
    pub(crate) strptime: PyObj,
    pub(crate) time_ns: *mut PyObject,
    pub(crate) zoneinfo_type: LazyImport,

    // strings
    pub(crate) str_years: PyObj,
    pub(crate) str_months: PyObj,
    pub(crate) str_weeks: PyObj,
    pub(crate) str_days: PyObj,
    pub(crate) str_hours: PyObj,
    pub(crate) str_minutes: PyObj,
    pub(crate) str_seconds: PyObj,
    pub(crate) str_milliseconds: PyObj,
    pub(crate) str_microseconds: PyObj,
    pub(crate) str_nanoseconds: PyObj,
    pub(crate) str_year: PyObj,
    pub(crate) str_month: PyObj,
    pub(crate) str_day: PyObj,
    pub(crate) str_hour: PyObj,
    pub(crate) str_minute: PyObj,
    pub(crate) str_second: PyObj,
    pub(crate) str_millisecond: PyObj,
    pub(crate) str_microsecond: PyObj,
    pub(crate) str_nanosecond: PyObj,
    pub(crate) str_compatible: PyObj,
    pub(crate) str_raise: PyObj,
    pub(crate) str_earlier: PyObj,
    pub(crate) str_later: PyObj,
    pub(crate) str_tz: PyObj,
    pub(crate) str_disambiguate: PyObj,
    pub(crate) str_offset: PyObj,
    pub(crate) str_ignore_dst: PyObj,
    pub(crate) str_unit: PyObj,
    pub(crate) str_increment: PyObj,
    pub(crate) str_mode: PyObj,
    pub(crate) str_floor: PyObj,
    pub(crate) str_ceil: PyObj,
    pub(crate) str_half_floor: PyObj,
    pub(crate) str_half_ceil: PyObj,
    pub(crate) str_half_even: PyObj,
    pub(crate) str_format: PyObj,

    pub(crate) time_patch: Patch,

    pub(crate) tz_store: TzStore,
}

impl State {
    pub(crate) unsafe fn for_type<'a>(tp: *mut PyTypeObject) -> &'a Self {
        PyType_GetModuleState(tp).cast::<Self>().as_ref().unwrap()
    }

    pub(crate) unsafe fn for_mod<'a>(module: *mut PyObject) -> &'a Self {
        PyModule_GetState(module).cast::<Self>().as_ref().unwrap()
    }

    pub(crate) unsafe fn for_mod_mut<'a>(module: *mut PyObject) -> &'a mut Self {
        PyModule_GetState(module).cast::<Self>().as_mut().unwrap()
    }
}
