use crate::{domain::instant::Instant, py::*, pymodule::State};

pub(crate) fn extract_instant(obj: PyObj, state: &State) -> Option<Instant> {
    if let Some(i) = obj.extract(*state.instant_type) {
        Some(i)
    } else if let Some(dt) = obj.extract(*state.offset_datetime_type) {
        Some(dt.to_instant())
    } else {
        obj.extract_ref(*state.zoned_datetime_type)
            .map(|dt| dt.to_instant())
    }
}

pub(crate) fn parse_instant_arg(fname: &str, obj: PyObj, state: &State) -> PyResult<Instant> {
    extract_instant(obj, state).ok_or_else_raise(exc_type_error(), || {
        format!("{fname}() argument must be an OffsetDateTime, Instant, or ZonedDateTime")
    })
}

#[inline(always)]
pub(crate) fn parse_timestamp(obj: PyObj) -> PyResult<Instant> {
    if let Some(i) = obj.cast_allow_subclass::<PyInt>() {
        Instant::from_timestamp(i.to_i64()?)
    } else if let Some(f) = obj.cast_allow_subclass::<PyFloat>() {
        Instant::from_timestamp_f64(f.to_f64()?)
    } else {
        raise_type_err("timestamp must be an integer or float")?
    }
    .ok_or_range_err()
}

#[inline(always)]
pub(crate) fn parse_timestamp_millis(obj: PyObj) -> PyResult<Instant> {
    Instant::from_timestamp_millis(obj.expect_int("timestamp")?.to_i64()?).ok_or_range_err()
}

#[inline(always)]
pub(crate) fn parse_timestamp_nanos(obj: PyObj) -> PyResult<Instant> {
    Instant::from_timestamp_nanos(obj.expect_int("timestamp")?.to_i128()?).ok_or_range_err()
}
