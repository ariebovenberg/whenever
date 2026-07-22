use super::{
    itemized_delta::ItemizedDelta,
    scalar::{
        DeltaField, DeltaNanos, DeltaSeconds, NS_PER_HOUR, NS_PER_MINUTE, NS_PER_SEC, Offset,
        SubSecNanos,
    },
};
use crate::common::{
    math::{self, ExactUnit, ExactUnitSet},
    parse::extract_digit,
    round,
};
use std::{fmt, ops::Neg};

/// A duration of time with nanosecond precision.
#[derive(Debug, Eq, PartialEq, Ord, PartialOrd, Copy, Clone)]
pub(crate) struct TimeDelta {
    // Invariant: a TimeDelta is always between TimeDelta::MIN and TimeDelta::MAX, inclusive.
    pub(crate) secs: DeltaSeconds,
    pub(crate) subsec: SubSecNanos,
}

impl TimeDelta {
    pub(crate) const MIN: Self = Self {
        secs: DeltaSeconds::MIN,
        subsec: SubSecNanos::MIN,
    };
    pub(crate) const MAX: Self = Self {
        secs: DeltaSeconds::MAX,
        subsec: SubSecNanos::MIN,
    };
    pub(crate) const RESOLUTION: Self = Self {
        secs: DeltaSeconds::ZERO,
        subsec: SubSecNanos::new_unchecked(1),
    };
    pub(crate) const ZERO: Self = Self {
        secs: DeltaSeconds::ZERO,
        subsec: SubSecNanos::MIN,
    };

    pub(crate) fn from_nanos_f64(nanos: f64) -> Option<Self> {
        if nanos.is_nan()
            || !(DeltaNanos::MIN.get() as f64..=DeltaNanos::MAX.get() as f64).contains(&nanos)
        {
            return None;
        }
        let nanos = nanos as i128;
        Some(TimeDelta {
            secs: DeltaSeconds::new_unchecked(nanos.div_euclid(NS_PER_SEC as i128) as _),
            subsec: SubSecNanos::new_unchecked(nanos.rem_euclid(NS_PER_SEC as i128) as _),
        })
    }

    pub(crate) fn to_nanos_f64(self) -> f64 {
        self.secs.get() as f64 * 1e9 + self.subsec.get() as f64
    }

    pub(crate) const fn from_nanos_unchecked(nanos: i128) -> Self {
        TimeDelta {
            secs: DeltaSeconds::new_unchecked(nanos.div_euclid(NS_PER_SEC as i128) as _),
            subsec: SubSecNanos::new_unchecked(nanos.rem_euclid(NS_PER_SEC as i128) as _),
        }
    }

    pub(crate) fn from_nanos(nanos: i128) -> Option<Self> {
        let (secs, subsec) = DeltaNanos::new(nanos)?.sec_subsec();
        Some(Self { secs, subsec })
    }

    pub(crate) const fn total_nanos(self) -> i128 {
        self.secs.get() as i128 * NS_PER_SEC as i128 + self.subsec.get() as i128
    }

    pub(crate) const fn is_zero(self) -> bool {
        self.secs.get() == 0 && self.subsec.get() == 0
    }

    pub(crate) fn abs(self) -> Self {
        if self.secs.get() >= 0 { self } else { -self }
    }

    pub(crate) fn mul(self, factor: i128) -> Option<Self> {
        self.total_nanos()
            .checked_mul(factor)
            .and_then(Self::from_nanos)
    }

    pub(crate) fn add(self, other: Self) -> Option<Self> {
        Self::from_nanos(self.total_nanos() + other.total_nanos())
    }

    pub(crate) fn round(self, increment: DeltaIncrement, abs_mode: round::AbsMode) -> Option<Self> {
        debug_assert!(increment.secs > 0 || increment.subsec.get() > 0);
        if increment.secs == 0 && NS_PER_SEC.is_multiple_of(increment.subsec.as_u32()) {
            let (extra_secs, subsec) = self.subsec.round(increment.subsec.as_u32(), abs_mode);
            Self {
                secs: self.secs.add(extra_secs).unwrap(),
                subsec,
            }
        } else {
            self.round_u128(increment.total_nanos(), abs_mode)?
        }
        .into()
    }

    fn round_u128(self, increment: u128, abs_mode: round::AbsMode) -> Option<Self> {
        debug_assert!(increment > 0);
        debug_assert!(increment <= i128::MAX as u128);
        let increment = increment as i128;
        let total_ns = self.total_nanos();
        let quotient = total_ns.div_euclid(increment);
        let remainder = total_ns.rem_euclid(increment);
        let threshold = match abs_mode {
            round::AbsMode::HalfEven => {
                1i128.max(increment / 2 + quotient.unsigned_abs().is_multiple_of(2) as i128)
            }
            round::AbsMode::Expand => 1,
            round::AbsMode::Trunc => increment + 1,
            round::AbsMode::HalfTrunc => increment / 2 + 1,
            round::AbsMode::HalfExpand => 1i128.max(increment / 2),
        };
        let result_ns = (quotient + i128::from(remainder >= threshold)) * increment;
        Some(Self {
            secs: DeltaSeconds::new(result_ns.div_euclid(NS_PER_SEC as i128) as i64)?,
            subsec: SubSecNanos::new_unchecked(result_ns.rem_euclid(NS_PER_SEC as i128) as i32),
        })
    }

    pub(crate) fn fmt_iso(self) -> String {
        if self.is_zero() {
            return "PT0S".to_string();
        }
        let mut result = String::with_capacity(8);
        let absolute = if self.is_negative() {
            result.push('-');
            -self
        } else {
            self
        };
        result.push_str("PT");
        fmt_components_abs(absolute, &mut result);
        result
    }

    pub(crate) fn in_exact_units(
        self,
        units: ExactUnitSet,
        round_increment: math::RoundIncrement,
        round_mode: round::AbsMode,
    ) -> Option<ItemizedDelta> {
        debug_assert!(
            !units.contains(ExactUnit::Milliseconds) && !units.contains(ExactUnit::Microseconds)
        );
        let increment = (units.smallest().in_nanos() as u64 as u128)
            .checked_mul(round_increment.as_i128() as u128)
            .and_then(DeltaIncrement::from_nanos)?;
        let rounded = self.round(increment, round_mode)?;

        let mut remaining = rounded.total_nanos();
        let mut target = ItemizedDelta::UNSET;
        type Setter = fn(&mut ItemizedDelta, i128);
        let fields: &[(ExactUnit, Setter)] = &[
            (ExactUnit::Weeks, |target, value| {
                target.weeks = DeltaField::new_unchecked(value as i32)
            }),
            (ExactUnit::Days, |target, value| {
                target.days = DeltaField::new_unchecked(value as i32)
            }),
            (ExactUnit::Hours, |target, value| {
                target.hours = DeltaField::new_unchecked(value as i32)
            }),
            (ExactUnit::Minutes, |target, value| {
                target.minutes = DeltaField::new_unchecked(value as i64)
            }),
            (ExactUnit::Seconds, |target, value| {
                target.seconds = DeltaField::new_unchecked(value as i64)
            }),
        ];
        for &(unit, setter) in fields {
            if units.contains(unit) {
                let per = unit.in_nanos() as i128;
                let value = remaining / per;
                remaining %= per;
                setter(&mut target, value);
            }
        }
        if units.contains(ExactUnit::Nanoseconds) {
            target.nanos = DeltaField::new_unchecked(remaining as i32);
        }
        Some(target)
    }

    pub(crate) fn negate_if(self, condition: bool) -> Self {
        if condition { -self } else { self }
    }

    pub(crate) fn is_negative(self) -> bool {
        self.secs.get() < 0
    }
}

impl Neg for TimeDelta {
    type Output = Self;

    fn neg(self) -> TimeDelta {
        TimeDelta::from_nanos_unchecked(-self.total_nanos())
    }
}

impl fmt::Display for TimeDelta {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        let mut isofmt = self.fmt_iso().into_bytes();
        for c in isofmt.iter_mut().skip(3) {
            *c = c.to_ascii_lowercase();
        }
        // SAFETY: ISO formatting only emits ASCII.
        f.write_str(unsafe { std::str::from_utf8_unchecked(&isofmt) })
    }
}

#[inline]
pub(crate) fn fmt_components_abs(delta: TimeDelta, result: &mut String) {
    let TimeDelta { secs, subsec } = delta;
    debug_assert!(secs.get() >= 0);
    let (hours, minutes, seconds) = secs.abs_hms();
    if hours != 0 {
        result.push_str(&format!("{hours}H"));
    }
    if minutes != 0 {
        result.push_str(&format!("{minutes}M"));
    }
    if seconds != 0 || subsec.get() != 0 {
        result.push_str(&format!("{seconds}{subsec}S"));
    }
}

pub(crate) fn parse_prefix(s: &mut &[u8]) -> Option<bool> {
    let negative = match s[0] {
        b'+' => {
            *s = &s[1..];
            false
        }
        b'-' => {
            *s = &s[1..];
            true
        }
        _ => false,
    };
    s[..2].eq_ignore_ascii_case(b"PT").then(|| {
        *s = &s[2..];
        negative
    })
}

#[derive(Debug, Copy, Clone, PartialEq, Eq, PartialOrd, Ord)]
pub(crate) enum TimeUnit {
    Hours,
    Minutes,
    Nanos { has_fraction: bool },
}

fn parse_nano_fractions(s: &[u8]) -> Option<u32> {
    if s.is_empty() {
        return None;
    }
    let mut tally = extract_digit(s, 0)? as u32 * 100_000_000;
    for i in 1..s.len().min(9) {
        match s[i] {
            c if c.is_ascii_digit() => tally += u32::from(c - b'0') * 10_u32.pow(8 - i as u32),
            b'S' | b's' if i + 1 == s.len() => return Some(tally),
            _ => return None,
        }
    }
    (s.len() == 10 && s[9].eq_ignore_ascii_case(&b's')).then_some(tally)
}

pub(crate) fn parse_time_component(s: &mut &[u8]) -> Option<(u128, TimeUnit)> {
    if s.len() < 2 {
        return None;
    }
    let mut tally: u128 = 0;
    for i in 0..s.len().min(35) {
        match s[i] {
            c if c.is_ascii_digit() => tally = tally * 10 + u128::from(c - b'0'),
            b'H' | b'h' if i > 0 => {
                *s = &s[i + 1..];
                return Some((tally, TimeUnit::Hours));
            }
            b'M' | b'm' if i > 0 => {
                *s = &s[i + 1..];
                return Some((tally, TimeUnit::Minutes));
            }
            b'S' | b's' if i > 0 => {
                *s = &s[i + 1..];
                return Some((
                    tally.checked_mul(NS_PER_SEC as u128)?,
                    TimeUnit::Nanos {
                        has_fraction: false,
                    },
                ));
            }
            b'.' | b',' if i > 0 => {
                let result = parse_nano_fractions(&s[i + 1..]).and_then(|nanos| {
                    Some((
                        tally
                            .checked_mul(NS_PER_SEC as u128)?
                            .checked_add(nanos as u128)?,
                        TimeUnit::Nanos { has_fraction: true },
                    ))
                });
                *s = &[];
                return result;
            }
            _ => break,
        }
    }
    None
}

pub(crate) fn parse_all_components(s: &mut &[u8]) -> Option<(u128, bool)> {
    let mut previous = None;
    let mut nanos: u128 = 0;
    while !s.is_empty() {
        let (value, unit) = parse_time_component(s)?;
        match (unit, previous.replace(unit)) {
            (TimeUnit::Hours, None) => {
                nanos = nanos.checked_add(value.checked_mul(NS_PER_HOUR as u128)?)?;
            }
            (TimeUnit::Minutes, None | Some(TimeUnit::Hours)) => {
                nanos = nanos.checked_add(value.checked_mul(NS_PER_MINUTE as u128)?)?;
            }
            (TimeUnit::Nanos { .. }, _) => {
                nanos = nanos.checked_add(value)?;
                if !s.is_empty() {
                    return None;
                }
                break;
            }
            _ => return None,
        }
    }
    Some((nanos, previous.is_none()))
}

impl Offset {
    pub(crate) const fn to_delta(self) -> TimeDelta {
        TimeDelta {
            secs: DeltaSeconds::new_unchecked(self.get() as _),
            subsec: SubSecNanos::MIN,
        }
    }
}

#[derive(Debug, Copy, Clone, PartialEq, Eq)]
pub(crate) struct DeltaIncrement {
    pub(crate) secs: u64,
    pub(crate) subsec: SubSecNanos,
}

impl DeltaIncrement {
    pub(crate) fn from_nanos(nanos: u128) -> Option<Self> {
        (nanos != 0).then_some(Self {
            secs: u64::try_from(nanos / NS_PER_SEC as u128).ok()?,
            subsec: SubSecNanos::from_remainder(nanos),
        })
    }

    pub(crate) fn total_nanos(self) -> u128 {
        self.secs as u128 * NS_PER_SEC as u128 + self.subsec.as_u32() as u128
    }
}
