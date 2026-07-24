use super::{
    plain_datetime::PlainDateTime,
    scalar::{EpochSecs, Offset, SubSecNanos},
    time_delta::TimeDelta,
};

#[derive(Debug, Eq, PartialEq, Ord, PartialOrd, Copy, Clone)]
pub(crate) struct Instant {
    pub(crate) epoch: EpochSecs,
    pub(crate) subsec: SubSecNanos,
}

impl Instant {
    pub(crate) fn to_utc_plain(self) -> PlainDateTime {
        self.epoch.datetime(self.subsec)
    }

    pub(crate) fn diff(self, other: Self) -> TimeDelta {
        TimeDelta::from_nanos_unchecked(self.timestamp_nanos() - other.timestamp_nanos())
    }

    pub(crate) fn timestamp_millis(self) -> i64 {
        self.epoch.get() * 1_000 + self.subsec.get() as i64 / 1_000_000
    }

    pub(crate) fn timestamp_nanos(self) -> i128 {
        self.epoch.get() as i128 * 1_000_000_000 + self.subsec.get() as i128
    }

    pub(crate) fn from_timestamp(timestamp: i64) -> Option<Self> {
        Some(Self {
            epoch: EpochSecs::new(timestamp)?,
            subsec: SubSecNanos::MIN,
        })
    }

    pub(crate) fn from_timestamp_f64(timestamp: f64) -> Option<Self> {
        (EpochSecs::MIN.get() as f64..=EpochSecs::MAX.get() as f64)
            .contains(&timestamp)
            .then(|| Self {
                epoch: EpochSecs::new_unchecked(timestamp.floor() as i64),
                subsec: SubSecNanos::from_fract(timestamp),
            })
    }

    pub(crate) fn from_timestamp_millis(millis: i64) -> Option<Self> {
        Some(Self {
            epoch: EpochSecs::new(millis.div_euclid(1_000))?,
            subsec: SubSecNanos::new_unchecked(millis.rem_euclid(1_000) as i32 * 1_000_000),
        })
    }

    pub(crate) fn from_timestamp_nanos(timestamp: i128) -> Option<Self> {
        i64::try_from(timestamp.div_euclid(1_000_000_000))
            .ok()
            .and_then(EpochSecs::new)
            .map(|epoch| Self {
                epoch,
                subsec: SubSecNanos::from_remainder(timestamp),
            })
    }

    pub(crate) fn shift(self, delta: TimeDelta) -> Option<Self> {
        let (extra_sec, subsec) = self.subsec.add(delta.subsec);
        Some(Self {
            epoch: self.epoch.shift(delta.secs)?.shift(extra_sec)?,
            subsec,
        })
    }

    pub(crate) fn shift_by_offset(self, offset: Offset) -> Option<Self> {
        Some(Self {
            epoch: self.epoch.shift_by_offset(offset)?,
            subsec: self.subsec,
        })
    }

    pub(crate) fn to_delta(self) -> TimeDelta {
        TimeDelta {
            secs: self.epoch.to_delta(),
            subsec: self.subsec,
        }
    }
}
