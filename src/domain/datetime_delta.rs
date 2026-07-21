use super::{
    date_delta::{DateDelta, InitError, format_components, parse_component, parse_prefix},
    scalar::{DeltaDays, DeltaMonths},
    time_delta::{TimeDelta, fmt_components_abs, parse_all_components},
};
use crate::common::math::CalUnit;
use std::{fmt, ops::Neg};

#[derive(Debug, Eq, PartialEq, Copy, Clone)]
pub(crate) struct DateTimeDelta {
    // invariant: these never have opposite signs
    pub(crate) ddelta: DateDelta,
    pub(crate) tdelta: TimeDelta,
}

impl DateTimeDelta {
    pub(crate) const ZERO: Self = Self {
        ddelta: DateDelta::ZERO,
        tdelta: TimeDelta::ZERO,
    };

    pub(crate) fn new(ddelta: DateDelta, tdelta: TimeDelta) -> Option<Self> {
        if ddelta.months.get() >= 0 && ddelta.days.get() >= 0 && tdelta.secs.get() >= 0
            || ddelta.months.get() <= 0 && ddelta.days.get() <= 0 && tdelta.secs.get() <= 0
        {
            Some(Self { ddelta, tdelta })
        } else {
            None
        }
    }

    pub(crate) fn checked_mul(self, factor: i32) -> Option<Self> {
        let Self { ddelta, tdelta } = self;
        ddelta
            .mul(factor)
            .zip(tdelta.mul(factor.into()))
            .map(|(ddelta, tdelta)| Self { ddelta, tdelta })
    }

    pub(crate) fn add(self, other: Self) -> Result<Self, InitError> {
        let ddelta = self.ddelta.add(other.ddelta)?;
        let tdelta = self.tdelta.add(other.tdelta).ok_or(InitError::TooBig)?;
        if ddelta.months.get() >= 0 && ddelta.days.get() >= 0 && tdelta.secs.get() >= 0
            || ddelta.months.get() <= 0 && ddelta.days.get() <= 0 && tdelta.secs.get() <= 0
        {
            Ok(Self { ddelta, tdelta })
        } else {
            Err(InitError::MixedSign)
        }
    }

    pub(crate) fn fmt_iso(self) -> String {
        let mut result = String::with_capacity(8);
        let Self { ddelta, tdelta } = if self.tdelta.secs.get() < 0
            || self.ddelta.months.get() < 0
            || self.ddelta.days.get() < 0
        {
            result.push('-');
            -self
        } else if self.tdelta.is_zero() && self.ddelta.is_zero() {
            return "P0D".to_string();
        } else {
            self
        };
        result.push('P');
        if !ddelta.is_zero() {
            format_components(ddelta, &mut result);
        }
        if !tdelta.is_zero() {
            result.push('T');
            fmt_components_abs(tdelta, &mut result);
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
        let mut ddelta = parse_date_components(&mut s)?;
        let mut tdelta = if s.is_empty() {
            TimeDelta::ZERO
        } else if s[0].eq_ignore_ascii_case(&b'T') {
            s = &s[1..];
            let (nanos, _) = parse_all_components(&mut s)?;
            TimeDelta::from_nanos(nanos as _)?
        } else {
            return None;
        };
        if negative {
            ddelta = -ddelta;
            tdelta = -tdelta;
        }
        Some(Self { ddelta, tdelta })
    }
}

impl Neg for DateTimeDelta {
    type Output = Self;

    fn neg(self) -> Self {
        Self {
            ddelta: -self.ddelta,
            tdelta: -self.tdelta,
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
            (CalUnit::Years, None) => months += value * 12,
            (CalUnit::Months, None | Some(CalUnit::Years)) => months += value,
            (CalUnit::Weeks, None | Some(CalUnit::Years | CalUnit::Months)) => days += value * 7,
            (CalUnit::Days, _) => {
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
