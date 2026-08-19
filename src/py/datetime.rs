//! Functionality for working with Python's datetime module.
use super::{base::*, exc::*, refs::*, typed::*};
use crate::domain::{
    plain_datetime::PlainDateTime,
    scalar::{DeltaSeconds, NS_PER_MICROSEC, Offset, S_PER_DAY, SubSecNanos},
    time_delta::TimeDelta,
};
use pyo3_ffi::*;

pub(crate) trait PyDateTimeApiExt {
    fn utc_timezone(&self) -> PyObj;
    fn new_datetime(&self, dt: PlainDateTime, tzinfo: Option<PyObj>)
    -> PyResult<Owned<PyDateTime>>;
    fn new_timedelta(&self, delta: TimeDelta) -> PyResult<Owned<PyTimeDelta>>;
    fn new_timezone(&self, offset: Offset) -> PyReturn;
}

impl PyDateTimeApiExt for PyDateTime_CAPI {
    fn utc_timezone(&self) -> PyObj {
        // SAFETY: TimeZone_UTC is a borrowed reference owned by the initialized datetime module.
        unsafe { PyObj::from_ptr_unchecked(self.TimeZone_UTC) }
    }

    fn new_datetime(
        &self,
        dt: PlainDateTime,
        tzinfo: Option<PyObj>,
    ) -> PyResult<Owned<PyDateTime>> {
        let date = dt.date;
        let time = dt.time;
        // SAFETY: the domain values are valid datetime components and DateTimeType is supplied
        // by the initialized CPython datetime C API.
        unsafe {
            (self.DateTime_FromDateAndTime)(
                date.year.get().into(),
                date.month.get().into(),
                date.day.into(),
                time.hour.into(),
                time.minute.into(),
                time.second.into(),
                (time.subsec.get() / 1_000) as _,
                tzinfo.map_or_else(|| Py_None(), |obj| obj.as_ptr()),
                self.DateTimeType,
            )
        }
        .own()
        // SAFETY: DateTime_FromDateAndTime returns a datetime instance.
        .map(|obj| unsafe { obj.cast_unchecked::<PyDateTime>() })
    }

    fn new_timedelta(&self, delta: TimeDelta) -> PyResult<Owned<PyTimeDelta>> {
        // SAFETY: values are normalized for CPython and DeltaType comes from the initialized API.
        unsafe {
            (self.Delta_FromDelta)(
                delta.secs.get().div_euclid(S_PER_DAY.into()) as _,
                delta.secs.get().rem_euclid(S_PER_DAY.into()) as _,
                (delta.subsec.get() / NS_PER_MICROSEC as i32) as _,
                0,
                self.DeltaType,
            )
        }
        .own()
        // SAFETY: Delta_FromDelta returns a timedelta instance.
        .map(|obj| unsafe { obj.cast_unchecked::<PyTimeDelta>() })
    }

    fn new_timezone(&self, offset: Offset) -> PyReturn {
        // SAFETY: every valid Offset fits within the TimeDelta range.
        let delta = self.new_timedelta(TimeDelta {
            secs: DeltaSeconds::new(offset.get().into()).unwrap(),
            subsec: SubSecNanos::MIN,
        })?;
        // SAFETY: delta is a valid timedelta and the null name requests CPython's default name.
        unsafe { (self.TimeZone_FromTimeZone)(delta.as_ptr(), std::ptr::null_mut()) }.own()
    }
}

#[derive(Debug, Clone, Copy)]
pub(crate) struct DateTag;

impl TypeTag for DateTag {
    fn check_exact(obj: PyObj) -> bool {
        unsafe {
            if PyDateTimeAPI().is_null() {
                PyDateTime_IMPORT();
            }
            PyDate_CheckExact(obj.as_ptr()) != 0
        }
    }

    fn check(obj: PyObj) -> bool {
        unsafe {
            if PyDateTimeAPI().is_null() {
                PyDateTime_IMPORT();
            }
            PyDate_Check(obj.as_ptr()) != 0
        }
    }
}

pub(crate) type PyDate = Typed<DateTag>;

impl Typed<DateTag> {
    pub fn year(&self) -> i32 {
        unsafe { PyDateTime_GET_YEAR(self.as_ptr()) }
    }

    pub fn month(&self) -> i32 {
        unsafe { PyDateTime_GET_MONTH(self.as_ptr()) }
    }

    pub fn day(&self) -> i32 {
        unsafe { PyDateTime_GET_DAY(self.as_ptr()) }
    }
}

#[derive(Debug, Clone, Copy)]
pub(crate) struct DateTimeTag;

impl TypeTag for DateTimeTag {
    fn check_exact(obj: PyObj) -> bool {
        unsafe {
            if PyDateTimeAPI().is_null() {
                PyDateTime_IMPORT();
            }
            PyDateTime_CheckExact(obj.as_ptr()) != 0
        }
    }

    fn check(obj: PyObj) -> bool {
        unsafe {
            if PyDateTimeAPI().is_null() {
                PyDateTime_IMPORT();
            }
            PyDateTime_Check(obj.as_ptr()) != 0
        }
    }
}

pub(crate) type PyDateTime = Typed<DateTimeTag>;

impl Typed<DateTimeTag> {
    #[allow(dead_code)]
    pub(crate) fn year(&self) -> i32 {
        unsafe { PyDateTime_GET_YEAR(self.as_ptr()) }
    }

    #[allow(dead_code)]
    pub(crate) fn month(&self) -> i32 {
        unsafe { PyDateTime_GET_MONTH(self.as_ptr()) }
    }

    #[allow(dead_code)]
    pub(crate) fn day(&self) -> i32 {
        unsafe { PyDateTime_GET_DAY(self.as_ptr()) }
    }

    pub(crate) fn hour(&self) -> i32 {
        unsafe { PyDateTime_DATE_GET_HOUR(self.as_ptr()) }
    }

    pub(crate) fn minute(&self) -> i32 {
        unsafe { PyDateTime_DATE_GET_MINUTE(self.as_ptr()) }
    }

    pub(crate) fn second(&self) -> i32 {
        unsafe { PyDateTime_DATE_GET_SECOND(self.as_ptr()) }
    }

    pub(crate) fn microsecond(&self) -> i32 {
        unsafe { PyDateTime_DATE_GET_MICROSECOND(self.as_ptr()) }
    }

    /// Get a borrowed reference to the tzinfo object. Only valid so
    /// long as the PyDateTime object itself is alive.
    pub(crate) fn tzinfo(&self) -> PyObj {
        // SAFETY: calling CPython API with valid arguments
        unsafe { PyObj::from_ptr_unchecked(PyDateTime_DATE_GET_TZINFO(self.as_ptr())) }
    }

    pub(crate) fn date(&self) -> PyDate {
        // SAFETY: Date has the same layout
        unsafe { PyDate::from_ptr_unchecked(self.as_ptr()) }
    }

    pub(crate) fn utcoffset(&self) -> PyReturn {
        self.getattr(c"utcoffset")?.call0()
    }
}

#[derive(Debug, Clone, Copy)]
pub(crate) struct TimeDeltaTag;

impl TypeTag for TimeDeltaTag {
    fn check_exact(obj: PyObj) -> bool {
        unsafe {
            if PyDateTimeAPI().is_null() {
                PyDateTime_IMPORT();
            }
            PyDelta_CheckExact(obj.as_ptr()) != 0
        }
    }

    fn check(obj: PyObj) -> bool {
        unsafe {
            if PyDateTimeAPI().is_null() {
                PyDateTime_IMPORT();
            }
            PyDelta_Check(obj.as_ptr()) != 0
        }
    }
}

pub(crate) type PyTimeDelta = Typed<TimeDeltaTag>;

impl Typed<TimeDeltaTag> {
    pub(crate) fn days_component(&self) -> i32 {
        unsafe { PyDateTime_DELTA_GET_DAYS(self.as_ptr()) }
    }

    pub(crate) fn seconds_component(&self) -> i32 {
        unsafe { PyDateTime_DELTA_GET_SECONDS(self.as_ptr()) }
    }

    pub(crate) fn microseconds_component(&self) -> i32 {
        unsafe { PyDateTime_DELTA_GET_MICROSECONDS(self.as_ptr()) }
    }

    pub(crate) fn whole_seconds(self) -> Option<DeltaSeconds> {
        DeltaSeconds::new(
            // SAFETY: timedelta.max days (in seconds) are safely within i64
            i64::from(self.days_component()) * 86400 + i64::from(self.seconds_component()),
        )
    }

    pub(crate) fn subsec(self) -> SubSecNanos {
        // SAFETY: microseconds are always less than 1_000_000
        SubSecNanos::new_unchecked(self.microseconds_component() * 1_000)
    }
}

#[derive(Debug, Clone, Copy)]
pub(crate) struct TimeTag;

impl TypeTag for TimeTag {
    fn check_exact(obj: PyObj) -> bool {
        unsafe {
            if PyDateTimeAPI().is_null() {
                PyDateTime_IMPORT();
            }
            PyTime_CheckExact(obj.as_ptr()) != 0
        }
    }

    fn check(obj: PyObj) -> bool {
        unsafe {
            if PyDateTimeAPI().is_null() {
                PyDateTime_IMPORT();
            }
            PyTime_Check(obj.as_ptr()) != 0
        }
    }
}

pub(crate) type PyTime = Typed<TimeTag>;

impl Typed<TimeTag> {
    pub(crate) fn hour(&self) -> i32 {
        unsafe { PyDateTime_TIME_GET_HOUR(self.as_ptr()) }
    }

    pub(crate) fn minute(&self) -> i32 {
        unsafe { PyDateTime_TIME_GET_MINUTE(self.as_ptr()) }
    }

    pub(crate) fn second(&self) -> i32 {
        unsafe { PyDateTime_TIME_GET_SECOND(self.as_ptr()) }
    }

    pub(crate) fn microsecond(&self) -> i32 {
        unsafe { PyDateTime_TIME_GET_MICROSECOND(self.as_ptr()) }
    }
}
