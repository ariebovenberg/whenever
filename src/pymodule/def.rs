//! The core definitions of the `whenever` Python module
use crate::{
    classes::{
        date::{self, unpickle as _unpkl_date},
        instant::{self, unpickle as _unpkl_inst, unpickle_pre_0_8 as _unpkl_utc},
        offset_datetime::{self, unpickle as _unpkl_offset},
        plain_datetime::{self, unpickle as _unpkl_local},
        time::{self, unpickle as _unpkl_time},
        time_delta::{
            self, hours, microseconds, milliseconds, minutes, nanoseconds, seconds,
            unpickle as _unpkl_tdelta,
        },
        zoned_datetime::{self, unpickle as _unpkl_zoned},
    },
    common::{
        round,
        sync::{OncePyCell, SwapPtr},
    },
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
    modmethod1!(_unpkl_time, c""),
    modmethod1!(_unpkl_tdelta, c""),
    modmethod1!(_unpkl_local, c""),
    modmethod1!(_unpkl_inst, c""),
    modmethod1!(_unpkl_utc, c""), // for backwards compatibility
    modmethod1!(_unpkl_offset, c""),
    modmethod_vararg!(_unpkl_zoned, c""),
    // FUTURE: set __module__ on these
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
    modmethod0!(_get_tzpath, c""),
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
    // Emit marker so tests can detect debug builds and assert cleanup.
    #[cfg(debug_assertions)]
    eprintln!("[whenever] module_exec (debug)");
    // Initialize state to None to get it out of uninitialized state ASAP,
    // as any further calls could trigger a GC cycle which would retrieve
    // the state.
    let state = module.state().write(None);
    let module_name = "whenever".to_py()?;

    let (date_type, unpickle_date) = new_class(
        module,
        *module_name,
        &mut unsafe { date::SPEC },
        c"_unpkl_date",
    )?;
    create_singletons(*date_type, date::SINGLETONS)?;
    let (time_type, unpickle_time) = new_class(
        module,
        *module_name,
        &mut unsafe { time::SPEC },
        c"_unpkl_time",
    )?;
    create_singletons(*time_type, time::SINGLETONS)?;
    let (time_delta_type, unpickle_time_delta) = new_class(
        module,
        *module_name,
        &mut unsafe { time_delta::SPEC },
        c"_unpkl_tdelta",
    )?;
    create_singletons(*time_delta_type, time_delta::SINGLETONS)?;
    let (plain_datetime_type, unpickle_plain_datetime) = new_class(
        module,
        *module_name,
        &mut unsafe { plain_datetime::SPEC },
        c"_unpkl_local",
    )?;
    create_singletons(*plain_datetime_type, plain_datetime::SINGLETONS)?;
    let (instant_type, unpickle_instant) = new_class(
        module,
        *module_name,
        &mut unsafe { instant::SPEC },
        c"_unpkl_inst",
    )?;
    create_singletons(*instant_type, instant::SINGLETONS)?;
    let (offset_datetime_type, unpickle_offset_datetime) = new_class(
        module,
        *module_name,
        &mut unsafe { offset_datetime::SPEC },
        c"_unpkl_offset",
    )?;
    let (zoned_datetime_type, unpickle_zoned_datetime) = new_class(
        module,
        *module_name,
        &mut unsafe { zoned_datetime::SPEC },
        c"_unpkl_zoned",
    )?;
    module
        .getattr(c"_unpkl_utc")?
        .setattr(c"__module__", *module_name)?;

    unsafe { PyDateTime_IMPORT() };
    match unsafe { PyDateTimeAPI().as_ref() } {
        Some(_) => {}
        None => Err(PyErrMarker)?,
    };

    let exc_repeated = new_exception(
        module,
        c"whenever.RepeatedTime",
        doc::REPEATEDTIME,
        exc_value_error(),
    )?;
    let exc_skipped = new_exception(
        module,
        c"whenever.SkippedTime",
        doc::SKIPPEDTIME,
        exc_value_error(),
    )?;
    let exc_invalid_offset = new_exception(
        module,
        c"whenever.InvalidOffsetError",
        doc::INVALIDOFFSETERROR,
        exc_value_error(),
    )?;
    let exc_tz_notfound = new_exception(
        module,
        c"whenever.TimeZoneNotFoundError",
        doc::TIMEZONENOTFOUNDERROR,
        exc_value_error(),
    )?;

    // Warning classes (UserWarning hierarchy)
    let warn_potential_dst_bug = new_exception(
        module,
        c"whenever.PotentialDstBugWarning",
        doc::POTENTIALDSTBUGWARNING,
        exc_user_warning(),
    )?;
    let warn_days_not_always_24h = new_exception(
        module,
        c"whenever.DaysAssumed24HoursWarning",
        doc::DAYSASSUMED24HOURSWARNING,
        *warn_potential_dst_bug,
    )?;
    let warn_potentially_stale_offset = new_exception(
        module,
        c"whenever.StaleOffsetWarning",
        doc::STALEOFFSETWARNING,
        *warn_potential_dst_bug,
    )?;
    let warn_naive_arithmetic = new_exception(
        module,
        c"whenever.NaiveArithmeticWarning",
        doc::NAIVEARITHMETICWARNING,
        *warn_potential_dst_bug,
    )?;

    let tz_store = TzStore::new(*exc_tz_notfound);

    // Only write the state once everything is initialized,
    // to ensure we don't leak references to the above.
    state.replace(State {
        date_type,
        time_type,
        time_delta_type,
        itemized_date_delta_type: OncePyObj::new(|| {
            import(c"whenever._ideltas")?.getattr(c"ItemizedDateDelta")
        }),
        itemized_delta_type: OncePyObj::new(|| {
            import(c"whenever._ideltas")?.getattr(c"ItemizedDelta")
        }),
        plain_datetime_type,
        instant_type,
        offset_datetime_type,
        zoned_datetime_type,

        yearmonth_type: OncePyObj::new(|| import(c"whenever._shared")?.getattr(c"YearMonth")),
        monthday_type: OncePyObj::new(|| import(c"whenever._shared")?.getattr(c"MonthDay")),
        isoweekdate_new: OncePyObj::new(|| {
            import(c"whenever._shared")?
                .getattr(c"IsoWeekDate")?
                .getattr(c"_from_parts_unchecked")
        }),
        weekday_enum_members: OncePyCell::new(|| {
            let shared_module = import(c"whenever._shared")?;
            let weekday_enum = shared_module.getattr(c"Weekday")?;
            Ok([
                weekday_enum.getattr(c"MONDAY")?,
                weekday_enum.getattr(c"TUESDAY")?,
                weekday_enum.getattr(c"WEDNESDAY")?,
                weekday_enum.getattr(c"THURSDAY")?,
                weekday_enum.getattr(c"FRIDAY")?,
                weekday_enum.getattr(c"SATURDAY")?,
                weekday_enum.getattr(c"SUNDAY")?,
            ])
        }),

        py_api: SwapPtr::new(None),
        // NOTE: getting strptime from the C API `DateTimeType` results in crashes
        // with subinterpreters. Thus we import it through Python.
        strptime: OncePyObj::new(|| {
            import(c"datetime")?
                .getattr(c"datetime")?
                .getattr(c"strptime")
        }),
        time_ns: OncePyObj::new(|| import(c"time")?.getattr(c"time_ns")),
        zoneinfo_type: OncePyObj::new(|| import(c"zoneinfo")?.getattr(c"ZoneInfo")),
        get_pydantic_schema: OncePyObj::new(|| {
            import(c"whenever._utils")?.getattr(c"pydantic_schema")
        }),

        str_years: intern(c"years")?,
        str_months: intern(c"months")?,
        str_weeks: intern(c"weeks")?,
        str_days: intern(c"days")?,
        str_hours: intern(c"hours")?,
        str_minutes: intern(c"minutes")?,
        str_seconds: intern(c"seconds")?,
        str_milliseconds: intern(c"milliseconds")?,
        str_microseconds: intern(c"microseconds")?,
        str_nanoseconds: intern(c"nanoseconds")?,
        str_year: intern(c"year")?,
        str_month: intern(c"month")?,
        str_day: intern(c"day")?,
        str_week: intern(c"week")?,
        str_hour: intern(c"hour")?,
        str_minute: intern(c"minute")?,
        str_second: intern(c"second")?,
        str_millisecond: intern(c"millisecond")?,
        str_microsecond: intern(c"microsecond")?,
        str_nanosecond: intern(c"nanosecond")?,
        str_compatible: intern(c"compatible")?,
        str_raise: intern(c"raise")?,
        str_earlier: intern(c"earlier")?,
        str_later: intern(c"later")?,
        str_tz: intern(c"tz")?,
        str_disambiguate: intern(c"disambiguate")?,
        str_offset: intern(c"offset")?,
        str_total: intern(c"total")?,
        str_unit: intern(c"unit")?,
        str_in_units: intern(c"in_units")?,
        str_increment: intern(c"increment")?,
        str_mode: intern(c"mode")?,
        str_round_mode: intern(c"round_mode")?,
        str_round_increment: intern(c"round_increment")?,
        str_relative_to: intern(c"relative_to")?,
        round_mode_strs: round::ModeStrs {
            str_floor: intern(c"floor")?,
            str_ceil: intern(c"ceil")?,
            str_trunc: intern(c"trunc")?,
            str_expand: intern(c"expand")?,
            str_half_floor: intern(c"half_floor")?,
            str_half_ceil: intern(c"half_ceil")?,
            str_half_even: intern(c"half_even")?,
            str_half_trunc: intern(c"half_trunc")?,
            str_half_expand: intern(c"half_expand")?,
        },
        str_format: intern(c"format")?,
        str_sep: intern(c"sep")?,
        str_space: intern(c" ")?,
        str_t: intern(c"T")?,
        str_auto: intern(c"auto")?,
        str_basic: intern(c"basic")?,
        str_always: intern(c"always")?,
        str_never: intern(c"never")?,

        str_offset_mismatch: intern(c"offset_mismatch")?,
        str_keep_instant: intern(c"keep_instant")?,
        str_keep_local: intern(c"keep_local")?,
        str_days_assumed_24h_ok: intern(c"days_assumed_24h_ok")?,
        str_stale_offset_ok: intern(c"stale_offset_ok")?,
        str_naive_arithmetic_ok: intern(c"naive_arithmetic_ok")?,
        str_week_mon: intern(c"week_mon")?,
        str_week_sun: intern(c"week_sun")?,

        exc_repeated,
        exc_skipped,
        exc_invalid_offset,
        exc_tz_notfound,

        warn_potential_dst_bug,
        warn_days_not_always_24h,
        warn_potentially_stale_offset,
        warn_naive_arithmetic,

        unpickle_date,
        unpickle_time,
        unpickle_time_delta,
        unpickle_itemized_date_delta: OncePyObj::new(|| {
            import(c"whenever._ideltas")?.getattr(c"_unpkl_iddelta")
        }),
        unpickle_itemized_delta: OncePyObj::new(|| {
            import(c"whenever._ideltas")?.getattr(c"_unpkl_idelta")
        }),
        unpickle_plain_datetime,
        unpickle_instant,
        unpickle_offset_datetime,
        unpickle_zoned_datetime,

        time_patch: Patch::new()?,
        tz_store,
    });

    Ok(())
}

fn traverse_type(
    target: PyType,
    visit: visitproc,
    arg: *mut c_void,
    num_singletons: usize,
) -> TraverseResult {
    // XXX: This trick SEEMS to let us avoid adding GC support to our types.
    // Since our types are atomic and immutable this should be allowed...
    // ...BUT there is a reference cycle between the class and the
    // singleton instances (e.g. the Date.MAX instance and Date class itself)
    // Visiting the type once for each singleton should make GC aware of this.
    // NOTE: the +1 is for the type itself
    for _ in 0..(num_singletons + 1) {
        traverse(target.as_ptr(), visit, arg)?;
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
            *state.unpickle_date,
            date::SINGLETONS.len(),
        ),
        (
            state.time_type.inner(),
            *state.unpickle_time,
            time::SINGLETONS.len(),
        ),
        (
            state.time_delta_type.inner(),
            *state.unpickle_time_delta,
            time_delta::SINGLETONS.len(),
        ),
        (
            state.plain_datetime_type.inner(),
            *state.unpickle_plain_datetime,
            plain_datetime::SINGLETONS.len(),
        ),
        (
            state.instant_type.inner(),
            *state.unpickle_instant,
            instant::SINGLETONS.len(),
        ),
        (
            state.offset_datetime_type.inner(),
            *state.unpickle_offset_datetime,
            0,
        ),
        (
            state.zoned_datetime_type.inner(),
            *state.unpickle_zoned_datetime,
            0,
        ),
    ] {
        traverse_type(cls, visit, arg, num_singletons)?;
        unpkl.gc_traverse(visit, arg)?;
    }

    // Lazily imported from _shared and _ideltas
    state.yearmonth_type.gc_traverse(visit, arg)?;
    state.monthday_type.gc_traverse(visit, arg)?;
    state.isoweekdate_new.gc_traverse(visit, arg)?;
    state.itemized_date_delta_type.gc_traverse(visit, arg)?;
    state.itemized_delta_type.gc_traverse(visit, arg)?;
    state.unpickle_itemized_date_delta.gc_traverse(visit, arg)?;
    state.unpickle_itemized_delta.gc_traverse(visit, arg)?;

    // enum members
    if let Some(members) = state.weekday_enum_members.get_if_init() {
        for m in members.iter() {
            m.gc_traverse(visit, arg)?;
        }
    }

    // exceptions and warnings
    for exc in [
        *state.exc_repeated,
        *state.exc_skipped,
        *state.exc_invalid_offset,
        *state.exc_tz_notfound,
        *state.warn_potential_dst_bug,
        *state.warn_days_not_always_24h,
        *state.warn_potentially_stale_offset,
        *state.warn_naive_arithmetic,
    ] {
        exc.gc_traverse(visit, arg)?;
    }

    // Imported stuff
    state.strptime.gc_traverse(visit, arg)?;
    state.time_ns.gc_traverse(visit, arg)?;
    state.zoneinfo_type.gc_traverse(visit, arg)?;
    state.get_pydantic_schema.gc_traverse(visit, arg)?;
    Ok(())
}

#[cold]
unsafe extern "C" fn module_clear(mod_ptr: *mut PyObject) -> c_int {
    unsafe {
        // SAFETY: We're passed a valid PyModule pointer
        PyModule::from_ptr_unchecked(mod_ptr)
            .state()
            // SAFETY: `module_exec` initialized the state immediately to `None`
            // so it's safe to access--even though it hasn't been fully populated yet.
            .assume_init_mut()
    }
    // m_clear may be called multiple times by the cyclic GC (once per GC cycle that
    // finds this module in a reference cycle). Setting state to None is idempotent:
    // the first call drops Some(State) → auto-DECREFs all Owned<T> fields exactly once;
    // subsequent calls have None = None → no-op. Concurrent calls are impossible
    // since GC runs under the GIL (or stop-the-world in free-threaded builds).
    .take();
    0
}

#[cold]
unsafe extern "C" fn module_free(mod_ptr: *mut c_void) {
    #[cfg(debug_assertions)]
    eprintln!("[whenever] module_free called");
    // SAFETY: We're passed a valid PyModule pointer
    unsafe { module_clear(mod_ptr.cast()) };
}

// NOTE: The module state owns references to all the listed fields.
// The module __dict__ cannot be relied on because technically
// they can be deleted from it.
pub(crate) struct State {
    // classes
    pub(crate) date_type: Owned<HeapType<date::Date>>,
    pub(crate) time_type: Owned<HeapType<time::Time>>,
    pub(crate) time_delta_type: Owned<HeapType<time_delta::TimeDelta>>,
    pub(crate) plain_datetime_type: Owned<HeapType<plain_datetime::DateTime>>,
    pub(crate) instant_type: Owned<HeapType<instant::Instant>>,
    pub(crate) offset_datetime_type: Owned<HeapType<offset_datetime::OffsetDateTime>>,
    pub(crate) zoned_datetime_type: Owned<HeapType<zoned_datetime::ZonedDateTime>>,

    // Lazily imported from _shared
    pub(crate) yearmonth_type: OncePyObj,
    pub(crate) monthday_type: OncePyObj,
    pub(crate) isoweekdate_new: OncePyObj,
    pub(crate) weekday_enum_members: OncePyCell<[Owned<PyObj>; 7]>,

    // Lazily imported from _ideltas
    pub(crate) itemized_date_delta_type: OncePyObj,
    pub(crate) itemized_delta_type: OncePyObj,

    // exceptions
    pub(crate) exc_repeated: Owned<PyObj>,
    pub(crate) exc_skipped: Owned<PyObj>,
    pub(crate) exc_invalid_offset: Owned<PyObj>,
    pub(crate) exc_tz_notfound: Owned<PyObj>,

    // warnings
    pub(crate) warn_potential_dst_bug: Owned<PyObj>,
    pub(crate) warn_days_not_always_24h: Owned<PyObj>,
    pub(crate) warn_potentially_stale_offset: Owned<PyObj>,
    pub(crate) warn_naive_arithmetic: Owned<PyObj>,

    // unpickling functions
    pub(crate) unpickle_date: Owned<PyObj>,
    pub(crate) unpickle_time: Owned<PyObj>,
    pub(crate) unpickle_time_delta: Owned<PyObj>,
    pub(crate) unpickle_itemized_date_delta: OncePyObj,
    pub(crate) unpickle_itemized_delta: OncePyObj,
    pub(crate) unpickle_plain_datetime: Owned<PyObj>,
    pub(crate) unpickle_instant: Owned<PyObj>,
    pub(crate) unpickle_offset_datetime: Owned<PyObj>,
    pub(crate) unpickle_zoned_datetime: Owned<PyObj>,

    pub(crate) py_api: SwapPtr<PyDateTime_CAPI>,

    // imported stuff
    pub(crate) strptime: OncePyObj,
    pub(crate) time_ns: OncePyObj,
    pub(crate) zoneinfo_type: OncePyObj,
    pub(crate) get_pydantic_schema: OncePyObj,

    // strings
    pub(crate) str_years: Owned<PyObj>,
    pub(crate) str_months: Owned<PyObj>,
    pub(crate) str_weeks: Owned<PyObj>,
    pub(crate) str_days: Owned<PyObj>,
    pub(crate) str_hours: Owned<PyObj>,
    pub(crate) str_minutes: Owned<PyObj>,
    pub(crate) str_seconds: Owned<PyObj>,
    pub(crate) str_milliseconds: Owned<PyObj>,
    pub(crate) str_microseconds: Owned<PyObj>,
    pub(crate) str_nanoseconds: Owned<PyObj>,
    pub(crate) str_year: Owned<PyObj>,
    pub(crate) str_month: Owned<PyObj>,
    pub(crate) str_day: Owned<PyObj>,
    pub(crate) str_week: Owned<PyObj>,
    pub(crate) str_hour: Owned<PyObj>,
    pub(crate) str_minute: Owned<PyObj>,
    pub(crate) str_second: Owned<PyObj>,
    pub(crate) str_millisecond: Owned<PyObj>,
    pub(crate) str_microsecond: Owned<PyObj>,
    pub(crate) str_nanosecond: Owned<PyObj>,
    pub(crate) str_compatible: Owned<PyObj>,
    pub(crate) str_raise: Owned<PyObj>,
    pub(crate) str_earlier: Owned<PyObj>,
    pub(crate) str_later: Owned<PyObj>,
    pub(crate) str_tz: Owned<PyObj>,
    pub(crate) str_disambiguate: Owned<PyObj>,
    pub(crate) str_offset: Owned<PyObj>,
    pub(crate) str_total: Owned<PyObj>,
    pub(crate) str_unit: Owned<PyObj>,
    pub(crate) str_in_units: Owned<PyObj>,
    pub(crate) str_increment: Owned<PyObj>,
    pub(crate) str_mode: Owned<PyObj>,
    pub(crate) str_round_mode: Owned<PyObj>,
    pub(crate) str_round_increment: Owned<PyObj>,
    pub(crate) str_relative_to: Owned<PyObj>,
    pub(crate) round_mode_strs: round::ModeStrs,
    pub(crate) str_format: Owned<PyObj>,
    pub(crate) str_sep: Owned<PyObj>,
    pub(crate) str_space: Owned<PyObj>,
    pub(crate) str_t: Owned<PyObj>,
    pub(crate) str_auto: Owned<PyObj>,
    pub(crate) str_basic: Owned<PyObj>,
    pub(crate) str_always: Owned<PyObj>,
    pub(crate) str_never: Owned<PyObj>,
    pub(crate) str_offset_mismatch: Owned<PyObj>,
    pub(crate) str_keep_instant: Owned<PyObj>,
    pub(crate) str_keep_local: Owned<PyObj>,
    pub(crate) str_days_assumed_24h_ok: Owned<PyObj>,
    pub(crate) str_stale_offset_ok: Owned<PyObj>,
    pub(crate) str_naive_arithmetic_ok: Owned<PyObj>,
    pub(crate) str_week_mon: Owned<PyObj>,
    pub(crate) str_week_sun: Owned<PyObj>,

    pub(crate) time_patch: Patch,
    pub(crate) tz_store: TzStore,
}

impl State {
    pub(crate) fn py_api(&self) -> PyResult<&'static PyDateTime_CAPI> {
        if let Some(p) = self.py_api.load() {
            return Ok(unsafe { p.as_ref() });
        }
        self.py_api_slow()
    }

    #[cold]
    fn py_api_slow(&self) -> PyResult<&'static PyDateTime_CAPI> {
        unsafe { PyDateTime_IMPORT() };
        let api = unsafe { PyDateTimeAPI().as_ref() }.ok_or(PyErrMarker)?;
        // try_init is a no-op if another thread already initialized
        let _ = self
            .py_api
            .try_init(unsafe { std::ptr::NonNull::new_unchecked(PyDateTimeAPI()) });
        Ok(api)
    }
}
