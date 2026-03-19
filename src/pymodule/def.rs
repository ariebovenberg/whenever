//! The core definitions of the `whenever` Python module
use crate::{
    classes::{
        date::{self, unpickle as _unpkl_date},
        date_delta::{self, days, months, unpickle as _unpkl_ddelta, weeks, years},
        datetime_delta::{self, unpickle as _unpkl_dtdelta},
        instant::{self, unpickle as _unpkl_inst, unpickle_pre_0_8 as _unpkl_utc},
        itemized_date_delta::{self, unpickle as _unpkl_iddelta},
        itemized_delta::{self, unpickle as _unpkl_idelta},
        monthday::{self, unpickle as _unpkl_md},
        offset_datetime::{self, unpickle as _unpkl_offset},
        plain_datetime::{self, unpickle as _unpkl_local},
        time::{self, unpickle as _unpkl_time},
        time_delta::{
            self, hours, microseconds, milliseconds, minutes, nanoseconds, seconds,
            unpickle as _unpkl_tdelta,
        },
        yearmonth::{self, unpickle as _unpkl_ym},
        zoned_datetime::{self, unpickle as _unpkl_zoned},
    },
    common::round,
    docstrings as doc,
    py::*,
    pymodule::{
        patch::{_patch_time_frozen, _patch_time_keep_ticking, _unpatch_time, Patch},
        tzconf::*,
        utils::*,
    },
    tz::store::TzStore,
};
use core::{
    ffi::{c_int, c_void},
    mem::{self, MaybeUninit},
    ptr::null_mut as NULL,
};
use pyo3_ffi::*;

#[allow(static_mut_refs)]
pub(crate) static mut MODULE_DEF: PyModuleDef = PyModuleDef {
    m_base: PyModuleDef_HEAD_INIT,
    m_name: c"whenever".as_ptr(),
    m_doc: c"Modern datetime library for Python".as_ptr(),
    m_size: mem::size_of::<MaybeUninit<Option<State>>>() as _,
    m_methods: unsafe { METHODS.as_mut_ptr() },
    m_slots: unsafe { MODULE_SLOTS.as_mut_ptr() },
    m_traverse: Some({
        unsafe extern "C" fn _wrap(
            module: *mut PyObject,
            visit: visitproc,
            arg: *mut c_void,
        ) -> c_int {
            match module_traverse(module, visit, arg) {
                Ok(()) => 0,
                Err(n) => n,
            }
        }
        _wrap
    }),
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
    modmethod_vararg!(_unpkl_iddelta, c""),
    modmethod_vararg!(_unpkl_idelta, c""),
    modmethod1!(_unpkl_local, c""),
    modmethod1!(_unpkl_inst, c""),
    modmethod1!(_unpkl_utc, c""), // for backwards compatibility
    modmethod1!(_unpkl_offset, c""),
    modmethod_vararg!(_unpkl_zoned, c""),
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
    modmethod1!(_patch_time_frozen, c""),
    modmethod1!(_patch_time_keep_ticking, c""),
    modmethod0!(_unpatch_time, c""),
    modmethod1!(_set_tzpath, c""),
    modmethod0!(_clear_tz_cache, c""),
    modmethod1!(_clear_tz_cache_by_keys, c""),
    modmethod0!(reset_system_tz, doc::RESET_SYSTEM_TZ),
    PyMethodDef::zeroed(),
];

static mut MODULE_SLOTS: &mut [PyModuleDef_Slot] = &mut [
    PyModuleDef_Slot {
        slot: Py_mod_exec,
        value: {
            extern "C" fn _wrap(arg: *mut PyObject) -> c_int {
                catch_panic!(
                    match module_exec(unsafe { PyModule::from_ptr_unchecked(arg) }) {
                        Ok(_) => 0,
                        Err(_) => -1,
                    },
                    -1,
                    "Rust panic in module exec: "
                )
            }
            _wrap
        } as *mut c_void,
    },
    #[cfg(Py_3_13)]
    PyModuleDef_Slot {
        slot: Py_mod_multiple_interpreters,
        value: Py_MOD_PER_INTERPRETER_GIL_SUPPORTED,
    },
    #[cfg(Py_3_13)]
    PyModuleDef_Slot {
        slot: Py_mod_gil,
        value: Py_MOD_GIL_NOT_USED,
    },
    PyModuleDef_Slot {
        slot: 0,
        value: NULL(),
    },
];

#[cold]
fn module_exec(module: PyModule) -> PyResult<()> {
    // Initialize state to None to get it out of uninitialized state ASAP,
    // as any further calls could trigger a GC cycle which would retrieve
    // the state.
    let state = module.state().write(None);
    let module_name = "whenever".to_py()?;

    let (date_type, unpickle_date) = new_class(
        module,
        module_name.borrow(),
        &mut unsafe { date::SPEC },
        c"_unpkl_date",
    )?;
    create_singletons(*date_type, date::SINGLETONS)?;
    let (yearmonth_type, unpickle_yearmonth) = new_class(
        module,
        module_name.borrow(),
        &mut unsafe { yearmonth::SPEC },
        c"_unpkl_ym",
    )?;
    create_singletons(*yearmonth_type, yearmonth::SINGLETONS)?;
    let (monthday_type, unpickle_monthday) = new_class(
        module,
        module_name.borrow(),
        &mut unsafe { monthday::SPEC },
        c"_unpkl_md",
    )?;
    create_singletons(*monthday_type, monthday::SINGLETONS)?;
    let (time_type, unpickle_time) = new_class(
        module,
        module_name.borrow(),
        &mut unsafe { time::SPEC },
        c"_unpkl_time",
    )?;
    create_singletons(*time_type, time::SINGLETONS)?;
    let (date_delta_type, unpickle_date_delta) = new_class(
        module,
        module_name.borrow(),
        &mut unsafe { date_delta::SPEC },
        c"_unpkl_ddelta",
    )?;
    create_singletons(*date_delta_type, date_delta::SINGLETONS)?;
    let (time_delta_type, unpickle_time_delta) = new_class(
        module,
        module_name.borrow(),
        &mut unsafe { time_delta::SPEC },
        c"_unpkl_tdelta",
    )?;
    create_singletons(*time_delta_type, time_delta::SINGLETONS)?;
    let (datetime_delta_type, unpickle_datetime_delta) = new_class(
        module,
        module_name.borrow(),
        &mut unsafe { datetime_delta::SPEC },
        c"_unpkl_dtdelta",
    )?;
    create_singletons(*datetime_delta_type, datetime_delta::SINGLETONS)?;
    let (itemized_date_delta_type, unpickle_itemized_date_delta) = new_class(
        module,
        module_name.borrow(),
        &mut unsafe { itemized_date_delta::SPEC },
        c"_unpkl_iddelta",
    )?;
    itemized_date_delta::register_as_mapping(itemized_date_delta_type.borrow().as_py_obj())?;
    let (itemized_delta_type, unpickle_itemized_delta) = new_class(
        module,
        module_name.borrow(),
        &mut unsafe { itemized_delta::SPEC },
        c"_unpkl_idelta",
    )?;
    itemized_date_delta::register_as_mapping(itemized_delta_type.borrow().as_py_obj())?;
    let (plain_datetime_type, unpickle_plain_datetime) = new_class(
        module,
        module_name.borrow(),
        &mut unsafe { plain_datetime::SPEC },
        c"_unpkl_local",
    )?;
    create_singletons(*plain_datetime_type, plain_datetime::SINGLETONS)?;
    let (instant_type, unpickle_instant) = new_class(
        module,
        module_name.borrow(),
        &mut unsafe { instant::SPEC },
        c"_unpkl_inst",
    )?;
    create_singletons(*instant_type, instant::SINGLETONS)?;
    let (offset_datetime_type, unpickle_offset_datetime) = new_class(
        module,
        module_name.borrow(),
        &mut unsafe { offset_datetime::SPEC },
        c"_unpkl_offset",
    )?;
    let (zoned_datetime_type, unpickle_zoned_datetime) = new_class(
        module,
        module_name.borrow(),
        &mut unsafe { zoned_datetime::SPEC },
        c"_unpkl_zoned",
    )?;
    module
        .getattr(c"_unpkl_utc")?
        .setattr(c"__module__", module_name.borrow())?;

    unsafe { PyDateTime_IMPORT() };
    let py_api = match unsafe { PyDateTimeAPI().as_ref() } {
        Some(api) => api,
        None => Err(PyErrMarker())?,
    };

    // NOTE: getting strptime from the C API `DateTimeType` results in crashes
    // with subinterpreters. Thus we import it through Python.
    let strptime = import(c"datetime")?
        .getattr(c"datetime")?
        .getattr(c"strptime")?;
    let time_ns = import(c"time")?.getattr(c"time_ns")?;

    let weekday_enum = new_enum(
        module,
        module_name.borrow(),
        "Weekday",
        "MONDAY TUESDAY WEDNESDAY THURSDAY FRIDAY SATURDAY SUNDAY",
    )?;

    let exc_repeated = new_exception(
        module,
        c"whenever.RepeatedTime",
        doc::REPEATEDTIME,
        unsafe { PyExc_ValueError },
    )?;
    let exc_skipped = new_exception(module, c"whenever.SkippedTime", doc::SKIPPEDTIME, unsafe {
        PyExc_ValueError
    })?;
    let exc_invalid_offset = new_exception(
        module,
        c"whenever.InvalidOffsetError",
        doc::INVALIDOFFSETERROR,
        unsafe { PyExc_ValueError },
    )?;
    let exc_implicitly_ignoring_dst = new_exception(
        module,
        c"whenever.ImplicitlyIgnoringDST",
        doc::IMPLICITLYIGNORINGDST,
        unsafe { PyExc_TypeError },
    )?;
    let exc_tz_notfound = new_exception(
        module,
        c"whenever.TimeZoneNotFoundError",
        doc::TIMEZONENOTFOUNDERROR,
        unsafe { PyExc_ValueError },
    )?;

    // Warning classes (UserWarning hierarchy)
    let warn_potential_dst_bug = new_exception(
        module,
        c"whenever.PotentialDstBugWarning",
        doc::POTENTIALDSTBUGWARNING,
        unsafe { PyExc_UserWarning },
    )?;
    let warn_days_not_always_24h = new_exception(
        module,
        c"whenever.DaysNotAlways24HoursWarning",
        doc::DAYSNOTALWAYS24HOURSWARNING,
        warn_potential_dst_bug.as_ptr(),
    )?;
    let warn_potentially_stale_offset = new_exception(
        module,
        c"whenever.PotentiallyStaleOffsetWarning",
        doc::POTENTIALLYSTALEOFFSETWARNING,
        warn_potential_dst_bug.as_ptr(),
    )?;
    let warn_tz_unaware_arithmetic = new_exception(
        module,
        c"whenever.TimeZoneUnawareArithmeticWarning",
        doc::TIMEZONEUNAWAREARITHMETICWARNING,
        warn_potential_dst_bug.as_ptr(),
    )?;
    let warn_deprecation = new_exception(
        module,
        c"whenever.WheneverDeprecationWarning",
        doc::WHENEVERDEPRECATIONWARNING,
        unsafe { PyExc_UserWarning },
    )?;

    // ContextVars for suppressing warnings
    let cv_ignore_days_not_always_24h =
        ContextVarBool::create(c"_ignore_days_not_always_24h_warning", module)?;
    let cv_ignore_potentially_stale_offset =
        ContextVarBool::create(c"_ignore_potentially_stale_offset_warning", module)?;
    let cv_ignore_tz_unaware_arithmetic =
        ContextVarBool::create(c"_ignore_timezone_unaware_arithmetic_warning", module)?;

    let time_patch = Patch::new()?;
    let tz_store = TzStore::new(*exc_tz_notfound)?;

    // Only write the state once everything is initialized,
    // to ensure we don't leak references to the above.
    state.replace(State {
        date_type: date_type.py_owned(),
        yearmonth_type: yearmonth_type.py_owned(),
        monthday_type: monthday_type.py_owned(),
        time_type: time_type.py_owned(),
        date_delta_type: date_delta_type.py_owned(),
        time_delta_type: time_delta_type.py_owned(),
        datetime_delta_type: datetime_delta_type.py_owned(),
        itemized_date_delta_type: itemized_date_delta_type.py_owned(),
        itemized_delta_type: itemized_delta_type.py_owned(),
        plain_datetime_type: plain_datetime_type.py_owned(),
        instant_type: instant_type.py_owned(),
        offset_datetime_type: offset_datetime_type.py_owned(),
        zoned_datetime_type: zoned_datetime_type.py_owned(),

        py_api,
        strptime: strptime.py_owned(),
        time_ns: time_ns.py_owned(),
        weekday_enum_members: [
            weekday_enum.getattr(c"MONDAY")?.py_owned(),
            weekday_enum.getattr(c"TUESDAY")?.py_owned(),
            weekday_enum.getattr(c"WEDNESDAY")?.py_owned(),
            weekday_enum.getattr(c"THURSDAY")?.py_owned(),
            weekday_enum.getattr(c"FRIDAY")?.py_owned(),
            weekday_enum.getattr(c"SATURDAY")?.py_owned(),
            weekday_enum.getattr(c"SUNDAY")?.py_owned(),
        ],
        zoneinfo_type: LazyImport::new(c"zoneinfo", c"ZoneInfo"),
        get_pydantic_schema: LazyImport::new(c"whenever._utils", c"pydantic_schema"),

        str_years: intern(c"years")?.py_owned(),
        str_months: intern(c"months")?.py_owned(),
        str_weeks: intern(c"weeks")?.py_owned(),
        str_days: intern(c"days")?.py_owned(),
        str_hours: intern(c"hours")?.py_owned(),
        str_minutes: intern(c"minutes")?.py_owned(),
        str_seconds: intern(c"seconds")?.py_owned(),
        str_milliseconds: intern(c"milliseconds")?.py_owned(),
        str_microseconds: intern(c"microseconds")?.py_owned(),
        str_nanoseconds: intern(c"nanoseconds")?.py_owned(),
        str_year: intern(c"year")?.py_owned(),
        str_month: intern(c"month")?.py_owned(),
        str_day: intern(c"day")?.py_owned(),
        str_week: intern(c"week")?.py_owned(),
        str_hour: intern(c"hour")?.py_owned(),
        str_minute: intern(c"minute")?.py_owned(),
        str_second: intern(c"second")?.py_owned(),
        str_millisecond: intern(c"millisecond")?.py_owned(),
        str_microsecond: intern(c"microsecond")?.py_owned(),
        str_nanosecond: intern(c"nanosecond")?.py_owned(),
        str_compatible: intern(c"compatible")?.py_owned(),
        str_raise: intern(c"raise")?.py_owned(),
        str_earlier: intern(c"earlier")?.py_owned(),
        str_later: intern(c"later")?.py_owned(),
        str_tz: intern(c"tz")?.py_owned(),
        str_disambiguate: intern(c"disambiguate")?.py_owned(),
        str_offset: intern(c"offset")?.py_owned(),
        str_ignore_dst: intern(c"ignore_dst")?.py_owned(),
        str_total: intern(c"total")?.py_owned(),
        str_unit: intern(c"unit")?.py_owned(),
        str_in_units: intern(c"in_units")?.py_owned(),
        str_increment: intern(c"increment")?.py_owned(),
        str_mode: intern(c"mode")?.py_owned(),
        str_round_mode: intern(c"round_mode")?.py_owned(),
        str_round_increment: intern(c"round_increment")?.py_owned(),
        str_round_unit: intern(c"round_unit")?.py_owned(),
        str_relative_to: intern(c"relative_to")?.py_owned(),
        round_mode_strs: round::ModeStrs {
            str_floor: intern(c"floor")?.py_owned(),
            str_ceil: intern(c"ceil")?.py_owned(),
            str_trunc: intern(c"trunc")?.py_owned(),
            str_expand: intern(c"expand")?.py_owned(),
            str_half_floor: intern(c"half_floor")?.py_owned(),
            str_half_ceil: intern(c"half_ceil")?.py_owned(),
            str_half_even: intern(c"half_even")?.py_owned(),
            str_half_trunc: intern(c"half_trunc")?.py_owned(),
            str_half_expand: intern(c"half_expand")?.py_owned(),
        },
        str_format: intern(c"format")?.py_owned(),
        str_sep: intern(c"sep")?.py_owned(),
        str_space: intern(c" ")?.py_owned(),
        str_t: intern(c"T")?.py_owned(),
        str_auto: intern(c"auto")?.py_owned(),
        str_basic: intern(c"basic")?.py_owned(),
        str_always: intern(c"always")?.py_owned(),
        str_never: intern(c"never")?.py_owned(),
        str_lowercase_units: intern(c"lowercase_units")?.py_owned(),
        str_offset_mismatch: intern(c"offset_mismatch")?.py_owned(),
        str_keep_instant: intern(c"keep_instant")?.py_owned(),
        str_keep_local: intern(c"keep_local")?.py_owned(),

        exc_repeated: exc_repeated.py_owned(),
        exc_skipped: exc_skipped.py_owned(),
        exc_invalid_offset: exc_invalid_offset.py_owned(),
        exc_implicitly_ignoring_dst: exc_implicitly_ignoring_dst.py_owned(),
        exc_tz_notfound: exc_tz_notfound.py_owned(),

        warn_potential_dst_bug: warn_potential_dst_bug.py_owned(),
        warn_days_not_always_24h: warn_days_not_always_24h.py_owned(),
        warn_potentially_stale_offset: warn_potentially_stale_offset.py_owned(),
        warn_tz_unaware_arithmetic: warn_tz_unaware_arithmetic.py_owned(),
        warn_deprecation: warn_deprecation.py_owned(),

        cv_ignore_days_not_always_24h,
        cv_ignore_potentially_stale_offset,
        cv_ignore_tz_unaware_arithmetic,

        unpickle_date: unpickle_date.py_owned(),
        unpickle_yearmonth: unpickle_yearmonth.py_owned(),
        unpickle_monthday: unpickle_monthday.py_owned(),
        unpickle_time: unpickle_time.py_owned(),
        unpickle_date_delta: unpickle_date_delta.py_owned(),
        unpickle_time_delta: unpickle_time_delta.py_owned(),
        unpickle_datetime_delta: unpickle_datetime_delta.py_owned(),
        unpickle_itemized_date_delta: unpickle_itemized_date_delta.py_owned(),
        unpickle_itemized_delta: unpickle_itemized_delta.py_owned(),
        unpickle_plain_datetime: unpickle_plain_datetime.py_owned(),
        unpickle_instant: unpickle_instant.py_owned(),
        unpickle_offset_datetime: unpickle_offset_datetime.py_owned(),
        unpickle_zoned_datetime: unpickle_zoned_datetime.py_owned(),

        time_patch,
        tz_store,
    });
    Ok(())
}

fn traverse_type(
    target: *mut PyTypeObject,
    visit: visitproc,
    arg: *mut c_void,
    num_singletons: usize,
) -> TraverseResult {
    if !target.is_null() {
        // XXX: This trick SEEMS to let us avoid adding GC support to our types.
        // Since our types are atomic and immutable this should be allowed...
        // ...BUT there is a reference cycle between the class and the
        // singleton instances (e.g. the Date.MAX instance and Date class itself)
        // Visiting the type once for each singleton should make GC aware of this.
        // NOTE: the +1 is for the type itself
        for _ in 0..(num_singletons + 1) {
            traverse(target.cast(), visit, arg)?;
        }
    }
    Ok(())
}

fn module_traverse(mod_ptr: *mut PyObject, visit: visitproc, arg: *mut c_void) -> TraverseResult {
    // SAFETY: We're passed a valid PyModule pointer
    let module = unsafe { PyModule::from_ptr_unchecked(mod_ptr) };
    // SAFETY: `module_exec` initialized the state immediately to `None`
    // so it's safe to access--even though it hasn't been fully populated yet.
    let Some(state) = (unsafe { module.state().assume_init_mut() }) else {
        // i.e. `module_exec` hasn't finished yet
        return Ok(());
    };

    // types
    for (cls, unpkl, num_singletons) in [
        (
            state.date_type.inner(),
            state.unpickle_date,
            date::SINGLETONS.len(),
        ),
        (
            state.yearmonth_type.inner(),
            state.unpickle_yearmonth,
            yearmonth::SINGLETONS.len(),
        ),
        (
            state.monthday_type.inner(),
            state.unpickle_monthday,
            monthday::SINGLETONS.len(),
        ),
        (
            state.time_type.inner(),
            state.unpickle_time,
            time::SINGLETONS.len(),
        ),
        (
            state.date_delta_type.inner(),
            state.unpickle_date_delta,
            date_delta::SINGLETONS.len(),
        ),
        (
            state.time_delta_type.inner(),
            state.unpickle_time_delta,
            time_delta::SINGLETONS.len(),
        ),
        (
            state.datetime_delta_type.inner(),
            state.unpickle_datetime_delta,
            datetime_delta::SINGLETONS.len(),
        ),
        (
            state.itemized_date_delta_type.inner(),
            state.unpickle_itemized_date_delta,
            0,
        ),
        (
            state.itemized_delta_type.inner(),
            state.unpickle_itemized_delta,
            0,
        ),
        (
            state.plain_datetime_type.inner(),
            state.unpickle_plain_datetime,
            plain_datetime::SINGLETONS.len(),
        ),
        (
            state.instant_type.inner(),
            state.unpickle_instant,
            instant::SINGLETONS.len(),
        ),
        (
            state.offset_datetime_type.inner(),
            state.unpickle_offset_datetime,
            0,
        ),
        (
            state.zoned_datetime_type.inner(),
            state.unpickle_zoned_datetime,
            0,
        ),
    ] {
        traverse_type(cls.as_ptr().cast(), visit, arg, num_singletons)?;
        traverse(unpkl.as_ptr(), visit, arg)?;
    }

    // enum members
    for member in state.weekday_enum_members.into_iter() {
        traverse(member.as_ptr(), visit, arg)?;
    }

    // exceptions
    for exc in [
        state.exc_repeated,
        state.exc_skipped,
        state.exc_invalid_offset,
        state.exc_implicitly_ignoring_dst,
        state.exc_tz_notfound,
    ] {
        traverse(exc.as_ptr(), visit, arg)?;
    }

    // warnings
    for w in [
        state.warn_potential_dst_bug,
        state.warn_days_not_always_24h,
        state.warn_potentially_stale_offset,
        state.warn_tz_unaware_arithmetic,
        state.warn_deprecation,
    ] {
        traverse(w.as_ptr(), visit, arg)?;
    }

    // context vars
    for cv in [
        state.cv_ignore_days_not_always_24h,
        state.cv_ignore_potentially_stale_offset,
        state.cv_ignore_tz_unaware_arithmetic,
    ] {
        traverse(cv.as_ptr(), visit, arg)?;
    }

    // Imported stuff
    traverse(state.strptime.as_ptr(), visit, arg)?;
    traverse(state.time_ns.as_ptr(), visit, arg)?;
    state.zoneinfo_type.traverse(visit, arg)?;
    state.get_pydantic_schema.traverse(visit, arg)?;
    Ok(())
}

#[cold]
unsafe extern "C" fn module_clear(mod_ptr: *mut PyObject) -> c_int {
    // SAFETY: We're passed a valid PyModule pointer
    let module = unsafe { PyModule::from_ptr_unchecked(mod_ptr) };
    // SAFETY: `module_exec` initialized the state immediately to `None`
    // so it's safe to access--even though it hasn't been fully populated yet.
    let Some(state) = (unsafe { module.state().assume_init_mut() }) else {
        // i.e. `module_exec` hasn't finished yet
        return 0;
    };
    unsafe {
        // types
        Py_CLEAR((&raw mut state.date_type).cast());
        Py_CLEAR((&raw mut state.yearmonth_type).cast());
        Py_CLEAR((&raw mut state.monthday_type).cast());
        Py_CLEAR((&raw mut state.time_type).cast());
        Py_CLEAR((&raw mut state.date_delta_type).cast());
        Py_CLEAR((&raw mut state.time_delta_type).cast());
        Py_CLEAR((&raw mut state.datetime_delta_type).cast());
        Py_CLEAR((&raw mut state.itemized_date_delta_type).cast());
        Py_CLEAR((&raw mut state.itemized_delta_type).cast());
        Py_CLEAR((&raw mut state.plain_datetime_type).cast());
        Py_CLEAR((&raw mut state.instant_type).cast());
        Py_CLEAR((&raw mut state.offset_datetime_type).cast());
        Py_CLEAR((&raw mut state.zoned_datetime_type).cast());

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
        Py_CLEAR((&raw mut state.str_week).cast());
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
        Py_CLEAR((&raw mut state.str_total).cast());
        Py_CLEAR((&raw mut state.str_unit).cast());
        Py_CLEAR((&raw mut state.str_in_units).cast());
        Py_CLEAR((&raw mut state.str_increment).cast());
        Py_CLEAR((&raw mut state.str_mode).cast());
        Py_CLEAR((&raw mut state.str_round_mode).cast());
        Py_CLEAR((&raw mut state.str_round_increment).cast());
        Py_CLEAR((&raw mut state.str_round_unit).cast());
        Py_CLEAR((&raw mut state.str_relative_to).cast());
        Py_CLEAR((&raw mut state.round_mode_strs.str_floor).cast());
        Py_CLEAR((&raw mut state.round_mode_strs.str_ceil).cast());
        Py_CLEAR((&raw mut state.round_mode_strs.str_trunc).cast());
        Py_CLEAR((&raw mut state.round_mode_strs.str_expand).cast());
        Py_CLEAR((&raw mut state.round_mode_strs.str_half_floor).cast());
        Py_CLEAR((&raw mut state.round_mode_strs.str_half_ceil).cast());
        Py_CLEAR((&raw mut state.round_mode_strs.str_half_even).cast());
        Py_CLEAR((&raw mut state.round_mode_strs.str_half_trunc).cast());
        Py_CLEAR((&raw mut state.round_mode_strs.str_half_expand).cast());
        Py_CLEAR((&raw mut state.str_format).cast());
        Py_CLEAR((&raw mut state.str_sep).cast());
        Py_CLEAR((&raw mut state.str_space).cast());
        Py_CLEAR((&raw mut state.str_t).cast());
        Py_CLEAR((&raw mut state.str_auto).cast());
        Py_CLEAR((&raw mut state.str_basic).cast());
        Py_CLEAR((&raw mut state.str_always).cast());
        Py_CLEAR((&raw mut state.str_never).cast());
        Py_CLEAR((&raw mut state.str_lowercase_units).cast());
        Py_CLEAR((&raw mut state.str_offset_mismatch).cast());
        Py_CLEAR((&raw mut state.str_keep_instant).cast());
        Py_CLEAR((&raw mut state.str_keep_local).cast());

        // unpickling functions
        Py_CLEAR((&raw mut state.unpickle_date).cast());
        Py_CLEAR((&raw mut state.unpickle_yearmonth).cast());
        Py_CLEAR((&raw mut state.unpickle_monthday).cast());
        Py_CLEAR((&raw mut state.unpickle_time).cast());
        Py_CLEAR((&raw mut state.unpickle_date_delta).cast());
        Py_CLEAR((&raw mut state.unpickle_time_delta).cast());
        Py_CLEAR((&raw mut state.unpickle_datetime_delta).cast());
        Py_CLEAR((&raw mut state.unpickle_itemized_date_delta).cast());
        Py_CLEAR((&raw mut state.unpickle_itemized_delta).cast());
        Py_CLEAR((&raw mut state.unpickle_plain_datetime).cast());
        Py_CLEAR((&raw mut state.unpickle_instant).cast());
        Py_CLEAR((&raw mut state.unpickle_offset_datetime).cast());
        Py_CLEAR((&raw mut state.unpickle_zoned_datetime).cast());

        // exceptions
        Py_CLEAR((&raw mut state.exc_repeated).cast());
        Py_CLEAR((&raw mut state.exc_skipped).cast());
        Py_CLEAR((&raw mut state.exc_invalid_offset).cast());
        Py_CLEAR((&raw mut state.exc_implicitly_ignoring_dst).cast());
        Py_CLEAR((&raw mut state.exc_tz_notfound).cast());

        // warnings
        Py_CLEAR((&raw mut state.warn_potential_dst_bug).cast());
        Py_CLEAR((&raw mut state.warn_days_not_always_24h).cast());
        Py_CLEAR((&raw mut state.warn_potentially_stale_offset).cast());
        Py_CLEAR((&raw mut state.warn_tz_unaware_arithmetic).cast());
        Py_CLEAR((&raw mut state.warn_deprecation).cast());

        // context vars
        Py_CLEAR((&raw mut state.cv_ignore_days_not_always_24h).cast());
        Py_CLEAR((&raw mut state.cv_ignore_potentially_stale_offset).cast());
        Py_CLEAR((&raw mut state.cv_ignore_tz_unaware_arithmetic).cast());

        // imported stuff
        Py_CLEAR((&raw mut state.strptime).cast());
        Py_CLEAR((&raw mut state.time_ns).cast());
    }

    0
}

#[cold]
unsafe extern "C" fn module_free(mod_ptr: *mut c_void) {
    // SAFETY: We're passed a valid PyModule pointer
    let module = unsafe { PyModule::from_ptr_unchecked(mod_ptr.cast()) };
    // SAFETY: `module_exec` initialized the state immediately to `None`
    // so it's safe to access--even though it hasn't been fully populated yet.
    (unsafe { module.state().assume_init_mut() }).take();
}

// NOTE: The module state owns references to all the listed fields.
// The module __dict__ cannot be relied on because technically
// they can be deleted from it.
pub(crate) struct State {
    // classes
    pub(crate) date_type: HeapType<date::Date>,
    pub(crate) yearmonth_type: HeapType<yearmonth::YearMonth>,
    pub(crate) monthday_type: HeapType<monthday::MonthDay>,
    pub(crate) time_type: HeapType<time::Time>,
    pub(crate) date_delta_type: HeapType<date_delta::DateDelta>,
    pub(crate) time_delta_type: HeapType<time_delta::TimeDelta>,
    pub(crate) datetime_delta_type: HeapType<datetime_delta::DateTimeDelta>,
    pub(crate) itemized_date_delta_type: HeapType<itemized_date_delta::ItemizedDateDelta>,
    pub(crate) itemized_delta_type: HeapType<itemized_delta::ItemizedDelta>,
    pub(crate) plain_datetime_type: HeapType<plain_datetime::DateTime>,
    pub(crate) instant_type: HeapType<instant::Instant>,
    pub(crate) offset_datetime_type: HeapType<offset_datetime::OffsetDateTime>,
    pub(crate) zoned_datetime_type: HeapType<zoned_datetime::ZonedDateTime>,

    pub(crate) weekday_enum_members: [PyObj; 7],

    // exceptions
    pub(crate) exc_repeated: PyObj,
    pub(crate) exc_skipped: PyObj,
    pub(crate) exc_invalid_offset: PyObj,
    pub(crate) exc_implicitly_ignoring_dst: PyObj,
    pub(crate) exc_tz_notfound: PyObj,

    // warnings
    pub(crate) warn_potential_dst_bug: PyObj,
    pub(crate) warn_days_not_always_24h: PyObj,
    pub(crate) warn_potentially_stale_offset: PyObj,
    pub(crate) warn_tz_unaware_arithmetic: PyObj,
    pub(crate) warn_deprecation: PyObj,

    // context vars (for suppressing warnings)
    pub(crate) cv_ignore_days_not_always_24h: ContextVarBool,
    pub(crate) cv_ignore_potentially_stale_offset: ContextVarBool,
    pub(crate) cv_ignore_tz_unaware_arithmetic: ContextVarBool,

    // unpickling functions
    pub(crate) unpickle_date: PyObj,
    pub(crate) unpickle_yearmonth: PyObj,
    pub(crate) unpickle_monthday: PyObj,
    pub(crate) unpickle_time: PyObj,
    pub(crate) unpickle_date_delta: PyObj,
    pub(crate) unpickle_time_delta: PyObj,
    pub(crate) unpickle_datetime_delta: PyObj,
    pub(crate) unpickle_itemized_date_delta: PyObj,
    pub(crate) unpickle_itemized_delta: PyObj,
    pub(crate) unpickle_plain_datetime: PyObj,
    pub(crate) unpickle_instant: PyObj,
    pub(crate) unpickle_offset_datetime: PyObj,
    pub(crate) unpickle_zoned_datetime: PyObj,

    pub(crate) py_api: &'static PyDateTime_CAPI,

    // imported stuff
    pub(crate) strptime: PyObj,
    pub(crate) time_ns: PyObj,
    pub(crate) zoneinfo_type: LazyImport,
    pub(crate) get_pydantic_schema: LazyImport,

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
    pub(crate) str_week: PyObj,
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
    pub(crate) str_total: PyObj,
    pub(crate) str_unit: PyObj,
    pub(crate) str_in_units: PyObj,
    pub(crate) str_increment: PyObj,
    pub(crate) str_mode: PyObj,
    pub(crate) str_round_mode: PyObj,
    pub(crate) str_round_increment: PyObj,
    pub(crate) str_round_unit: PyObj,
    pub(crate) str_relative_to: PyObj,
    pub(crate) round_mode_strs: round::ModeStrs,
    pub(crate) str_format: PyObj,
    pub(crate) str_sep: PyObj,
    pub(crate) str_space: PyObj,
    pub(crate) str_t: PyObj,
    pub(crate) str_auto: PyObj,
    pub(crate) str_basic: PyObj,
    pub(crate) str_always: PyObj,
    pub(crate) str_never: PyObj,
    pub(crate) str_lowercase_units: PyObj,
    pub(crate) str_offset_mismatch: PyObj,
    pub(crate) str_keep_instant: PyObj,
    pub(crate) str_keep_local: PyObj,

    pub(crate) time_patch: Patch,
    pub(crate) tz_store: TzStore,
}
