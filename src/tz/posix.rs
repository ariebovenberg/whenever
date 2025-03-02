/// Functionality for working with POSIX TZ strings
///
/// Resources:
/// - [POSIX TZ strings](https://pubs.opengroup.org/onlinepubs/9699919799/basedefs/V1_chap08.html)
/// - [GNU libc manual](https://www.gnu.org/software/libc/manual/html_node/TZ-Variable.html)
use crate::common::{Month, Offset};
use crate::{SecondOfDay, S_PER_DAY};
use std::cmp::min;
use std::num::{NonZeroU16, NonZeroU8};
use std::ops::RangeInclusive;

const DEFAULT_DST: Offset = 3_600;
pub(crate) type Weekday = u8; // 0 is Sunday, 6 is Saturday
const DEFAULT_TIME: SecondOfDay = 2 * 3_600; // 2:00:00

// OPTIMIZE: maybe we can have three classes: fixed, one-hour DST, and custom DST?
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct TZ {
    std: Offset,
    dst: Option<DST>,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) struct DST {
    offset: Offset,
    start: (Rule, SecondOfDay),
    end: (Rule, SecondOfDay),
}

/// A rule for the date when DST starts or ends
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) enum Rule {
    LastWeekday(Weekday, Month),
    NthWeekday(NonZeroU8, Weekday, Month), // N is 1..=4
    DayOfYear(u16),                        // 0..=365, accounts for leap days
    JulianDayOfYear(NonZeroU16),           // 1..=365, ignores leap days
}

#[allow(dead_code)]
pub fn parse(s: &[u8]) -> Option<TZ> {
    // So that all further parsing functions can assume ASCII input
    if !s.is_ascii() {
        return None;
    }
    let (std, s) = skip_tzname(s).and_then(parse_offset)?;
    // If there's nothing else, it's a fixed offset without DST
    if s.is_empty() {
        return Some(TZ { std, dst: None });
    };
    let s = skip_tzname(s)?;
    // Parse the DST offset. If omitted, the default is 1 hour ahead.
    // After the DST offset, there is a comma before the rules begin.
    let (dst_offset, s) = if s.get(0)? == &b',' {
        (std + DEFAULT_DST, &s[1..])
    } else {
        let (dst, s) = parse_offset(s)?;
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
    debug_assert!(!s.is_empty()); // invariant
    let (sign, s) = match s[0] {
        // POSIX offsets are inverted from how we store them (+ is east of UTC)
        b'-' => (1, &s[1..]),
        b'+' => (-1, &s[1..]),
        _ => (-1, s),
    };
    parse_hms(s).map(|(n, s)| (sign * n as i32, s))
}

/// Parse a `h[h][:mm[:ss]]` string into a total number of seconds (< 24 hours)
fn parse_hms(s: &[u8]) -> Option<(u32, &[u8])> {
    let mut total = 0;
    // Parse the hours (1 or 2 digits)
    let s = match &s[..min(s.len(), 2)] {
        &[h1 @ b'0'..=b'2', h2 @ b'0'..=b'9'] => {
            total = (10 * (h1 - b'0') + (h2 - b'0')) as u32 * 3_600;
            &s[2..]
        }
        &[h @ b'0'..=b'9', ..] => {
            total = (h - b'0') as u32 * 3_600;
            &s[1..]
        }
        _ => None?, // no hours: invalid
    };
    // Parse the minutes (always 2 digits preceded by ':')
    let s = match &s[..min(s.len(), 3)] {
        &[b':', m1 @ b'0'..=b'5', m2 @ b'0'..=b'9'] => {
            total += (10 * (m1 - b'0') + (m2 - b'0')) as u32 * 60;
            &s[3..]
        }
        &[b':', ..] => None?, // minutes must be 2 digits
        _ => return (total < S_PER_DAY as _).then_some((total, s)), // no minutes: we're done parsing
    };
    // Parse the seconds (always 2 digits preceded by ':')
    let s = match &s[..min(s.len(), 3)] {
        &[b':', s1 @ b'0'..=b'5', s2 @ b'0'..=b'9'] => {
            total += (10 * (s1 - b'0') + (s2 - b'0')) as u32;
            &s[3..]
        }
        &[b':', ..] => None?, // seconds must be 2 digits
        _ => s,
    };
    (total < S_PER_DAY as _).then_some((total, s))
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

/// Parse 1-3 digit number up to 365 (inclusive). Zero is allowed.
fn parse_day_of_year(s: &[u8]) -> Option<(u16, &[u8])> {
    fn digit(d: u8) -> u16 {
        (d - b'0') as u16
    }
    // Match arms for 1, 2, and 3 digits
    let (raw_value, s) = match s {
        &[d1 @ b'0'..=b'9', d2 @ b'0'..=b'9', d3 @ b'0'..=b'9', ..] => {
            (100 * digit(d1) + 10 * digit(d2) + digit(d3) as u16, &s[3..])
        }
        &[d1 @ b'0'..=b'9', d2 @ b'0'..=b'9', ..] => (10 * digit(d1) + digit(d2), &s[2..]),
        &[d @ b'0'..=b'9', ..] => (digit(d), &s[1..]),
        _ => None?,
    };
    (raw_value <= 365).then_some((raw_value, s))
}

fn parse_rule(s: &[u8]) -> Option<((Rule, SecondOfDay), &[u8])> {
    let (rule, s) = match s.get(0)? {
        b'M' => parse_weekday_rule(&s[1..]),
        b'J' => {
            let (day, rest) = parse_day_of_year(&s[1..])?;
            Some((Rule::JulianDayOfYear(NonZeroU16::new(day)?), rest))
        }
        _ => parse_day_of_year(s).map(|(n, s)| (Rule::DayOfYear(n), s)),
    }?;
    let (time, s) = if let Some(b'/') = s.get(0) {
        parse_hms(&s[1..])?
    } else {
        (DEFAULT_TIME, s)
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

    #[test]
    fn test_invalid_start() {
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
    fn test_fixed_offset() {
        // Whole hours
        assert_eq!(parse(b"UTC0").unwrap(), TZ { std: 0, dst: None });
        assert_eq!(
            parse(b"FOO1").unwrap(),
            TZ {
                std: -3600,
                dst: None
            }
        );
        assert_eq!(
            parse(b"FOO12").unwrap(),
            TZ {
                std: -3600 * 12,
                dst: None
            }
        );
        assert_eq!(
            parse(b"FOO-9").unwrap(),
            TZ {
                std: 3600 * 9,
                dst: None
            }
        );
        assert_eq!(parse(b"FOO+0").unwrap(), TZ { std: 0, dst: None });
        assert_eq!(
            parse(b"FOO-22").unwrap(),
            TZ {
                std: 3600 * 22,
                dst: None
            }
        );
        assert_eq!(
            parse(b"FOO-02").unwrap(),
            TZ {
                std: 3600 * 2,
                dst: None
            }
        );
        assert_eq!(
            parse(b"FOO+02").unwrap(),
            TZ {
                std: -3600 * 2,
                dst: None
            }
        );
        assert_eq!(
            parse(b"FOO+19").unwrap(),
            TZ {
                std: -3600 * 19,
                dst: None
            }
        );
        assert_eq!(
            parse(b"<+13>-13").unwrap(),
            TZ {
                std: 3600 * 13,
                dst: None
            }
        );
        // Minutes
        assert_eq!(
            parse(b"FOO+01:30").unwrap(),
            TZ {
                std: -3600 - 30 * 60,
                dst: None
            }
        );
        assert_eq!(
            parse(b"FOO-01:30:59").unwrap(),
            TZ {
                std: 3600 + 30 * 60 + 59,
                dst: None
            }
        );
        assert_eq!(
            parse(b"FOO-23:59:59").unwrap(),
            TZ {
                std: 86_399,
                dst: None
            }
        );
        assert_eq!(
            parse(b"FOO+23:59:59").unwrap(),
            TZ {
                std: -86_399,
                dst: None
            }
        );
    }

    #[test]
    fn test_fixed_offset_invalid() {
        // Invalid components
        assert_eq!(parse(b"FOO+01:"), None);
        assert_eq!(parse(b"FOO+01:9:03"), None);
        assert_eq!(parse(b"FOO+01:60:03"), None);
        assert_eq!(parse(b"FOO-01:59:60"), None);
        assert_eq!(parse(b"FOO-01:59:"), None);
        assert_eq!(parse(b"FOO-01:59:4"), None);

        // offset too large
        assert_eq!(parse(b"FOO24"), None);
        assert_eq!(parse(b"FOO+24"), None);
        assert_eq!(parse(b"FOO-24"), None);
        assert_eq!(parse(b"FOO-27:00"), None);
        assert_eq!(parse(b"FOO+27:00"), None);
        assert_eq!(parse(b"FOO-25:45:05"), None);
        assert_eq!(parse(b"FOO+27:45:09"), None);

        // Invalid trailing data
        assert_eq!(parse(b"FOO+01:30M"), None);
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
    fn test_with_dst() {
        // Implicit DST offset
        assert_eq!(
            parse(b"FOO-1FOOS,M3.5.0,M10.4.0").unwrap(),
            TZ {
                std: 3600,
                dst: Some(DST {
                    offset: 7200,
                    start: (Rule::LastWeekday(0, Nu8!(3)), DEFAULT_TIME),
                    end: (Rule::NthWeekday(Nu8!(4), 0, Nu8!(10)), DEFAULT_TIME)
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
                    start: (Rule::LastWeekday(0, Nu8!(3)), DEFAULT_TIME),
                    end: (Rule::NthWeekday(Nu8!(2), 0, Nu8!(10)), DEFAULT_TIME)
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
                    end: (Rule::NthWeekday(Nu8!(2), 0, Nu8!(10)), DEFAULT_TIME)
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
                    start: (Rule::DayOfYear(23), 8 * 3_600 + 34 * 60 + 1),
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
                    start: (Rule::DayOfYear(0), 8 * 3_600 + 34 * 60 + 1),
                    end: (Rule::JulianDayOfYear(Nu16!(1)), 0)
                })
            }
        );
    }

    #[test]
    fn test_with_dst_invalid() {
        // Unfinished rule
        assert_eq!(parse(b"FOO+01:30,J"), None);
        assert_eq!(parse(b"FOO+01:30,"), None);
        assert_eq!(parse(b"FOO+01:30,M3.2."), None);

        // Invalid month rule
        assert_eq!(parse(b"FOO+01:30,M13.2.1,M1.1.1"), None);
        assert_eq!(parse(b"FOO+01:30,M12.6.1,M1.1.1"), None);
        assert_eq!(parse(b"FOO+01:30,M12.2.7,M1.1.1"), None);
        assert_eq!(parse(b"FOO+01:30,M12.0.2,M1.1.1"), None);
        // Invalid day of year
        assert_eq!(parse(b"FOO+01:30,J366,M1.1.1"), None);
        assert_eq!(parse(b"FOO+01:30,J0,M1.1.1"), None);
        assert_eq!(parse(b"FOO+01:30,-1,M1.1.1"), None);
        assert_eq!(parse(b"FOO+01:30,366,M1.1.1"), None);
        // Trailing data
        assert_eq!(parse(b"FOO+01:30,M3.2.1,M1.1.1,"), None);
        assert_eq!(parse(b"FOO+01:30,M3.2.1,M1.1.1/0/1"), None);
    }
}
