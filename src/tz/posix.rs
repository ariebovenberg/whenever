/// Functionality for working with POSIX TZ strings
///
/// Resources:
/// - [POSIX TZ strings](https://pubs.opengroup.org/onlinepubs/9699919799/basedefs/V1_chap08.html)
/// - [GNU libc manual](https://www.gnu.org/software/libc/manual/html_node/TZ-Variable.html)
use crate::common::{
    clamp, EpochSeconds, Month, Offset, OffsetResult, Year, MAX_OFFSET, S_PER_DAY,
};
use crate::date::{days_before_year, days_in_month, is_leap, Date};
use crate::instant::UNIX_EPOCH_INSTANT;
use crate::time::Time;
use std::io::Cursor;
use std::num::{NonZeroU16, NonZeroU8};
use std::ops::RangeInclusive;

const DEFAULT_DST: Offset = 3_600;
pub(crate) type Weekday = u8; // 0 is Sunday, 6 is Saturday
                              // RFC 9636: the transition time may range from -167 to 167 hours! (not just 24)
pub(crate) type TransitionTime = i32;
const DEFAULT_RULE_TIME: i32 = 2 * 3_600; // 2 AM

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct TZ {
    std: Offset,
    dst: Option<DST>,
    // We don't store the TZ names since we don't use them (yet)
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) struct DST {
    offset: Offset,
    start: (Rule, TransitionTime),
    end: (Rule, TransitionTime),
}

/// A rule for the date when DST starts or ends
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) enum Rule {
    LastWeekday(Weekday, Month),
    NthWeekday(NonZeroU8, Weekday, Month), // N is 1..=4
    DayOfYear(NonZeroU16),                 // 1..=366, accounts for leap days
    JulianDayOfYear(NonZeroU16),           // 1..=365, ignores leap days
}

impl TZ {
    pub(crate) fn offset_for_instant(&self, epoch: EpochSeconds) -> Offset {
        match self.dst {
            None => self.std, // No DST rule means a fixed offset
            Some(DST {
                start: (start_rule, start_time),
                end: (end_rule, end_time),
                offset: dst_offset,
            }) => {
                // To determine the exact instant of DST start/end,
                // we need to know the *local* year.
                // However, this is theoretically difficult to determine
                // since we don't *strictly* know the if DST is active,
                // and thus what the offset should be.
                // However, in practice, we can assume that DST isn't active
                // at the start of the year, and that DST rules don't straddle years.
                // This is what Python's `zoneinfo` does anyway...
                let year = Date::from_unix_days_unchecked(
                    ((epoch + self.std as i64) / S_PER_DAY as i64) as _,
                )
                .year
                .try_into()
                .unwrap();
                let dst_start = start_rule.for_year(year).unix_days() as i64 * S_PER_DAY as i64
                    + start_time as i64
                    - self.std as i64;
                // fast path: avoid calculating the end time at all
                if epoch < dst_start {
                    self.std
                } else {
                    let dst_end = end_rule.for_year(year).unix_days() as i64 * S_PER_DAY as i64
                        + end_time as i64
                        - dst_offset as i64;
                    if epoch < dst_end {
                        dst_offset
                    } else {
                        self.std
                    }
                }
            }
        }
    }

    pub(crate) fn offset_for_local(&self, date: Date, time: Time) -> OffsetResult {
        fn epoch(d: Date, t: TransitionTime) -> i64 {
            // Safety: value ranges save us from overflow
            d.unix_days() as i64 * S_PER_DAY as i64 + t as i64
        }

        match self.dst {
            None => OffsetResult::Unambiguous(self.std), // No DST
            Some(DST {
                // NOTE: There's nothing preventing end from being before start,
                // but this shouldn't happen in practice. We don't crash, at least.
                start: (start_rule, start_time),
                end: (end_rule, end_time),
                offset,
            }) => {
                let year = date.year.try_into().unwrap(); // known to be >0
                let instant = epoch(date, time.total_seconds() as _);
                let dst_start = epoch(start_rule.for_year(year), start_time);
                let dst_shift = (offset - self.std) as i64;
                // In rare cases, the dst shift is negative.
                // We handle the common case first.
                if dst_shift >= 0 {
                    if instant < dst_start {
                        OffsetResult::Unambiguous(self.std)
                    } else if instant < dst_start + dst_shift {
                        OffsetResult::Gap(offset, self.std)
                    } else {
                        let dst_end = epoch(end_rule.for_year(year), end_time);
                        if instant < dst_end - dst_shift {
                            OffsetResult::Unambiguous(offset)
                        } else if instant < dst_end {
                            OffsetResult::Fold(offset, self.std)
                        } else {
                            OffsetResult::Unambiguous(self.std)
                        }
                    }
                } else {
                    if instant < dst_start + dst_shift {
                        OffsetResult::Unambiguous(self.std)
                    } else if instant < dst_start {
                        OffsetResult::Fold(self.std, offset)
                    } else {
                        let dst_end = epoch(end_rule.for_year(year), end_time);
                        if instant < dst_end {
                            OffsetResult::Unambiguous(offset)
                        } else if instant < dst_end - dst_shift {
                            OffsetResult::Gap(self.std, offset)
                        } else {
                            OffsetResult::Unambiguous(self.std)
                        }
                    }
                }
            }
        }
    }
}

fn weekday(d: Date) -> Weekday {
    (d.ord() % 7) as _
}

impl Rule {
    #[allow(dead_code)]
    fn for_year(&self, y: Year) -> Date {
        match self {
            &Rule::DayOfYear(d) => {
                // The 366th day will blow up for non-leap years,
                // It's unlikely that a TZ string would specify this,
                // so we'll just clamp it to the last day of the year.
                let doy = if d.get() == 366 && !is_leap(y.get()) {
                    365
                } else {
                    d.get() as u32
                };
                Date::from_ord_unchecked(days_before_year(y.into()) + doy)
            }
            &Rule::JulianDayOfYear(d) => {
                let doy = d.get() as u32 + (is_leap(y.get()) && d.get() > 59) as u32;
                Date::from_ord_unchecked(days_before_year(y.into()) + doy)
            }
            &Self::LastWeekday(w, m) => {
                // Try the last day of the month, and adjust from there
                let day_last =
                    Date::new_unchecked(y.get(), m.get(), days_in_month(y.get(), m.get()));
                Date {
                    day: day_last.day - (weekday(day_last) + 7 - w) % 7,
                    ..day_last
                }
            }
            &Self::NthWeekday(n, w, m) => {
                // Try the first day of the month, and adjust from there
                debug_assert!(n.get() <= 4);
                let day1 = Date::new_unchecked(y.get(), m.get(), 1);
                Date {
                    day: ((w + 7 - weekday(day1)) % 7) + 7 * (n.get() - 1) + 1,
                    ..day1
                }
            }
        }
    }
}

#[allow(dead_code)]
pub fn parse(s: &[u8]) -> Option<TZ> {
    // So that all further parsing functions can assume ASCII input
    if !s.is_ascii() {
        return None;
    }
    let (mut std, s) = skip_tzname(s).and_then(parse_offset)?;
    std = -std; // POSIX offsets are inverted from how we store them

    // If there's nothing else, it's a fixed offset without DST
    if s.is_empty() {
        return Some(TZ { std, dst: None });
    };
    let s = skip_tzname(s)?;
    // Parse the DST offset. If omitted, the default is 1 hour ahead.
    // After the DST offset, there is a comma before the rules begin.
    let (dst_offset, s) = if s.get(0)? == &b',' {
        (clamp(std + DEFAULT_DST, MAX_OFFSET)?, &s[1..])
    } else {
        let (mut dst, s) = parse_offset(s)?;
        dst = -dst; // POSIX offsets are inverted from how we store them
        if s.get(0)? == &b',' {
            (dst, &s[1..])
        } else {
            return None;
        }
    };

    // Expect two rules separated by a comma
    let (start, s) = parse_rule(s)?;
    let (end, s) = match s.get(0)? {
        b',' => parse_rule(&s[1..])?,
        _ => None?,
    };
    // No content should remain after parsing
    s.is_empty().then_some(TZ {
        std,
        dst: Some(DST {
            offset: dst_offset,
            start,
            end,
        }),
    })
}

/// Skip the TZ name and return the remaining slice,
/// which is guaranteed to be non-empty.
fn skip_tzname(s: &[u8]) -> Option<&[u8]> {
    // name is at least 3 characters long and offset is at least 1 char
    // Note also that in Tzif files, TZ names are limited to 6 characters.
    // This might be useful in the future for optimization
    if s.len() < 4 {
        return None;
    }
    // There are two types of TZ names.
    let splitpos = if s[0] == b'<' {
        // TZ name enclosed in "<" and ">"
        let end = s.iter().position(|&c| c == b'>')?;
        if end == s.len() - 1 {
            return None;
        }
        end + 1
    } else {
        // TZ name is a sequence of letters until encountering a digit or [+-]
        s.iter()
            .position(|&c| matches!(c, b'+' | b'-' | b',' | b'0'..=b'9'))?
    };
    Some(&s[splitpos..])
}

/// Parse an offset like `[+|-]h[h][:mm[:ss]]`
fn parse_offset(s: &[u8]) -> Option<(Offset, &[u8])> {
    parse_hms(s, MAX_OFFSET as u32)
}

/// Parse a `h[hh][:mm[:ss]]` string into a total number of seconds
fn parse_hms(s: &[u8], max: u32) -> Option<(i32, &[u8])> {
    let (sign, s) = match s.get(0)? {
        b'-' => (-1, &s[1..]),
        b'+' => (1, &s[1..]),
        _ => (1, s),
    };

    // Parse the hours
    let (hrs, s) = if max > 99 * 3_600 {
        parse_1to3_digits(s)
    } else {
        parse_1or2_digits(s).map(|(h, s)| (h as _, s))
    }?;
    let mut total = hrs as u32 * 3_600;

    // Parse the minutes
    let s = match s.get(0) {
        Some(b':') => {
            let (mins, s) = parse_00_to_59(&s[1..])?;
            total += mins as u32 * 60;

            // Parse the seconds
            match s.get(0) {
                Some(b':') => {
                    let (secs, s) = parse_00_to_59(&s[1..])?;
                    total += secs as u32;
                    s
                }
                _ => s,
            }
        }
        _ => s,
    };
    (total <= max).then_some((total as i32 * sign, s))
}

/// Parse `m[m].w.d` string as part of a DST start/end rule
fn parse_weekday_rule(s: &[u8]) -> Option<(Rule, &[u8])> {
    // Handle the variable length of months
    let (m_unchecked, w_raw, d_raw, rest) = match s {
        &[m1, m2, b'.', w, b'.', d, ..] => (
            parse_one_digit(m1)? * 10 + parse_one_digit(m2)?,
            w,
            d,
            &s[6..],
        ),
        &[m, b'.', w, b'.', d, ..] => (parse_one_digit(m)?, w, d, &s[5..]),
        _ => None?,
    };
    let m = (m_unchecked <= 12).then_some(NonZeroU8::new(m_unchecked)?)?;
    let w = parse_one_digit_ranged(w_raw, b'1'..=b'5')?;
    let d = parse_one_digit_ranged(d_raw, b'0'..=b'6')?;
    // A "fifth" occurrence of a weekday doesn't always occur.
    // Interpret it as the last weekday, according to the standard.
    if w == 5 {
        Some((Rule::LastWeekday(d, m), rest))
    } else {
        Some((
            Rule::NthWeekday(
                // Safety: we've already checked that w is in the range 1..=5
                unsafe { NonZeroU8::new_unchecked(w) },
                d,
                m,
            ),
            rest,
        ))
    }
}

fn parse_1or2_digits(s: &[u8]) -> Option<(u8, &[u8])> {
    let (raw_value, s) = match s {
        &[d1 @ b'0'..=b'9', d2 @ b'0'..=b'9', ..] => (10 * (d1 - b'0') + (d2 - b'0'), &s[2..]),
        &[d @ b'0'..=b'9', ..] => ((d - b'0'), &s[1..]),
        _ => None?,
    };
    Some((raw_value, s))
}

fn parse_00_to_59(s: &[u8]) -> Option<(u8, &[u8])> {
    Some(match s {
        &[d1 @ b'0'..=b'5', d2 @ b'0'..=b'9', ..] => (10 * (d1 - b'0') + (d2 - b'0'), &s[2..]),
        _ => None?,
    })
}

fn parse_1to3_digits(s: &[u8]) -> Option<(u16, &[u8])> {
    fn digit(d: u8) -> u16 {
        (d - b'0') as u16
    }
    Some(match s {
        &[d1 @ b'0'..=b'9', d2 @ b'0'..=b'9', d3 @ b'0'..=b'9', ..] => {
            (100 * digit(d1) + 10 * digit(d2) + digit(d3) as u16, &s[3..])
        }
        &[d1 @ b'0'..=b'9', d2 @ b'0'..=b'9', ..] => (10 * digit(d1) + digit(d2), &s[2..]),
        &[d @ b'0'..=b'9', ..] => (digit(d), &s[1..]),
        _ => None?,
    })
}

fn parse_rule(s: &[u8]) -> Option<((Rule, TransitionTime), &[u8])> {
    let (rule, s) = match s.get(0)? {
        b'M' => parse_weekday_rule(&s[1..]),
        b'J' => {
            let (day, s) = parse_1to3_digits(&s[1..])?;
            NonZeroU16::new(day)
                .filter(|&d| d.get() <= 365)
                .map(|d| (Rule::JulianDayOfYear(d), s))
        }
        _ => {
            let (day, s) = parse_1to3_digits(s)?;
            (day <= 365).then_some((Rule::DayOfYear((day + 1).try_into().unwrap()), s))
        }
    }?;
    let (time, s) = if let Some(b'/') = s.get(0) {
        parse_hms(&s[1..], 167 * 3_600)?
    } else {
        (DEFAULT_RULE_TIME, s)
    };
    Some(((rule, time), s))
}

/// Parse a single ASCII digit
fn parse_one_digit(s: u8) -> Option<u8> {
    s.is_ascii_digit().then_some(s - b'0')
}

/// Parse one digit in the range. Range MUST be valid digits.
fn parse_one_digit_ranged(s: u8, range: RangeInclusive<u8>) -> Option<u8> {
    range.contains(&s).then_some(s - b'0')
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::{common::OffsetResult::*, UNIX_EPOCH_INSTANT};

    #[test]
    fn invalid_start() {
        // empty
        assert_eq!(parse(b""), None);
        // too short
        assert_eq!(parse(b"F"), None);
        // no offset
        assert_eq!(parse(b"FOO"), None);
        // invalid tzname (digit)
        assert_eq!(parse(b"1T"), None);
        // no offset (bracketed tzname)
        assert_eq!(parse(b"<FOO>"), None);
    }

    #[test]
    fn fixed_offset() {
        fn test(s: &[u8], expected: i32) {
            assert_eq!(
                parse(s).unwrap(),
                TZ {
                    std: expected,
                    dst: None
                },
                "{:?} -> {}",
                unsafe { std::str::from_utf8_unchecked(s) },
                expected
            );
        }

        let cases: &[(&[u8], i32)] = &[
            (b"FOO+01", -3600),
            (b"FOO+01:30", -3600 - 30 * 60),
            (b"FOO+01:30:59", -3600 - 30 * 60 - 59),
            (b"FOO+23:59:59", -86_399),
            (b"FOO-23:59:59", 86_399),
            (b"FOO-23:59", 23 * 3600 + 59 * 60),
            (b"FOO-23", 23 * 3600),
            (b"FOO-01", 3600),
            (b"FOO-01:30", 3600 + 30 * 60),
            (b"FOO-01:30:59", 3600 + 30 * 60 + 59),
            (b"FOO+23:59:59", -86_399),
            (b"FOO+23:59", -23 * 3600 - 59 * 60),
            (b"FOO+23", -23 * 3600),
        ];

        for &(s, expected) in cases {
            test(s, expected);
        }
    }

    #[test]
    fn fixed_offset_invalid() {
        fn test(s: &[u8]) {
            assert_eq!(parse(s), None, "parse {:?}", unsafe {
                std::str::from_utf8_unchecked(s)
            });
        }

        let cases: &[&[u8]] = &[
            // Invalid components
            b"FOO+01:",
            b"FOO+01:9:03",
            b"FOO+01:60:03",
            b"FOO-01:59:60",
            b"FOO-01:59:",
            b"FOO-01:59:4",
            // offset too large
            b"FOO24",
            b"FOO+24",
            b"FOO-24",
            b"FOO-27:00",
            b"FOO+27:00",
            b"FOO-25:45:05",
            b"FOO+27:45:09",
            // invalid trailing data
            b"FOO+01:30M",
        ];

        for &case in cases {
            test(case);
        }
    }

    macro_rules! Nu8 {
        ($x:expr) => {
            NonZeroU8::new($x).unwrap()
        };
    }

    macro_rules! Nu16 {
        ($x:expr) => {
            NonZeroU16::new($x).unwrap()
        };
    }

    #[test]
    fn with_dst() {
        // Implicit DST offset
        assert_eq!(
            parse(b"FOO-1FOOS,M3.5.0,M10.4.0").unwrap(),
            TZ {
                std: 3600,
                dst: Some(DST {
                    offset: 7200,
                    start: (Rule::LastWeekday(0, Nu8!(3)), DEFAULT_RULE_TIME),
                    end: (Rule::NthWeekday(Nu8!(4), 0, Nu8!(10)), DEFAULT_RULE_TIME)
                })
            }
        );
        // Explicit DST offset
        assert_eq!(
            parse(b"FOO+1FOOS2:30,M3.5.0,M10.2.0").unwrap(),
            TZ {
                std: -3600,
                dst: Some(DST {
                    offset: -3600 * 2 - 30 * 60,
                    start: (Rule::LastWeekday(0, Nu8!(3)), DEFAULT_RULE_TIME),
                    end: (Rule::NthWeekday(Nu8!(2), 0, Nu8!(10)), DEFAULT_RULE_TIME)
                })
            }
        );
        // Explicit time, weekday rule
        assert_eq!(
            parse(b"FOO+1FOOS2:30,M3.5.0/8,M10.2.0").unwrap(),
            TZ {
                std: -3600,
                dst: Some(DST {
                    offset: -3600 * 2 - 30 * 60,
                    start: (Rule::LastWeekday(0, Nu8!(3)), 8 * 3_600),
                    end: (Rule::NthWeekday(Nu8!(2), 0, Nu8!(10)), DEFAULT_RULE_TIME)
                })
            }
        );
        // Explicit time, Julian day rule
        assert_eq!(
            parse(b"FOO+1FOOS2:30,J023/8:34:01,M10.2.0/03").unwrap(),
            TZ {
                std: -3600,
                dst: Some(DST {
                    offset: -3600 * 2 - 30 * 60,
                    start: (Rule::JulianDayOfYear(Nu16!(23)), 8 * 3_600 + 34 * 60 + 1),
                    end: (Rule::NthWeekday(Nu8!(2), 0, Nu8!(10)), 3 * 3_600)
                })
            }
        );
        // Explicit time, day-of-year rule
        assert_eq!(
            parse(b"FOO+1FOOS2:30,023/8:34:01,J1/0").unwrap(),
            TZ {
                std: -3600,
                dst: Some(DST {
                    offset: -3600 * 2 - 30 * 60,
                    start: (Rule::DayOfYear(Nu16!(24)), 8 * 3_600 + 34 * 60 + 1),
                    end: (Rule::JulianDayOfYear(Nu16!(1)), 0)
                })
            }
        );
        // Explicit time, zeroth day of year
        assert_eq!(
            parse(b"FOO+1FOOS2:30,00/8:34:01,J1/0").unwrap(),
            TZ {
                std: -3600,
                dst: Some(DST {
                    offset: -3600 * 2 - 30 * 60,
                    start: (Rule::DayOfYear(Nu16!(1)), 8 * 3_600 + 34 * 60 + 1),
                    end: (Rule::JulianDayOfYear(Nu16!(1)), 0)
                })
            }
        );
        // 24:00:00 is a valid time for a rule
        assert_eq!(
            parse(b"FOO+2FOOS+1,M3.5.0/24,M10.2.0").unwrap(),
            TZ {
                std: -7200,
                dst: Some(DST {
                    offset: -3600,
                    start: (Rule::LastWeekday(0, Nu8!(3)), 86_400),
                    end: (Rule::NthWeekday(Nu8!(2), 0, Nu8!(10)), DEFAULT_RULE_TIME)
                })
            }
        );
        // Anything between -167 and 167 hours is also valid!
        assert_eq!(
            parse(b"FOO+2FOOS+1,M3.5.0/-89:02,M10.2.0/100").unwrap(),
            TZ {
                std: -7200,
                dst: Some(DST {
                    offset: -3600,
                    start: (Rule::LastWeekday(0, Nu8!(3)), -89 * 3_600 - 2 * 60),
                    end: (Rule::NthWeekday(Nu8!(2), 0, Nu8!(10)), 100 * 3_600)
                })
            }
        );
    }

    #[test]
    fn with_dst_invalid() {
        fn test(s: &[u8]) {
            assert_eq!(parse(s), None);
        }

        let cases: &[&[u8]] = &[
            // Unfinished rule
            b"FOO+01:30BAR,J",
            b"FOO+01:30BAR,",
            b"FOO+01:30BAR,M3.2.",
            // Invalid month rule
            b"FOO+01:30BAR,M13.2.1,M1.1.1",
            b"FOO+01:30BAR,M12.6.1,M1.1.1",
            b"FOO+01:30BAR,M12.2.7,M1.1.1",
            b"FOO+01:30BAR,M12.0.2,M1.1.1",
            // Invalid day of year
            b"FOO+01:30BAR,J366,M1.1.1",
            b"FOO+01:30BAR,J0,M1.1.1",
            b"FOO+01:30BAR,-1,M1.1.1",
            b"FOO+01:30BAR,366,M1.1.1",
            // Trailing data
            b"FOO+01:30BAR,M3.2.1,M1.1.1,",
            b"FOO+01:30BAR,M3.2.1,M1.1.1/0/1",
            // std + 1 hr exceeds 24 hours
            b"FOO-23:30BAR,M3.2.1,M1.1.1",
        ];

        for &case in cases {
            test(case);
        }
    }

    #[test]
    fn day_of_year_rule_for_year() {
        fn test(year: u16, doy: u16, expected: (u16, u8, u8)) {
            let (y, m, d) = expected;
            assert_eq!(
                Rule::DayOfYear(Nu16!(doy)).for_year(Nu16!(year)),
                Date::new_unchecked(y, m, d),
                "year: {}, doy: {} -> {:?}",
                year,
                doy,
                expected
            );
        }
        let cases = [
            // Extremes
            (1, 1, (1, 1, 1)),           // MIN day
            (9999, 366, (9999, 12, 31)), // MAX day
            // no leap year
            (2021, 1, (2021, 1, 1)),     // First day
            (2059, 40, (2059, 2, 9)),    // < Feb 28
            (2221, 59, (2221, 2, 28)),   // Feb 28
            (1911, 60, (1911, 3, 1)),    // Mar 1
            (1900, 124, (1900, 5, 4)),   // > Mar 1
            (2021, 365, (2021, 12, 31)), // Last day
            (2021, 366, (2021, 12, 31)), // Last day (clamped)
            // leap year
            (2024, 1, (2024, 1, 1)),     // First day
            (2060, 40, (2060, 2, 9)),    // < Feb 28
            (2228, 59, (2228, 2, 28)),   // Feb 28
            (2228, 60, (2228, 2, 29)),   // Feb 29
            (1920, 61, (1920, 3, 1)),    // Mar 1
            (2000, 125, (2000, 5, 4)),   // > Mar 1
            (2020, 365, (2020, 12, 30)), // second-to-last day
            (2020, 366, (2020, 12, 31)), // Last day
        ];

        for &(year, day_of_year, expected) in &cases {
            test(year, day_of_year, expected);
        }
    }

    #[test]
    fn julian_day_of_year_rule_for_year() {
        fn test(year: u16, doy: u16, expected: (u16, u8, u8)) {
            let (y, m, d) = expected;
            assert_eq!(
                Rule::JulianDayOfYear(Nu16!(doy)).for_year(Nu16!(year)),
                Date::new_unchecked(y, m, d),
                "year: {}, doy: {} -> {:?}",
                year,
                doy,
                expected
            );
        }
        let cases = [
            // Extremes
            (1, 1, (1, 1, 1)),           // MIN day
            (9999, 365, (9999, 12, 31)), // MAX day
            // no leap year
            (2021, 1, (2021, 1, 1)),     // First day
            (2059, 40, (2059, 2, 9)),    // < Feb 28
            (2221, 59, (2221, 2, 28)),   // Feb 28
            (1911, 60, (1911, 3, 1)),    // Mar 1
            (1900, 124, (1900, 5, 4)),   // > Mar 1
            (2021, 365, (2021, 12, 31)), // Last day
            // leap year
            (2024, 1, (2024, 1, 1)),     // First day
            (2060, 40, (2060, 2, 9)),    // < Feb 28
            (2228, 59, (2228, 2, 28)),   // Feb 28
            (1920, 60, (1920, 3, 1)),    // Mar 1
            (2000, 124, (2000, 5, 4)),   // > Mar 1
            (2020, 364, (2020, 12, 30)), // second-to-last day
            (2020, 365, (2020, 12, 31)), // Last day
        ];

        for &(year, day_of_year, expected) in &cases {
            test(year, day_of_year, expected);
        }
    }

    #[test]
    fn last_weekday_rule_for_year() {
        fn test(year: u16, month: u8, weekday: u8, expected: (u16, u8, u8)) {
            let (y, m, d) = expected;
            assert_eq!(
                Rule::LastWeekday(weekday, Nu8!(month)).for_year(Nu16!(year)),
                Date::new_unchecked(y, m, d),
                "year: {}, month: {}, weekday: {} -> {:?}",
                year,
                month,
                weekday,
                expected
            );
        }

        let cases = [
            (2024, 3, 0, (2024, 3, 31)),
            (2024, 3, 1, (2024, 3, 25)),
            (1915, 7, 0, (1915, 7, 25)),
            (1915, 7, 6, (1915, 7, 31)),
            (1919, 7, 4, (1919, 7, 31)),
            (1919, 7, 0, (1919, 7, 27)),
        ];

        for &(year, month, weekday, expected) in &cases {
            test(year, month, weekday, expected);
        }
    }

    #[test]
    fn nth_weekday_rule_for_year() {
        fn test(year: u16, month: u8, nth: u8, weekday: u8, expected: (u16, u8, u8)) {
            let (y, m, d) = expected;
            assert_eq!(
                Rule::NthWeekday(Nu8!(nth), weekday, Nu8!(month)).for_year(Nu16!(year)),
                Date::new_unchecked(y, m, d),
                "year: {}, month: {}, nth: {}, weekday: {} -> {:?}",
                year,
                month,
                nth,
                weekday,
                expected
            );
        }

        let cases = [
            (1919, 7, 1, 0, (1919, 7, 6)),
            (2002, 12, 1, 0, (2002, 12, 1)),
            (2002, 12, 2, 0, (2002, 12, 8)),
            (2002, 12, 3, 6, (2002, 12, 21)),
            (1992, 2, 1, 6, (1992, 2, 1)),
            (1992, 2, 4, 6, (1992, 2, 22)),
        ];

        for &(year, month, nth, weekday, expected) in &cases {
            test(year, month, nth, weekday, expected);
        }
    }

    #[test]
    fn calculate_offsets() {
        let tz_fixed = TZ {
            std: 1234,
            dst: None,
        };
        // A TZ with random-ish DST rules
        let tz = TZ {
            std: 4800,
            dst: Some(DST {
                offset: 9300,
                start: (Rule::LastWeekday(0, Nu8!(3)), 3600 * 4),
                end: (Rule::JulianDayOfYear(Nu16!(281)), DEFAULT_RULE_TIME),
            }),
        };
        // A TZ with DST time rules that are very large, or negative!
        let tz_weirdtime = TZ {
            std: 4800,
            dst: Some(DST {
                offset: 9300,
                start: (Rule::LastWeekday(0, Nu8!(3)), 50 * 3_600),
                end: (Rule::JulianDayOfYear(Nu16!(281)), -2 * 3_600),
            }),
        };
        // A TZ with DST rules that are 00:00:00
        let tz00 = TZ {
            std: 4800,
            dst: Some(DST {
                offset: 9300,
                start: (Rule::LastWeekday(0, Nu8!(3)), 0),
                end: (Rule::JulianDayOfYear(Nu16!(281)), 0),
            }),
        };
        // A TZ with a DST offset smaller than the standard offset (theoretically possible)
        let tz_neg = TZ {
            std: 4800,
            dst: Some(DST {
                offset: 1200,
                start: (Rule::LastWeekday(0, Nu8!(3)), DEFAULT_RULE_TIME),
                end: (Rule::JulianDayOfYear(Nu16!(281)), 4 * 3_600),
            }),
        };
        // start can technically be before end. Behavior isn't defined, but we
        // shouldn't crash
        let tz_inverted = TZ {
            std: 4800,
            dst: Some(DST {
                offset: 7200,
                end: (Rule::LastWeekday(0, Nu8!(3)), DEFAULT_RULE_TIME),
                start: (Rule::JulianDayOfYear(Nu16!(281)), 4 * 3_600),
            }),
        };
        // Some timezones appear to be "always DST", like Africa/Casablanca
        let tz_always_dst = TZ {
            std: 7200,
            dst: Some(DST {
                offset: 3600,
                start: (Rule::DayOfYear(Nu16!(1)), 0),
                end: (Rule::JulianDayOfYear(Nu16!(365)), 23 * 3600),
            }),
        };

        fn to_epoch_s(d: Date, t: Time, offset: Offset) -> EpochSeconds {
            d.unix_days() as EpochSeconds * 86_400 + t.total_seconds() as EpochSeconds
                - offset as EpochSeconds
        }

        fn test(tz: TZ, ymd: (u16, u8, u8), hms: (u8, u8, u8), expected: OffsetResult) {
            let (y, m, d) = ymd;
            let (hour, minute, second) = hms;
            let date = Date::new_unchecked(y, m, d);
            let time = Time {
                hour,
                minute,
                second,
                nanos: 0,
            };
            assert_eq!(
                tz.offset_for_local(date, time),
                expected,
                "{:?} {:?} -> {:?}",
                ymd,
                hms,
                expected
            );
            // Test that the inverse operation (epoch->local) works
            match expected {
                Unambiguous(offset) => {
                    let epoch = to_epoch_s(date, time, offset);
                    assert_eq!(
                        tz.offset_for_instant(epoch),
                        offset,
                        "tz: {:?} date: {}, time: {}, offset: {}, epoch: {}",
                        tz,
                        date,
                        time,
                        offset,
                        epoch
                    );
                }
                Fold(a, b) => {
                    let epoch_a = to_epoch_s(date, time, a);
                    let epoch_b = to_epoch_s(date, time, b);
                    assert_eq!(
                        tz.offset_for_instant(epoch_a),
                        a,
                        "(earlier offset) tz: {:?} date: {}, time: {}, offset: {}, epoch: {}",
                        tz,
                        date,
                        time,
                        a,
                        epoch_a
                    );
                    assert_eq!(
                        tz.offset_for_instant(epoch_b),
                        b,
                        "(later offset) tz: {:?} date: {}, time: {}, offset: {}, epoch: {}",
                        tz,
                        date,
                        time,
                        b,
                        epoch_b
                    );
                }
                Gap(_, _) => {} // Times in a gap aren't reversible
            }
        }

        let cases = [
            // fixed always the same
            (tz_fixed, (2020, 3, 19), (12, 34, 56), Unambiguous(1234)),
            // First second of the year
            (tz, (1990, 1, 1), (0, 0, 0), Unambiguous(4800)),
            // Last second of the year
            (tz, (1990, 12, 31), (23, 59, 59), Unambiguous(4800)),
            // Well before the transition
            (tz, (1990, 3, 13), (12, 34, 56), Unambiguous(4800)),
            // Gap: Before, start, mid, end, after
            (tz, (1990, 3, 25), (3, 59, 59), Unambiguous(4800)),
            (tz, (1990, 3, 25), (4, 0, 0), Gap(9300, 4800)),
            (tz, (1990, 3, 25), (5, 10, 0), Gap(9300, 4800)),
            (tz, (1990, 3, 25), (5, 14, 59), Gap(9300, 4800)),
            (tz, (1990, 3, 25), (5, 15, 0), Unambiguous(9300)),
            // Well after the transition
            (tz, (1990, 6, 26), (8, 0, 0), Unambiguous(9300)),
            // Fold: Before, start, mid, end, after
            (tz, (1990, 10, 8), (0, 44, 59), Unambiguous(9300)),
            (tz, (1990, 10, 8), (0, 45, 0), Fold(9300, 4800)),
            (tz, (1990, 10, 8), (1, 33, 59), Fold(9300, 4800)),
            (tz, (1990, 10, 8), (1, 59, 59), Fold(9300, 4800)),
            (tz, (1990, 10, 8), (2, 0, 0), Unambiguous(4800)),
            // Well after the end of DST
            (tz, (1990, 11, 30), (23, 34, 56), Unambiguous(4800)),
            // time outside 0-24h range is also valid for a rule
            (tz_weirdtime, (1990, 3, 26), (1, 59, 59), Unambiguous(4800)),
            (tz_weirdtime, (1990, 3, 27), (2, 0, 0), Gap(9300, 4800)),
            (tz_weirdtime, (1990, 3, 27), (3, 0, 0), Gap(9300, 4800)),
            (tz_weirdtime, (1990, 3, 27), (3, 14, 59), Gap(9300, 4800)),
            (tz_weirdtime, (1990, 3, 27), (3, 15, 0), Unambiguous(9300)),
            (tz_weirdtime, (1990, 10, 7), (20, 44, 59), Unambiguous(9300)),
            (tz_weirdtime, (1990, 10, 7), (20, 45, 0), Fold(9300, 4800)),
            (tz_weirdtime, (1990, 10, 7), (21, 33, 59), Fold(9300, 4800)),
            (tz_weirdtime, (1990, 10, 7), (21, 59, 59), Fold(9300, 4800)),
            (tz_weirdtime, (1990, 10, 7), (22, 0, 0), Unambiguous(4800)),
            (tz_weirdtime, (1990, 10, 7), (22, 0, 1), Unambiguous(4800)),
            // 00:00:00 is a valid time for a rule
            (tz00, (1990, 3, 24), (23, 59, 59), Unambiguous(4800)),
            (tz00, (1990, 3, 25), (0, 0, 0), Gap(9300, 4800)),
            (tz00, (1990, 3, 25), (1, 0, 0), Gap(9300, 4800)),
            (tz00, (1990, 3, 25), (1, 14, 59), Gap(9300, 4800)),
            (tz00, (1990, 3, 25), (1, 15, 0), Unambiguous(9300)),
            (tz00, (1990, 10, 7), (22, 44, 59), Unambiguous(9300)),
            (tz00, (1990, 10, 7), (22, 45, 0), Fold(9300, 4800)),
            (tz00, (1990, 10, 7), (23, 33, 59), Fold(9300, 4800)),
            (tz00, (1990, 10, 7), (23, 59, 59), Fold(9300, 4800)),
            (tz00, (1990, 10, 8), (0, 0, 0), Unambiguous(4800)),
            (tz00, (1990, 10, 8), (0, 0, 1), Unambiguous(4800)),
            // Negative DST should be handled gracefully. Gap and fold reversed
            // Fold instead of gap
            (tz_neg, (1990, 3, 25), (0, 59, 59), Unambiguous(4800)),
            (tz_neg, (1990, 3, 25), (1, 0, 0), Fold(4800, 1200)),
            (tz_neg, (1990, 3, 25), (1, 33, 59), Fold(4800, 1200)),
            (tz_neg, (1990, 3, 25), (1, 59, 59), Fold(4800, 1200)),
            (tz_neg, (1990, 3, 25), (2, 0, 0), Unambiguous(1200)),
            // Gap instead of fold
            (tz_neg, (1990, 10, 8), (3, 59, 59), Unambiguous(1200)),
            (tz_neg, (1990, 10, 8), (4, 0, 0), Gap(4800, 1200)),
            (tz_neg, (1990, 10, 8), (4, 42, 12), Gap(4800, 1200)),
            (tz_neg, (1990, 10, 8), (4, 59, 59), Gap(4800, 1200)),
            (tz_neg, (1990, 10, 8), (5, 0, 0), Unambiguous(4800)),
            // No crash on inverted rules
            (tz_inverted, (1990, 2, 9), (15, 0, 0), Unambiguous(4800)),
            (tz_inverted, (1990, 10, 8), (3, 59, 0), Unambiguous(4800)),
            (tz_inverted, (1990, 10, 8), (4, 0, 0), Gap(7200, 4800)),
            (tz_inverted, (1990, 8, 13), (15, 0, 0), Unambiguous(4800)),
            (tz_inverted, (1990, 11, 1), (4, 0, 0), Unambiguous(4800)),
            // Always DST
            (tz_always_dst, (1990, 1, 1), (0, 0, 0), Unambiguous(3600)),
            // This is actually incorrect, but ZoneInfo does the same...
            (tz_always_dst, (1992, 12, 31), (23, 0, 0), Gap(7200, 3600)),
        ];

        for &(tz, ymd, hms, expected) in &cases {
            test(tz, ymd, hms, expected);
        }
    }
}
