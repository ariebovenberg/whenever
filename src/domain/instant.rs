use super::{
    plain_datetime::PlainDateTime,
    round,
    scalar::{EpochSecs, Offset, SubSecNanos},
    time::Time,
    time_delta::TimeDelta,
    units::{NS_PER_MILLISECOND, NS_PER_SECOND, S_PER_DAY},
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

    /// Round to an increment counted from midnight UTC. A point on the
    /// timeline rounds as a positive number, also before 1970.
    pub(crate) fn round(self, increment_ns: u64, mode: round::Mode) -> Option<Self> {
        let secs = self.epoch.get();
        let time = Time::from_sec_subsec(secs.rem_euclid(S_PER_DAY.into()) as u32, self.subsec);
        let (rounded, next_day) = time.round(increment_ns, mode);
        Some(Self {
            epoch: EpochSecs::new(
                (secs.div_euclid(S_PER_DAY.into()) + next_day as i64) * i64::from(S_PER_DAY)
                    + i64::from(rounded.total_seconds()),
            )?,
            subsec: rounded.subsec,
        })
    }

    pub(crate) fn diff(self, other: Self) -> TimeDelta {
        TimeDelta::from_nanos_unchecked(self.timestamp_nanos() - other.timestamp_nanos())
    }

    pub(crate) fn timestamp_millis(self) -> i64 {
        self.epoch.get() * i64::from(NS_PER_SECOND / NS_PER_MILLISECOND)
            + self.subsec.get() as i64 / i64::from(NS_PER_MILLISECOND)
    }

    pub(crate) fn timestamp_nanos(self) -> i128 {
        self.epoch.get() as i128 * NS_PER_SECOND as i128 + self.subsec.get() as i128
    }

    pub(crate) fn from_timestamp(timestamp: i64) -> Option<Self> {
        Some(Self {
            epoch: EpochSecs::new(timestamp)?,
            subsec: SubSecNanos::MIN,
        })
    }

    pub(crate) fn from_timestamp_f64(timestamp: f64) -> Option<Self> {
        // The whole seconds bound the range, so the last second is included
        let secs = timestamp.floor();
        (EpochSecs::MIN.get() as f64..=EpochSecs::MAX.get() as f64)
            .contains(&secs)
            .then(|| Self {
                epoch: EpochSecs::new_unchecked(secs as i64),
                subsec: SubSecNanos::from_fract(timestamp),
            })
    }

    pub(crate) fn from_timestamp_nanos(timestamp: i128) -> Option<Self> {
        i64::try_from(timestamp.div_euclid(NS_PER_SECOND as i128))
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
}
