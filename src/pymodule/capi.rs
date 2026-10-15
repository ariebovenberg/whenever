//! The C API: `whenever.C_API_v1`, a capsule holding a table of function
//! pointers through which other extensions convert whenever values to and
//! from plain records without Python calls.
//!
//! `include/whenever.h` is the public declaration. The types here mirror it
//! field for field and the two change together: within v1 the table only
//! ever grows at the end, and the records never change.
#![allow(non_camel_case_types)]

use crate::{
    classes::{
        date::Date,
        instant::Instant,
        offset_datetime::{OffsetDateTime, OffsetMismatch},
        plain_datetime::PlainDateTime,
        time::Time,
        time_delta::TimeDelta,
        zoned_datetime::{ZonedDateTime, resolve_zoned_local},
    },
    common::disambiguation::Disambiguation,
    domain::{
        scalar::{EpochSecs, Month, Offset, SubSecNanos, Year},
        units::NS_PER_SECOND,
    },
    py::*,
};
use core::ffi::{CStr, c_char, c_int};
use pyo3_ffi::*;

pub(crate) const CAPSULE_NAME: &CStr = c"whenever.C_API_v1";

#[repr(C)]
pub struct Whenever_Date {
    pub year: u16,
    pub month: u8,
    pub day: u8,
}

#[repr(C)]
pub struct Whenever_Time {
    pub hour: u8,
    pub minute: u8,
    pub second: u8,
    pub nanosecond: u32,
}

#[repr(C)]
pub struct Whenever_PlainDateTime {
    pub date: Whenever_Date,
    pub time: Whenever_Time,
}

#[repr(C)]
pub struct Whenever_Instant {
    pub epoch_second: i64,
    pub nanosecond: u32,
}

#[repr(C)]
pub struct Whenever_OffsetDateTime {
    pub local: Whenever_PlainDateTime,
    pub offset_second: i32,
}

#[repr(C)]
pub struct Whenever_ZonedDateTime {
    pub odt: Whenever_OffsetDateTime,
    /// A view, not NUL-terminated: into the object on extraction (null for
    /// a system time zone without a time zone ID), into the caller's memory
    /// for the duration of a constructor call.
    pub tz_id: *const c_char,
    pub tz_id_len: u8,
}

#[repr(C)]
pub struct Whenever_TimeDelta {
    pub second: i64,
    pub nanosecond: u32,
}

/// 0: written. 1: not exactly this type, nothing written, no exception.
type Extract<R> = unsafe extern "C" fn(*const Whenever_CAPI, *mut PyObject, *mut R) -> c_int;
/// A new reference, or null with an exception set.
type New<R> = unsafe extern "C" fn(*const Whenever_CAPI, *const R) -> *mut PyObject;

#[repr(C)]
pub struct Whenever_CAPI {
    pub magic: *const c_char,
    pub struct_size: i32,
    pub version_minor: i32,

    pub date_type: *mut PyTypeObject,
    pub time_type: *mut PyTypeObject,
    pub plain_datetime_type: *mut PyTypeObject,
    pub instant_type: *mut PyTypeObject,
    pub offset_datetime_type: *mut PyTypeObject,
    pub zoned_datetime_type: *mut PyTypeObject,
    pub time_delta_type: *mut PyTypeObject,

    pub date_extract: Extract<Whenever_Date>,
    pub time_extract: Extract<Whenever_Time>,
    pub plain_datetime_extract: Extract<Whenever_PlainDateTime>,
    pub instant_extract: Extract<Whenever_Instant>,
    pub offset_datetime_extract: Extract<Whenever_OffsetDateTime>,
    pub zoned_datetime_extract: Extract<Whenever_ZonedDateTime>,
    pub time_delta_extract: Extract<Whenever_TimeDelta>,

    pub date_new: New<Whenever_Date>,
    pub time_new: New<Whenever_Time>,
    pub plain_datetime_new: New<Whenever_PlainDateTime>,
    pub instant_new: New<Whenever_Instant>,
    pub offset_datetime_new: New<Whenever_OffsetDateTime>,
    pub time_delta_new: New<Whenever_TimeDelta>,
    pub zoned_datetime_from_instant: unsafe extern "C" fn(
        *const Whenever_CAPI,
        *const Whenever_Instant,
        *const c_char,
        u8,
    ) -> *mut PyObject,
    pub zoned_datetime_new: unsafe extern "C" fn(
        *const Whenever_CAPI,
        *const Whenever_ZonedDateTime,
        c_int,
        c_int,
    ) -> *mut PyObject,
}

// The table holds borrowed type pointers that the module state owns, and
// function pointers. Nothing in it is mutated after construction.
unsafe impl Sync for Whenever_CAPI {}
unsafe impl Send for Whenever_CAPI {}

#[allow(clippy::too_many_arguments)]
pub(crate) fn table(
    date: PyClass<Date>,
    time: PyClass<Time>,
    plain_datetime: PyClass<PlainDateTime>,
    instant: PyClass<Instant>,
    offset_datetime: PyClass<OffsetDateTime>,
    zoned_datetime: PyClass<ZonedDateTime>,
    time_delta: PyClass<TimeDelta>,
) -> Box<Whenever_CAPI> {
    Box::new(Whenever_CAPI {
        magic: CAPSULE_NAME.as_ptr(),
        struct_size: size_of::<Whenever_CAPI>() as _,
        version_minor: 0,
        date_type: date.as_ptr().cast(),
        time_type: time.as_ptr().cast(),
        plain_datetime_type: plain_datetime.as_ptr().cast(),
        instant_type: instant.as_ptr().cast(),
        offset_datetime_type: offset_datetime.as_ptr().cast(),
        zoned_datetime_type: zoned_datetime.as_ptr().cast(),
        time_delta_type: time_delta.as_ptr().cast(),
        date_extract,
        time_extract,
        plain_datetime_extract,
        instant_extract,
        offset_datetime_extract,
        zoned_datetime_extract,
        time_delta_extract,
        date_new,
        time_new,
        plain_datetime_new,
        instant_new,
        offset_datetime_new,
        time_delta_new,
        zoned_datetime_from_instant,
        zoned_datetime_new,
    })
}

/// The capsule that publishes `table`, which must outlive it.
pub(crate) fn capsule(table: &Whenever_CAPI) -> PyReturn {
    unsafe {
        PyCapsule_New(
            (table as *const Whenever_CAPI).cast_mut().cast(),
            CAPSULE_NAME.as_ptr(),
            None,
        )
    }
    .own()
}

// --- records <-> domain values -------------------------------------------

fn date_record(d: Date) -> Whenever_Date {
    Whenever_Date {
        year: d.year.get(),
        month: d.month.get(),
        day: d.day,
    }
}

fn date_value(r: &Whenever_Date) -> Option<Date> {
    Date::new(Year::new(r.year)?, Month::new(r.month)?, r.day)
}

fn time_record(t: Time) -> Whenever_Time {
    Whenever_Time {
        hour: t.hour,
        minute: t.minute,
        second: t.second,
        nanosecond: t.subsec.as_u32(),
    }
}

fn subsec(nanosecond: u32) -> Option<SubSecNanos> {
    SubSecNanos::new(i32::try_from(nanosecond).ok()?)
}

fn time_value(r: &Whenever_Time) -> Option<Time> {
    Time::new(r.hour, r.minute, r.second, subsec(r.nanosecond)?)
}

fn plain_record(p: PlainDateTime) -> Whenever_PlainDateTime {
    Whenever_PlainDateTime {
        date: date_record(p.date),
        time: time_record(p.time),
    }
}

fn plain_value(r: &Whenever_PlainDateTime) -> Option<PlainDateTime> {
    Some(PlainDateTime {
        date: date_value(&r.date)?,
        time: time_value(&r.time)?,
    })
}

fn instant_record(i: Instant) -> Whenever_Instant {
    Whenever_Instant {
        epoch_second: i.epoch.get(),
        nanosecond: i.subsec.as_u32(),
    }
}

fn instant_value(r: &Whenever_Instant) -> Option<Instant> {
    Some(Instant {
        epoch: EpochSecs::new(r.epoch_second)?,
        subsec: subsec(r.nanosecond)?,
    })
}

fn offset_record(o: OffsetDateTime) -> Whenever_OffsetDateTime {
    Whenever_OffsetDateTime {
        local: plain_record(o.to_plain()),
        offset_second: o.offset.get(),
    }
}

fn offset_value(r: &Whenever_OffsetDateTime) -> Option<OffsetDateTime> {
    plain_value(&r.local)?.assume_offset(Offset::new(r.offset_second)?)
}

fn zoned_record(z: &ZonedDateTime) -> Whenever_ZonedDateTime {
    let (tz_id, tz_id_len) = match z.tz.key.as_deref() {
        // The store rejects IDs of 100 bytes or more, so the length fits.
        Some(key) => (key.as_ptr().cast(), key.len() as u8),
        None => (core::ptr::null(), 0),
    };
    Whenever_ZonedDateTime {
        odt: offset_record(z.to_fixed_offset()),
        tz_id,
        tz_id_len,
    }
}

fn time_delta_record(d: TimeDelta) -> Whenever_TimeDelta {
    Whenever_TimeDelta {
        second: d.secs.get(),
        nanosecond: d.subsec.as_u32(),
    }
}

fn time_delta_value(r: &Whenever_TimeDelta) -> Option<TimeDelta> {
    let subsec = subsec(r.nanosecond)?;
    TimeDelta::from_nanos(r.second as i128 * NS_PER_SECOND as i128 + subsec.get() as i128)
}

// --- extraction --------------------------------------------------------------
//
// Extractors make no CPython call, so a consumer may run them without an
// attached thread state: the type check reads `ob_type` as a field, and the
// payload is immutable for the object's lifetime.

/// The payload of `obj` if its type is exactly `ty`.
unsafe fn payload<'a, T: PyPayload>(obj: *mut PyObject, ty: *mut PyTypeObject) -> Option<&'a T> {
    // SAFETY: the caller passes a valid object; the type check proves its layout.
    (unsafe { Py_TYPE(obj) } == ty).then(|| unsafe { &(*obj.cast::<PyObjectLayout<T>>()).data })
}

macro_rules! extractor {
    ($name:ident, $typ:ty, $slot:ident, $record:ty, $convert:expr) => {
        unsafe extern "C" fn $name(
            api: *const Whenever_CAPI,
            obj: *mut PyObject,
            out: *mut $record,
        ) -> c_int {
            // SAFETY: the consumer passes the table the capsule handed out.
            match unsafe { payload::<$typ>(obj, (*api).$slot) } {
                Some(value) => {
                    // SAFETY: `out` is the consumer's record to fill.
                    unsafe { out.write($convert(value)) };
                    0
                }
                None => 1,
            }
        }
    };
}

extractor!(date_extract, Date, date_type, Whenever_Date, |d: &Date| {
    date_record(*d)
});
extractor!(time_extract, Time, time_type, Whenever_Time, |t: &Time| {
    time_record(*t)
});
extractor!(
    plain_datetime_extract,
    PlainDateTime,
    plain_datetime_type,
    Whenever_PlainDateTime,
    |p: &PlainDateTime| plain_record(*p)
);
extractor!(
    instant_extract,
    Instant,
    instant_type,
    Whenever_Instant,
    |i: &Instant| instant_record(*i)
);
extractor!(
    offset_datetime_extract,
    OffsetDateTime,
    offset_datetime_type,
    Whenever_OffsetDateTime,
    |o: &OffsetDateTime| offset_record(*o)
);
extractor!(
    zoned_datetime_extract,
    ZonedDateTime,
    zoned_datetime_type,
    Whenever_ZonedDateTime,
    zoned_record
);
extractor!(
    time_delta_extract,
    TimeDelta,
    time_delta_type,
    Whenever_TimeDelta,
    |d: &TimeDelta| time_delta_record(*d)
);

// --- construction ------------------------------------------------------------
//
// Constructors run with an attached thread state, like any C API call that
// creates objects.

/// The class whose module state the zoned constructors need for the tz
/// store; `Date` is the first slot, any would do. The other constructors
/// allocate from their type slot alone.
///
/// # Safety
/// `api` is the table the capsule handed out, and its module is alive.
unsafe fn date_class(api: *const Whenever_CAPI) -> PyClass<Date> {
    unsafe { PyType::from_ptr_unchecked((*api).date_type.cast()).assume_class::<Date>() }
}

macro_rules! constructor {
    ($name:ident, $slot:ident, $typ:ty, $record:ty, $convert:expr, $msg:literal) => {
        unsafe extern "C" fn $name(
            api: *const Whenever_CAPI,
            rec: *const $record,
        ) -> *mut PyObject {
            catch_panic!({
                // SAFETY: `api` is the table the capsule handed out, whose type
                // slots are alive; `rec` is the consumer's record.
                let cls = unsafe {
                    PyType::from_ptr_unchecked((*api).$slot.cast()).assume_class::<$typ>()
                };
                $convert(unsafe { &*rec })
                    .ok_or_value_err($msg)
                    .and_then(|v: $typ| v.to_obj(cls))
                    .to_py_owned_ptr()
            })
        }
    };
}

constructor!(
    date_new,
    date_type,
    Date,
    Whenever_Date,
    date_value,
    "invalid date"
);
constructor!(
    time_new,
    time_type,
    Time,
    Whenever_Time,
    time_value,
    "invalid time"
);
constructor!(
    plain_datetime_new,
    plain_datetime_type,
    PlainDateTime,
    Whenever_PlainDateTime,
    plain_value,
    "invalid date or time"
);
constructor!(
    instant_new,
    instant_type,
    Instant,
    Whenever_Instant,
    instant_value,
    "instant out of range"
);
constructor!(
    offset_datetime_new,
    offset_datetime_type,
    OffsetDateTime,
    Whenever_OffsetDateTime,
    offset_value,
    "invalid date, time, or offset"
);
constructor!(
    time_delta_new,
    time_delta_type,
    TimeDelta,
    Whenever_TimeDelta,
    time_delta_value,
    "TimeDelta out of range"
);

/// # Safety
/// `tz_id` points at `len` readable bytes, or is null.
unsafe fn tz_id_str<'a>(tz_id: *const c_char, len: u8) -> PyResult<&'a str> {
    if tz_id.is_null() {
        return raise_value_err("tz_id is required");
    }
    // SAFETY: as documented.
    str::from_utf8(unsafe { core::slice::from_raw_parts(tz_id.cast::<u8>(), len as usize) })
        .ok()
        .ok_or_value_err("invalid tz_id")
}

unsafe extern "C" fn zoned_datetime_from_instant(
    api: *const Whenever_CAPI,
    rec: *const Whenever_Instant,
    tz_id: *const c_char,
    tz_id_len: u8,
) -> *mut PyObject {
    catch_panic!({
        // SAFETY: as documented on `date_class` and `tz_id_str`.
        let cls = unsafe { date_class(api) };
        let state = cls.state();
        (|| {
            let instant =
                instant_value(unsafe { &*rec }).ok_or_value_err("instant out of range")?;
            let tz = state
                .tz_store
                .get(unsafe { tz_id_str(tz_id, tz_id_len) }?)?;
            instant.into_zoned_obj(tz, *state.zoned_datetime_type)
        })()
        .to_py_owned_ptr()
    })
}

fn offset_mismatch_policy(value: c_int) -> PyResult<OffsetMismatch> {
    match value {
        0 => Ok(OffsetMismatch::Raise),
        1 => Ok(OffsetMismatch::KeepInstant),
        2 => Ok(OffsetMismatch::KeepLocal),
        _ => raise_value_err(format!("invalid offset_mismatch: {value}")),
    }
}

fn disambiguation_policy(value: c_int) -> PyResult<Disambiguation> {
    match value {
        0 => Ok(Disambiguation::Compatible),
        1 => Ok(Disambiguation::Earlier),
        2 => Ok(Disambiguation::Later),
        3 => Ok(Disambiguation::Reject),
        _ => raise_value_err(format!("invalid disambiguation: {value}")),
    }
}

unsafe extern "C" fn zoned_datetime_new(
    api: *const Whenever_CAPI,
    rec: *const Whenever_ZonedDateTime,
    offset_mismatch: c_int,
    disambiguation: c_int,
) -> *mut PyObject {
    catch_panic!({
        // SAFETY: as documented on `date_class` and `tz_id_str`.
        let cls = unsafe { date_class(api) };
        let state = cls.state();
        let rec = unsafe { &*rec };
        (|| {
            let mismatch = offset_mismatch_policy(offset_mismatch)?;
            let dis = disambiguation_policy(disambiguation)?;
            let local = plain_value(&rec.odt.local).ok_or_value_err("invalid date or time")?;
            let offset =
                Offset::new(rec.odt.offset_second).ok_or_value_err("offset out of range")?;
            let tz = state
                .tz_store
                .get(unsafe { tz_id_str(rec.tz_id, rec.tz_id_len) }?)?;
            resolve_zoned_local(
                *state.zoned_datetime_type,
                local,
                tz,
                offset,
                true,
                false,
                Some(dis),
                mismatch,
            )
        })()
        .to_py_owned_ptr()
    })
}
