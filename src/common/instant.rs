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
