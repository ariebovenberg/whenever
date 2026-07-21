use super::scalar::{DeltaDays, DeltaMonths};
use crate::common::math::CalUnit;
use std::{fmt, ops::Neg};

#[derive(Debug, Eq, PartialEq, Copy, Clone)]
pub(crate) struct DateDelta {
    // invariant: these never have opposite signs
    pub(crate) months: DeltaMonths,
    pub(crate) days: DeltaDays,
}

pub(crate) enum InitError {
    TooBig,
    MixedSign,
}

impl DateDelta {
    pub(crate) const ZERO: Self = Self {
        months: DeltaMonths::ZERO,
        days: DeltaDays::ZERO,
    };

    pub(crate) fn new(months: DeltaMonths, days: DeltaDays) -> Option<Self> {
        same_sign(months, days).then_some(Self { months, days })
    }

    pub(crate) fn from_months(months: DeltaMonths) -> Self {
        Self {
            months,
            days: DeltaDays::ZERO,
        }
    }

    pub(crate) fn from_days(days: DeltaDays) -> Self {
        Self {
            months: DeltaMonths::ZERO,
            days,
        }
    }

    pub(crate) fn mul(self, factor: i32) -> Option<Self> {
        let Self { months, days } = self;
        months
            .mul(factor)
            .zip(days.mul(factor))
            .map(|(months, days)| Self { months, days })
    }

    pub(crate) fn add(self, other: Self) -> Result<Self, InitError> {
        let Self { months, days } = self;
        let (months, days) = months
            .add(other.months)
            .zip(days.add(other.days))
            .ok_or(InitError::TooBig)?;
        Self::new(months, days).ok_or(InitError::MixedSign)
    }

    pub(crate) fn is_zero(self) -> bool {
        self.months.is_zero() && self.days.is_zero()
    }

    pub(crate) fn abs(self) -> Self {
        Self {
            months: self.months.abs(),
            days: self.days.abs(),
        }
    }

    pub(crate) fn fmt_iso(self) -> String {
        let mut result = String::with_capacity(8);
        let Self { months, days } = self;
        let absolute = if months.get() < 0 || days.get() < 0 {
            result.push('-');
            -self
        } else if months.is_zero() && days.is_zero() {
            return "P0D".to_string();
        } else {
            self
        };
        result.push('P');
        format_components(absolute, &mut result);
        result
    }

    pub(crate) fn parse_iso(mut s: &[u8]) -> Option<Self> {
        if s.len() < 3 {
            return None;
        }
        let negative = parse_prefix(&mut s)?;
        let mut months = 0;
        let mut days = 0;
        let mut previous = None;
        while !s.is_empty() {
            let (value, unit) = parse_component(&mut s)?;
            match (unit, previous.replace(unit)) {
                (CalUnit::Years, None) => months += value * 12,
                (CalUnit::Months, None | Some(CalUnit::Years)) => months += value,
                (CalUnit::Weeks, None | Some(CalUnit::Years | CalUnit::Months)) => {
                    days += value * 7
                }
                (CalUnit::Days, _) if s.is_empty() => days += value,
                _ => return None,
            }
        }
        previous?;
        if negative {
            months = -months;
            days = -days;
        }
        Some(Self {
            months: DeltaMonths::new(months)?,
            days: DeltaDays::new(days)?,
        })
    }
}

impl Neg for DateDelta {
    type Output = Self;

    fn neg(self) -> Self {
        Self {
            months: -self.months,
            days: -self.days,
        }
    }
}

impl fmt::Display for DateDelta {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        let mut isofmt = self.fmt_iso().into_bytes();
        for byte in isofmt.iter_mut().skip(2) {
            *byte = byte.to_ascii_lowercase();
        }
        // SAFETY: fmt_iso only emits ASCII.
        f.write_str(unsafe { String::from_utf8_unchecked(isofmt) }.as_str())
    }
}

fn same_sign(months: DeltaMonths, days: DeltaDays) -> bool {
    months.get() >= 0 && days.get() >= 0 || months.get() <= 0 && days.get() <= 0
}

pub(crate) fn format_components(delta: DateDelta, result: &mut String) {
    let mut months = delta.months.get();
    let days = delta.days.get();
    debug_assert!(months >= 0 && days >= 0);
    debug_assert!(months > 0 || days > 0);
    let years = months / 12;
    months %= 12;
    if years != 0 {
        result.push_str(&format!("{years}Y"));
    }
    if months != 0 {
        result.push_str(&format!("{months}M"));
    }
    if days != 0 {
        result.push_str(&format!("{days}D"));
    }
}

pub(crate) fn parse_prefix(s: &mut &[u8]) -> Option<bool> {
    debug_assert!(s.len() >= 2);
    match s[0] {
        b'P' | b'p' => {
            *s = &s[1..];
            Some(false)
        }
        b'-' if s[1].eq_ignore_ascii_case(&b'P') => {
            *s = &s[2..];
            Some(true)
        }
        b'+' if s[1].eq_ignore_ascii_case(&b'P') => {
            *s = &s[2..];
            Some(false)
        }
        _ => None,
    }
}

fn finish_parsing_component(s: &mut &[u8], mut value: i32) -> Option<(i32, CalUnit)> {
    for i in 1..s.len().min(9) {
        match s[i] {
            c if c.is_ascii_digit() => value = value * 10 + i32::from(c - b'0'),
            b'D' | b'd' => {
                *s = &s[i + 1..];
                return Some((value, CalUnit::Days));
            }
            b'W' | b'w' => {
                *s = &s[i + 1..];
                return Some((value, CalUnit::Weeks));
            }
            b'M' | b'm' => {
                *s = &s[i + 1..];
                return Some((value, CalUnit::Months));
            }
            b'Y' | b'y' => {
                *s = &s[i + 1..];
                return Some((value, CalUnit::Years));
            }
            _ => return None,
        }
    }
    None
}

pub(crate) fn parse_component(s: &mut &[u8]) -> Option<(i32, CalUnit)> {
    (s.len() >= 2 && s[0].is_ascii_digit())
        .then(|| finish_parsing_component(s, (s[0] - b'0').into()))
        .flatten()
}
