use super::{date::Date, plain_datetime::PlainDateTime, round, scalar::*};
use crate::common::{
    fmt::{self, Sink, format_2_digits},
    parse::Scan,
};
use std::fmt::{Display, Formatter};

#[derive(Debug, Eq, PartialEq, Ord, PartialOrd, Copy, Clone)]
pub struct Time {
    pub(crate) hour: u8,
    pub(crate) minute: u8,
    pub(crate) second: u8,
    pub(crate) subsec: SubSecNanos,
}

impl Time {
    pub(crate) const MIN: Time = Time {
        hour: 0,
        minute: 0,
        second: 0,
        subsec: SubSecNanos::MIN,
    };

    pub(crate) const MAX: Self = Self {
        hour: 23,
        minute: 59,
        second: 59,
        subsec: SubSecNanos::MAX,
    };

    pub(crate) fn new(hour: u8, minute: u8, second: u8, subsec: SubSecNanos) -> Option<Self> {
        (hour < 24 && minute < 60 && second < 60).then_some(Self {
            hour,
            minute,
            second,
            subsec,
        })
    }

    pub(crate) const fn total_seconds(self) -> u32 {
        self.hour as u32 * 3600 + self.minute as u32 * 60 + self.second as u32
    }

    pub(crate) const fn from_sec_subsec(sec: u32, subsec: SubSecNanos) -> Self {
        Time {
            hour: (sec / 3600) as u8,
            minute: ((sec % 3600) / 60) as u8,
            second: (sec % 60) as u8,
            subsec,
        }
    }

    pub(crate) const fn total_nanos(self) -> u64 {
        self.subsec.get() as u64 + self.total_seconds() as u64 * NS_PER_SEC as u64
    }

    pub(crate) const fn on(self, date: Date) -> PlainDateTime {
        PlainDateTime { date, time: self }
    }

    pub(crate) fn from_total_nanos_unchecked(nanos: u64) -> Self {
        Time {
            hour: (nanos / NS_PER_HOUR) as u8,
            minute: ((nanos % NS_PER_HOUR) / NS_PER_MINUTE) as u8,
            second: ((nanos % NS_PER_MINUTE) / NS_PER_SEC as u64) as u8,
            subsec: SubSecNanos::from_remainder(nanos),
        }
    }

    pub(crate) fn read_iso_extended(s: &mut Scan) -> Option<Self> {
        let hour = s.digits00_23()?;
        let (minute, second, subsec) = match s.advance_on(b':') {
            Some(true) => {
                let minute = s.digits00_59()?;
                let (second, subsec) = match s.advance_on(b':') {
                    Some(true) => s.digits00_60_leap().zip(s.subsec())?,
                    _ => (0, SubSecNanos::MIN),
                };
                (minute, second, subsec)
            }
            _ => (0, 0, SubSecNanos::MIN),
        };
        Some(Time {
            hour,
            minute,
            second,
            subsec,
        })
    }

    pub(crate) fn read_iso_basic(s: &mut Scan) -> Option<Self> {
        let hour = s.digits00_23()?;
        let (minute, second, subsec) = match s.digits00_59() {
            Some(minute) => {
                let (second, subsec) = match s.digits00_60_leap() {
                    Some(second) => (second, s.subsec()?),
                    None => (0, SubSecNanos::MIN),
                };
                (minute, second, subsec)
            }
            None => (0, 0, SubSecNanos::MIN),
        };
        Some(Time {
            hour,
            minute,
            second,
            subsec,
        })
    }

    pub(crate) fn read_iso(s: &mut Scan) -> Option<Self> {
        match s.get(2) {
            Some(b':') => Self::read_iso_extended(s),
            _ => Self::read_iso_basic(s),
        }
    }

    pub(crate) fn parse_iso(s: &[u8]) -> Option<Self> {
        Scan::new(s).parse_all(Self::read_iso)
    }

    pub(crate) fn iso_format(self, unit: fmt::Precision, basic: bool) -> IsoFormat {
        let (subsec_str, subsec_len) = self.subsec.iso_format();
        IsoFormat {
            time: self,
            basic,
            subsec_str,
            subsec_len,
            unit,
        }
    }

    /// Round the time and return whether it wrapped to the next day.
    pub(crate) fn round(self, increment: u64, mode: round::Mode) -> (Self, u64) {
        debug_assert!(NS_PER_DAY.is_multiple_of(increment));
        let total_nanos = self.total_nanos();
        let quotient = total_nanos / increment;
        let remainder = total_nanos % increment;
        let threshold = match mode {
            round::Mode::HalfEven => 1.max(increment / 2 + quotient.is_multiple_of(2) as u64),
            round::Mode::Ceil | round::Mode::Expand => 1,
            round::Mode::Floor | round::Mode::Trunc => increment + 1,
            round::Mode::HalfFloor | round::Mode::HalfTrunc => increment / 2 + 1,
            round::Mode::HalfCeil | round::Mode::HalfExpand => 1.max(increment / 2),
        };
        let ns_since_midnight = (quotient + (remainder >= threshold) as u64) * increment;
        (
            Self::from_total_nanos_unchecked(ns_since_midnight % NS_PER_DAY),
            ns_since_midnight / NS_PER_DAY,
        )
    }

    pub(crate) fn start_of(self, unit: TimeBoundaryUnit) -> Self {
        match unit {
            TimeBoundaryUnit::Hour => Time {
                hour: self.hour,
                ..Time::MIN
            },
            TimeBoundaryUnit::Minute => Time {
                second: 0,
                subsec: SubSecNanos::MIN,
                ..self
            },
            TimeBoundaryUnit::Second => Time {
                subsec: SubSecNanos::MIN,
                ..self
            },
        }
    }

    pub(crate) fn end_of(self, unit: TimeBoundaryUnit) -> Self {
        match unit {
            TimeBoundaryUnit::Hour => Time {
                hour: self.hour,
                ..Time::MAX
            },
            TimeBoundaryUnit::Minute => Time {
                second: 59,
                subsec: SubSecNanos::MAX,
                ..self
            },
            TimeBoundaryUnit::Second => Time {
                subsec: SubSecNanos::MAX,
                ..self
            },
        }
    }

    pub(crate) fn next_start_of(self, unit: TimeBoundaryUnit) -> (Self, bool) {
        match unit {
            TimeBoundaryUnit::Hour => (
                Time {
                    hour: (self.hour + 1) % 24,
                    ..Time::MIN
                },
                self.hour == 23,
            ),
            TimeBoundaryUnit::Minute => (
                Time {
                    hour: (self.hour + (self.minute == 59) as u8) % 24,
                    minute: (self.minute + 1) % 60,
                    ..Time::MIN
                },
                self.minute == 59 && self.hour == 23,
            ),
            TimeBoundaryUnit::Second => (
                Time {
                    hour: (self.hour + (self.minute == 59 && self.second == 59) as u8) % 24,
                    minute: (self.minute + (self.second == 59) as u8) % 60,
                    second: (self.second + 1) % 60,
                    ..Time::MIN
                },
                self.second == 59 && self.minute == 59 && self.hour == 23,
            ),
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) enum TimeBoundaryUnit {
    Hour,
    Minute,
    Second,
}

impl TimeBoundaryUnit {
    pub(crate) fn in_secs(self) -> i32 {
        match self {
            TimeBoundaryUnit::Hour => 3600,
            TimeBoundaryUnit::Minute => 60,
            TimeBoundaryUnit::Second => 1,
        }
    }
}

#[derive(Debug, Clone, Copy)]
pub(crate) struct IsoFormat {
    time: Time,
    basic: bool,
    unit: fmt::Precision,
    subsec_str: [u8; 10],
    subsec_len: usize,
}

impl fmt::Chunk for IsoFormat {
    fn len(&self) -> usize {
        (match self.unit {
            fmt::Precision::Hour => 2,
            fmt::Precision::Minute => 4,
            fmt::Precision::Second => 6,
            fmt::Precision::Millisecond => 10,
            fmt::Precision::Microsecond => 13,
            fmt::Precision::Nanosecond => 16,
            fmt::Precision::Auto => 6 + self.subsec_len,
        }) + if self.basic || self.unit == fmt::Precision::Hour {
            0
        } else if self.unit == fmt::Precision::Minute {
            1
        } else {
            2
        }
    }

    fn write(&self, buf: &mut impl Sink) {
        let &IsoFormat {
            time:
                Time {
                    hour,
                    minute,
                    second,
                    ..
                },
            basic,
            unit,
            subsec_str,
            subsec_len,
        } = self;
        buf.write(format_2_digits(hour).as_ref());
        if unit == fmt::Precision::Hour {
            return;
        }
        if !basic {
            buf.write_byte(b':');
        }
        buf.write(format_2_digits(minute).as_ref());
        if unit == fmt::Precision::Minute {
            return;
        }
        if !basic {
            buf.write_byte(b':');
        }
        buf.write(format_2_digits(second).as_ref());
        if unit == fmt::Precision::Second {
            return;
        }
        let len_to_write = match unit {
            fmt::Precision::Auto => subsec_len,
            fmt::Precision::Nanosecond => 10,
            fmt::Precision::Microsecond => 7,
            fmt::Precision::Millisecond => 4,
            _ => unreachable!(),
        };
        buf.write(&subsec_str[..len_to_write]);
    }
}

impl Display for Time {
    fn fmt(&self, f: &mut Formatter<'_>) -> std::fmt::Result {
        write!(
            f,
            "{:02}:{:02}:{:02}{}",
            self.hour, self.minute, self.second, self.subsec
        )
    }
}
