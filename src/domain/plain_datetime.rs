use super::{
    date::{BoundaryUnit as DateBoundaryUnit, Date},
    instant::Instant,
    scalar::{DeltaDays, DeltaMonths, Month, OffsetDelta, S_PER_DAY, Year},
    time::{BoundUnit as TimeBoundaryUnit, Time},
    time_delta::TimeDelta,
};
use crate::common::parse::Scan;

#[derive(Debug, Eq, PartialEq, Ord, PartialOrd, Copy, Clone)]
pub struct PlainDateTime {
    pub(crate) date: Date,
    pub(crate) time: Time,
}

impl PlainDateTime {
    pub(crate) const MIN: Self = Self {
        date: Date {
            year: Year::MIN,
            month: Month::January,
            day: 1,
        },
        time: Time::MIN,
    };

    pub(crate) const MAX: Self = Self {
        date: Date {
            year: Year::MAX,
            month: Month::December,
            day: 31,
        },
        time: Time::MAX,
    };

    pub(crate) fn assume_utc(self) -> Instant {
        Instant {
            epoch: self.date.epoch_at(self.time),
            subsec: self.time.subsec,
        }
    }

    pub(crate) fn local_epoch(self) -> super::scalar::EpochSecs {
        self.date.epoch_at(self.time)
    }

    pub(crate) fn diff(self, other: Self) -> TimeDelta {
        self.assume_utc().diff(other.assume_utc())
    }

    pub(crate) fn with_date(self, date: Date) -> Self {
        Self {
            date,
            time: self.time,
        }
    }

    pub(crate) fn shift_date(self, months: DeltaMonths, days: DeltaDays) -> Option<Self> {
        let Self { date, time } = self;
        date.shift(months, days).map(|date| Self { date, time })
    }

    pub(crate) fn shift(self, delta: TimeDelta) -> Option<Self> {
        self.assume_utc().shift(delta).map(Instant::to_utc_plain)
    }

    pub(crate) fn shift_by_offset(self, offset: OffsetDelta) -> Option<Self> {
        let Self { date, time } = self;
        let seconds = time.total_seconds() as i32 + offset.get();
        Some(Self {
            date: match seconds.div_euclid(S_PER_DAY) {
                0 => date,
                1 => date.tomorrow()?,
                -1 => date.yesterday()?,
                2 => date.tomorrow()?.tomorrow()?,
                -2 => date.yesterday()?.yesterday()?,
                _ => unreachable!(),
            },
            time: Time::from_sec_subsec(seconds.rem_euclid(S_PER_DAY) as u32, time.subsec),
        })
    }

    pub(crate) fn start_of_unit(self, unit: BoundaryUnit) -> Option<PlainDateTime> {
        let (date, time) = match unit {
            BoundaryUnit::Date(unit) => (self.date.start_of(unit)?, Time::MIN),
            BoundaryUnit::Time(unit) => (self.date, self.time.start_of(unit)),
            BoundaryUnit::Day => (self.date, Time::MIN),
        };
        Some(PlainDateTime { date, time })
    }

    pub(crate) fn end_of_unit(self, unit: BoundaryUnit) -> Option<PlainDateTime> {
        let (date, time) = match unit {
            BoundaryUnit::Date(unit) => (self.date.end_of(unit)?, Time::MAX),
            BoundaryUnit::Time(unit) => (self.date, self.time.end_of(unit)),
            BoundaryUnit::Day => (self.date, Time::MAX),
        };
        Some(PlainDateTime { date, time })
    }

    pub(crate) fn next_start_of_unit(self, unit: BoundaryUnit) -> Option<PlainDateTime> {
        let (date, time) = match unit {
            BoundaryUnit::Date(unit) => (self.date.next_start_of(unit)?, Time::MIN),
            BoundaryUnit::Time(unit) => {
                let (time, overflow) = self.time.next_start_of(unit);
                (
                    if overflow {
                        self.date.tomorrow()?
                    } else {
                        self.date
                    },
                    time,
                )
            }
            BoundaryUnit::Day => (self.date.tomorrow()?, Time::MIN),
        };
        Some(PlainDateTime { date, time })
    }

    pub(crate) fn read_iso(s: &mut Scan) -> Option<Self> {
        if s.len() < 11 {
            return None;
        }
        let date = if is_datetime_sep(s[10]) {
            Date::parse_iso_extended(s.take_unchecked(10).try_into().unwrap())
        } else if is_datetime_sep(s[8]) {
            Date::parse_iso_basic(s.take_unchecked(8).try_into().unwrap())
        } else {
            return None;
        }?;
        let time = Time::read_iso(s.skip(1))?;
        Some(PlainDateTime { date, time })
    }

    pub fn parse(s: &[u8]) -> Option<Self> {
        Scan::new(s).parse_all(Self::read_iso)
    }
}

#[derive(Debug, Eq, PartialEq, Copy, Clone)]
pub(crate) enum BoundaryUnit {
    Date(DateBoundaryUnit),
    Time(TimeBoundaryUnit),
    Day,
}

impl std::fmt::Display for PlainDateTime {
    fn fmt(&self, f: &mut std::fmt::Formatter) -> std::fmt::Result {
        write!(f, "{}T{}", self.date, self.time)
    }
}

fn is_datetime_sep(c: u8) -> bool {
    c == b'T' || c == b' ' || c == b't'
}
