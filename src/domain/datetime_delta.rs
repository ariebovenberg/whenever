use super::{
    date_delta::{DateDelta, InitError, format_components, parse_component, parse_prefix},
    scalar::{DeltaDays, DeltaMonths},
    time_delta::{TimeDelta, fmt_components_abs, parse_all_components},
};
use crate::common::math::CalendarUnit;
use std::{fmt, ops::Neg};

#[derive(Debug, Eq, PartialEq, Copy, Clone)]
pub(crate) struct DateTimeDelta {
    // invariant: these never have opposite signs
    pub(crate) date: DateDelta,
    pub(crate) time: TimeDelta,
}

impl DateTimeDelta {
    pub(crate) const ZERO: Self = Self {
        date: DateDelta::ZERO,
        time: TimeDelta::ZERO,
    };

    pub(crate) fn new(date: DateDelta, time: TimeDelta) -> Option<Self> {
        if date.months.get() >= 0 && date.days.get() >= 0 && time.secs.get() >= 0
            || date.months.get() <= 0 && date.days.get() <= 0 && time.secs.get() <= 0
        {
            Some(Self { date, time })
        } else {
            None
        }
    }

    pub(crate) fn mul(self, factor: i32) -> Option<Self> {
        let Self { date, time } = self;
        date.mul(factor)
            .zip(time.mul(factor.into()))
            .map(|(date, time)| Self { date, time })
    }

    pub(crate) fn add(self, other: Self) -> Result<Self, InitError> {
        let date = self.date.add(other.date)?;
        let time = self.time.add(other.time).ok_or(InitError::TooBig)?;
        if date.months.get() >= 0 && date.days.get() >= 0 && time.secs.get() >= 0
            || date.months.get() <= 0 && date.days.get() <= 0 && time.secs.get() <= 0
        {
            Ok(Self { date, time })
        } else {
            Err(InitError::MixedSign)
        }
    }

    pub(crate) fn fmt_iso(self) -> String {
        let mut result = String::with_capacity(8);
        let Self { date, time } =
            if self.time.secs.get() < 0 || self.date.months.get() < 0 || self.date.days.get() < 0 {
                result.push('-');
                -self
            } else if self.time.is_zero() && self.date.is_zero() {
                return "P0D".to_string();
            } else {
                self
            };
        result.push('P');
        if !date.is_zero() {
            format_components(date, &mut result);
        }
        if !time.is_zero() {
            result.push('T');
            fmt_components_abs(time, &mut result);
        }
        result
    }

    pub(crate) fn parse_iso(mut s: &[u8]) -> Option<Self> {
        if s.len() < 3 {
            return None;
        }
        let negative = parse_prefix(&mut s)?;
        if s.last()?.eq_ignore_ascii_case(&b'T') {
            return None;
        }
        let mut date = parse_date_components(&mut s)?;
        let mut time = if s.is_empty() {
            TimeDelta::ZERO
        } else if s[0].eq_ignore_ascii_case(&b'T') {
            s = &s[1..];
            let (nanos, _) = parse_all_components(&mut s)?;
            TimeDelta::from_nanos(nanos as _)?
        } else {
            return None;
        };
        if negative {
            date = -date;
            time = -time;
        }
        Some(Self { date, time })
    }
}

impl Neg for DateTimeDelta {
    type Output = Self;

    fn neg(self) -> Self {
        Self {
            date: -self.date,
            time: -self.time,
        }
    }
}

impl fmt::Display for DateTimeDelta {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        let mut isofmt = self.fmt_iso().into_bytes();
        for byte in isofmt.iter_mut().skip(2) {
            if *byte != b'T' {
                *byte = byte.to_ascii_lowercase();
            }
        }
        // SAFETY: ISO formatting only emits ASCII.
        f.write_str(unsafe { std::str::from_utf8_unchecked(&isofmt) })
    }
}

fn parse_date_components(s: &mut &[u8]) -> Option<DateDelta> {
    let mut months = 0;
    let mut days = 0;
    let mut previous = None;
    while !s.is_empty() && !s[0].eq_ignore_ascii_case(&b'T') {
        let (value, unit) = parse_component(s)?;
        match (unit, previous.replace(unit)) {
            (CalendarUnit::Years, None) => months += value * 12,
            (CalendarUnit::Months, None | Some(CalendarUnit::Years)) => months += value,
            (CalendarUnit::Weeks, None | Some(CalendarUnit::Years | CalendarUnit::Months)) => {
                days += value * 7
            }
            (CalendarUnit::Days, _) => {
                days += value;
                break;
            }
            _ => return None,
        }
    }
    Some(DateDelta {
        months: DeltaMonths::new(months)?,
        days: DeltaDays::new(days)?,
    })
}
