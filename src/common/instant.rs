use crate::{domain::instant::Instant, py::*, pymodule::State};

#[derive(Clone, Copy)]
pub(crate) enum TimestampUnit {
    Second,
    Millisecond,
    Microsecond,
    Nanosecond,
}

impl TimestampUnit {
    pub(crate) fn from_py(obj: PyObj, state: &State) -> PyResult<Self> {
        find_interned(
            obj,
            &[
                (*state.strs.second, Self::Second),
                (*state.strs.millisecond, Self::Millisecond),
                (*state.strs.microsecond, Self::Microsecond),
                (*state.strs.nanosecond, Self::Nanosecond),
            ],
        )
        .ok_or_value_err("invalid timestamp unit")
    }

    pub(crate) fn timestamp(self, instant: Instant) -> i128 {
        let units_per_second = match self {
            Self::Second => 1,
            Self::Millisecond => 1_000,
            Self::Microsecond => 1_000_000,
            Self::Nanosecond => 1_000_000_000,
        };
        instant.epoch.get() as i128 * units_per_second
            + instant.subsec.get() as i128 / (1_000_000_000 / units_per_second)
    }

    pub(crate) fn parse(self, obj: PyObj) -> PyResult<Instant> {
        match self {
            Self::Second => parse_timestamp(obj),
            Self::Millisecond | Self::Microsecond | Self::Nanosecond => {
                let value = obj.expect_int("timestamp")?.to_i128()?;
                let nanos_per_unit = match self {
                    Self::Millisecond => 1_000_000,
                    Self::Microsecond => 1_000,
                    Self::Nanosecond => 1,
                    Self::Second => unreachable!(),
                };
                value
                    .checked_mul(nanos_per_unit)
                    .and_then(Instant::from_timestamp_nanos)
                    .ok_or_range_err()
            }
        }
    }
}

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

pub(crate) fn parse_timestamp_millis(obj: PyObj) -> PyResult<Instant> {
    let value = obj
        .cast_allow_subclass::<PyInt>()
        .ok_or_type_err("timestamp conversion requires an integer")?;
    Instant::from_timestamp_millis(value.to_i64()?).ok_or_range_err()
}

pub(crate) fn parse_timestamp_nanos(obj: PyObj) -> PyResult<Instant> {
    let value = obj
        .cast_allow_subclass::<PyInt>()
        .ok_or_type_err("timestamp conversion requires an integer")?;
    Instant::from_timestamp_nanos(value.to_i128()?).ok_or_range_err()
}
