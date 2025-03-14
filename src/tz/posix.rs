/// Functionality for working with POSIX TZ strings
///
/// Resources:
/// - [POSIX TZ strings](https://pubs.opengroup.org/onlinepubs/9699919799/basedefs/V1_chap08.html)
/// - [GNU libc manual](https://www.gnu.org/software/libc/manual/html_node/TZ-Variable.html)
use crate::common::parse::Scan;
use crate::common::{Ambiguity, Month, OffsetDelta, OffsetS, Year};
use crate::date::{days_before_year, days_in_month, is_leap, Date};
use crate::EpochSecs;
use std::num::{NonZeroU16, NonZeroU8};

const DEFAULT_DST: OffsetDelta = OffsetDelta::new_unchecked(3_600);
pub(crate) type Weekday = u8; // 0 is Sunday, 6 is Saturday
                              // RFC 9636: the transition time may range from -167 to 167 hours! (not just 24)
pub(crate) type TransitionTime = i32;
const DEFAULT_RULE_TIME: i32 = 2 * 3_600; // 2 AM

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct TZ {
    std: OffsetS,
    dst: Option<Dst>,
    // We don't store the TZ names since we don't use them (yet)
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) struct Dst {
    offset: OffsetS,
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
    pub(crate) fn offset_for_instant(&self, epoch: EpochSecs) -> OffsetS {
        match self.dst {
            None => self.std, // No DST rule means a fixed offset
            Some(Dst {
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
                let year = epoch
                    .saturating_offset(self.std)
                    .date()
                    .year
                    .try_into()
                    .unwrap();
                let dst_start = start_rule
                    .for_year(year)
                    .epoch()
                    .saturating_add_i32(start_time - self.std.get());
                // fast path: avoid calculating the end time at all
                if epoch < dst_start {
                    self.std
                } else {
                    let dst_end = end_rule
                        .for_year(year)
                        .epoch()
                        .saturating_add_i32(end_time - dst_offset.get());
                    if epoch < dst_end {
                        dst_offset
                    } else {
                        self.std
                    }
                }
            }
        }
    }

    /// Get the offset for a local time, given as the number of seconds since the Unix epoch.
    pub(crate) fn ambiguity_for_local(&self, t: EpochSecs) -> Ambiguity {
        match self.dst {
            None => Ambiguity::Unambiguous(self.std.get()), // No DST
            Some(Dst {
                // NOTE: There's nothing preventing end from being before start,
                // but this shouldn't happen in practice. We don't crash, at least.
                start: (start_rule, start_time),
                end: (end_rule, end_time),
                offset,
            }) => {
                let year = t.date().year.try_into().unwrap();
                let dst_start = start_rule
                    .for_year(year)
                    .epoch()
                    .saturating_add_i32(start_time);
                let dst_shift = offset.get() - self.std.get();
                // In rare cases, the dst shift is negative.
                // We handle the common case first.
                if dst_shift >= 0 {
                    if t < dst_start {
                        Ambiguity::Unambiguous(self.std.get())
                    } else if t < dst_start.saturating_add_i32(dst_shift) {
                        Ambiguity::Gap(offset.get(), self.std.get())
                    } else {
                        let dst_end = end_rule.for_year(year).epoch().saturating_add_i32(end_time);
                        if t < dst_end.saturating_add_i32(-dst_shift) {
                            Ambiguity::Unambiguous(offset.get())
                        } else if t < dst_end {
                            Ambiguity::Fold(offset.get(), self.std.get())
                        } else {
                            Ambiguity::Unambiguous(self.std.get())
                        }
                    }
                // These further branches mirror the above, but with the
                // roles of standard and DST time reversed.
                } else if t < dst_start.saturating_add_i32(dst_shift) {
                    Ambiguity::Unambiguous(self.std.get())
                } else if t < dst_start {
                    Ambiguity::Fold(self.std.get(), offset.get())
                } else {
                    let dst_end = end_rule.for_year(year).epoch().saturating_add_i32(end_time);
                    if t < dst_end {
                        Ambiguity::Unambiguous(offset.get())
                    } else if t < dst_end.saturating_add_i32(-dst_shift) {
                        Ambiguity::Gap(self.std.get(), offset.get())
                    } else {
                        Ambiguity::Unambiguous(self.std.get())
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
    fn for_year(&self, y: Year) -> Date {
        match *self {
            // The 366th day will blow up for non-leap years,
            // It's unlikely that a TZ string would specify this,
            // so we'll just clamp it to the last day of the year.
            Rule::DayOfYear(d) => Date::from_ord_unchecked(
                days_before_year(y.into())
                    + (d.get().clamp(0, 365 + is_leap(y.get()) as u16) as u32),
            ),

            Rule::JulianDayOfYear(d) => {
                let doy = d.get() as u32 + (is_leap(y.get()) && d.get() > 59) as u32;
                Date::from_ord_unchecked(days_before_year(y.into()) + doy)
            }
            Self::LastWeekday(w, m) => {
                // Try the last day of the month, and adjust from there
                let day_last =
                    Date::new_unchecked(y.get(), m.get(), days_in_month(y.get(), m.get()));
                Date {
                    day: day_last.day - (weekday(day_last) + 7 - w) % 7,
                    ..day_last
                }
            }
            Self::NthWeekday(n, w, m) => {
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

pub fn parse(s: &[u8]) -> Option<TZ> {
    let mut scan = Scan::new(s);
    skip_tzname(&mut scan)?;
    let std = parse_offset(&mut scan)?;

    // If there's nothing else, it's a fixed offset without DST
    if scan.is_done() {
        return Some(TZ { std, dst: None });
    };
    skip_tzname(&mut scan)?;

    let dst_offset = match scan.peek()? {
        // If the offset is omitted, the default is 1 hour ahead
        b',' => {
            scan.take_unchecked(1);
            // It's theoretically possible for the DST shift to
            // bump the offset to over 24 hours. We reject these cases.
            std.shift(DEFAULT_DST)?
        }
        // Otherwise, parse the offset
        _ => {
            let offset = parse_offset(&mut scan)?;
            scan.expect(b',')?;
            offset
        }
    };

    // Expect two rules separated by a comma
    let start = parse_rule(&mut scan)?;
    scan.expect(b',')?;
    let end = parse_rule(&mut scan)?;

    // No content should remain after parsing
    scan.is_done().then_some(TZ {
        std,
        dst: Some(Dst {
            offset: dst_offset,
            start,
            end,
        }),
    })
}

/// Skip the TZ name and return the remaining slice,
/// which is guaranteed to be non-empty.
fn skip_tzname(s: &mut Scan) -> Option<()> {
    // name is at least 3 characters long and offset is at least 1 char
    // Note also that in Tzif files, TZ names are limited to 6 characters.
    // This might be useful in the future for optimization
    let tzname = match s.peek() {
        Some(b'<') => {
            let name = s.take_until_inclusive(|c| c == b'>')?;
            &name[1..name.len() - 1]
        }
        _ => s.take_until(|c| matches!(c, b'+' | b'-' | b',' | b'0'..=b'9'))?,
    };
    tzname.is_ascii().then_some(())
}

/// Parse an offset like `[+|-]h[h][:mm[:ss]]`
fn parse_offset(s: &mut Scan) -> Option<OffsetS> {
    parse_hms(s, OffsetS::MAX.get())
        // POSIX offsets are inverted from how we store them
        .map(|s| OffsetS::new_unchecked(-s))
}

/// Parse a `h[hh][:mm[:ss]]` string into a total number of seconds
fn parse_hms(s: &mut Scan, max: i32) -> Option<i32> {
    let sign = s
        .transform(|c| match c {
            b'+' => Some(1),
            b'-' => Some(-1),
            _ => None,
        })
        .unwrap_or(1);
    let mut total = 0;

    // parse the hours
    let hrs = if max > 99 * 3_600 {
        s.up_to_3_digits()? as i32
    } else {
        s.up_to_2_digits()? as i32
    };
    total += hrs * 3_600;

    if let Some(true) = s.advance_on(b':') {
        total += s.digits00_59()? as i32 * 60;
        if let Some(true) = s.advance_on(b':') {
            total += s.digits00_59()? as i32;
        }
    }
    (total <= max).then_some(total * sign)
}

/// Parse `m[m].w.d` string as part of a DST start/end rule
fn parse_weekday_rule(scan: &mut Scan) -> Option<Rule> {
    // Handle the variable length of months
    let m = scan
        .up_to_2_digits()
        .filter(|&m| m <= 12)
        .and_then(NonZeroU8::new)?;
    scan.expect(b'.')?;
    let w: NonZeroU8 = scan.digit_ranged(b'1'..=b'5')?.try_into().unwrap(); // safe >0 unwrap
    scan.expect(b'.')?;
    let d = scan.digit_ranged(b'0'..=b'6')?;

    // A "fifth" occurrence of a weekday doesn't always occur.
    // Interpret it as the last weekday, according to the standard.
    Some(if w.get() == 5 {
        Rule::LastWeekday(d, m)
    } else {
        Rule::NthWeekday(w, d, m)
    })
}

fn parse_rule(scan: &mut Scan) -> Option<(Rule, TransitionTime)> {
    let rule = match scan.peek()? {
        b'M' => {
            scan.next();
            parse_weekday_rule(scan)
        }
        b'J' => {
            scan.next();
            NonZeroU16::new(scan.up_to_3_digits()?)
                .filter(|&d| d.get() <= 365)
                .map(Rule::JulianDayOfYear)
        }
        _ => NonZeroU16::new(scan.up_to_3_digits()? + 1)
            .filter(|&d| d.get() <= 366)
            .map(Rule::DayOfYear),
    }?;

    let time = scan
        .expect(b'/')
        .and_then(|_| parse_hms(scan, 167 * 3_600))
        .unwrap_or(DEFAULT_RULE_TIME);
    Some((rule, time))
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::common::Ambiguity::*;
    use crate::time::Time;

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
        assert_eq!(parse(b"<FOO>"), None);
        assert_eq!(parse(b"<FOO>>-3"), None);
    }

    #[test]
    fn fixed_offset() {
        fn test(s: &[u8], expected: i32) {
            assert_eq!(
                parse(s).unwrap(),
                TZ {
                    std: expected.try_into().unwrap(),
                    dst: None
                },
                "{:?} -> {}",
                unsafe { std::str::from_utf8_unchecked(s) },
                expected
            );
        }

        let cases: &[(&[u8], i32)] = &[
            (b"FOO1", -3600),
            (b"FOOS0", 0),
            (b"FOO+01", -3600),
            (b"FOO+01:30", -3600 - 30 * 60),
            (b"FOO+01:30:59", -3600 - 30 * 60 - 59),
            (b"FOOM+23:59:59", -86_399),
            (b"FOOS-23:59:59", 86_399),
            (b"FOOBLA-23:59", 23 * 3600 + 59 * 60),
            (b"FOO-23", 23 * 3600),
            (b"FOO-01", 3600),
            (b"FOO-01:30", 3600 + 30 * 60),
            (b"FOO-01:30:59", 3600 + 30 * 60 + 59),
            (b"FOO+23:59:59", -86_399),
            (b"FOO+23:59", -23 * 3600 - 59 * 60),
            (b"FOO+23", -23 * 3600),
            (b"<FOO>-3", 3 * 3600),
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
                std: 3600.try_into().unwrap(),
                dst: Some(Dst {
                    offset: 7200.try_into().unwrap(),
                    start: (Rule::LastWeekday(0, Nu8!(3)), DEFAULT_RULE_TIME),
                    end: (Rule::NthWeekday(Nu8!(4), 0, Nu8!(10)), DEFAULT_RULE_TIME)
                })
            }
        );
        // Explicit DST offset
        assert_eq!(
            parse(b"FOO+1FOOS2:30,M3.5.0,M10.2.0").unwrap(),
            TZ {
                std: (-3600).try_into().unwrap(),
                dst: Some(Dst {
                    offset: (-3600 * 2 - 30 * 60).try_into().unwrap(),
                    start: (Rule::LastWeekday(0, Nu8!(3)), DEFAULT_RULE_TIME),
                    end: (Rule::NthWeekday(Nu8!(2), 0, Nu8!(10)), DEFAULT_RULE_TIME)
                })
            }
        );
        // Explicit time, weekday rule
        assert_eq!(
            parse(b"FOO+1FOOS2:30,M3.5.0/8,M10.2.0").unwrap(),
            TZ {
                std: (-3600).try_into().unwrap(),
                dst: Some(Dst {
                    offset: (-3600 * 2 - 30 * 60).try_into().unwrap(),
                    start: (Rule::LastWeekday(0, Nu8!(3)), 8 * 3_600),
                    end: (Rule::NthWeekday(Nu8!(2), 0, Nu8!(10)), DEFAULT_RULE_TIME)
                })
            }
        );
        // Explicit time, Julian day rule
        assert_eq!(
            parse(b"FOO+1FOOS2:30,J023/8:34:01,M10.2.0/03").unwrap(),
            TZ {
                std: (-3600).try_into().unwrap(),
                dst: Some(Dst {
                    offset: (-3600 * 2 - 30 * 60).try_into().unwrap(),
                    start: (Rule::JulianDayOfYear(Nu16!(23)), 8 * 3_600 + 34 * 60 + 1),
                    end: (Rule::NthWeekday(Nu8!(2), 0, Nu8!(10)), 3 * 3_600)
                })
            }
        );
        // Explicit time, day-of-year rule
        assert_eq!(
            parse(b"FOO+1FOOS2:30,023/8:34:01,J1/0").unwrap(),
            TZ {
                std: (-3600).try_into().unwrap(),
                dst: Some(Dst {
                    offset: (-3600 * 2 - 30 * 60).try_into().unwrap(),
                    start: (Rule::DayOfYear(Nu16!(24)), 8 * 3_600 + 34 * 60 + 1),
                    end: (Rule::JulianDayOfYear(Nu16!(1)), 0)
                })
            }
        );
        // Explicit time, zeroth day of year
        assert_eq!(
            parse(b"FOO+1FOOS2:30,00/8:34:01,J1/0").unwrap(),
            TZ {
                std: (-3600).try_into().unwrap(),
                dst: Some(Dst {
                    offset: (-3600 * 2 - 30 * 60).try_into().unwrap(),
                    start: (Rule::DayOfYear(Nu16!(1)), 8 * 3_600 + 34 * 60 + 1),
                    end: (Rule::JulianDayOfYear(Nu16!(1)), 0)
                })
            }
        );
        // 24:00:00 is a valid time for a rule
        assert_eq!(
            parse(b"FOO+2FOOS+1,M3.5.0/24,M10.2.0").unwrap(),
            TZ {
                std: (-7200).try_into().unwrap(),
                dst: Some(Dst {
                    offset: (-3600).try_into().unwrap(),
                    start: (Rule::LastWeekday(0, Nu8!(3)), 86_400),
                    end: (Rule::NthWeekday(Nu8!(2), 0, Nu8!(10)), DEFAULT_RULE_TIME)
                })
            }
        );
        // Anything between -167 and 167 hours is also valid!
        assert_eq!(
            parse(b"FOO+2FOOS+1,M3.5.0/-89:02,M10.2.0/100").unwrap(),
            TZ {
                std: (-7200).try_into().unwrap(),
                dst: Some(Dst {
                    offset: (-3600).try_into().unwrap(),
                    start: (Rule::LastWeekday(0, Nu8!(3)), -89 * 3_600 - 2 * 60),
                    end: (Rule::NthWeekday(Nu8!(2), 0, Nu8!(10)), 100 * 3_600)
                })
            }
        );
    }

    #[test]
    fn with_dst_invalid() {
        fn test(s: &[u8]) {
            assert_eq!(parse(s), None, "parse {:?}", unsafe {
                std::str::from_utf8_unchecked(s)
            });
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
            std: 1234.try_into().unwrap(),
            dst: None,
        };
        // A TZ with random-ish DST rules
        let tz = TZ {
            std: 4800.try_into().unwrap(),
            dst: Some(Dst {
                offset: 9300.try_into().unwrap(),
                start: (Rule::LastWeekday(0, Nu8!(3)), 3600 * 4),
                end: (Rule::JulianDayOfYear(Nu16!(281)), DEFAULT_RULE_TIME),
            }),
        };
        // A TZ with DST time rules that are very large, or negative!
        let tz_weirdtime = TZ {
            std: 4800.try_into().unwrap(),
            dst: Some(Dst {
                offset: 9300.try_into().unwrap(),
                start: (Rule::LastWeekday(0, Nu8!(3)), 50 * 3_600),
                end: (Rule::JulianDayOfYear(Nu16!(281)), -2 * 3_600),
            }),
        };
        // A TZ with DST rules that are 00:00:00
        let tz00 = TZ {
            std: 4800.try_into().unwrap(),
            dst: Some(Dst {
                offset: 9300.try_into().unwrap(),
                start: (Rule::LastWeekday(0, Nu8!(3)), 0),
                end: (Rule::JulianDayOfYear(Nu16!(281)), 0),
            }),
        };
        // A TZ with a DST offset smaller than the standard offset (theoretically possible)
        let tz_neg = TZ {
            std: 4800.try_into().unwrap(),
            dst: Some(Dst {
                offset: 1200.try_into().unwrap(),
                start: (Rule::LastWeekday(0, Nu8!(3)), DEFAULT_RULE_TIME),
                end: (Rule::JulianDayOfYear(Nu16!(281)), 4 * 3_600),
            }),
        };
        // start can technically be before end. Behavior isn't defined, but we
        // shouldn't crash
        let tz_inverted = TZ {
            std: 4800.try_into().unwrap(),
            dst: Some(Dst {
                offset: 7200.try_into().unwrap(),
                end: (Rule::LastWeekday(0, Nu8!(3)), DEFAULT_RULE_TIME),
                start: (Rule::JulianDayOfYear(Nu16!(281)), 4 * 3_600),
            }),
        };
        // Some timezones appear to be "always DST", like Africa/Casablanca
        let tz_always_dst = TZ {
            std: 7200.try_into().unwrap(),
            dst: Some(Dst {
                offset: 3600.try_into().unwrap(),
                start: (Rule::DayOfYear(Nu16!(1)), 0),
                end: (Rule::JulianDayOfYear(Nu16!(365)), 23 * 3600),
            }),
        };

        fn to_epoch_s(d: Date, t: Time, offset: i32) -> EpochSecs {
            EpochSecs::new(d.timestamp_at(t))
                .unwrap()
                .offset(OffsetS::new(-offset).unwrap())
                .unwrap()
        }

        fn test(tz: TZ, ymd: (u16, u8, u8), hms: (u8, u8, u8), expected: Ambiguity) {
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
                tz.ambiguity_for_local(to_epoch_s(date, time, 0)),
                expected,
                "{:?} {:?} -> {:?} (tz: {:?})",
                ymd,
                hms,
                expected,
                tz
            );
            // Test that the inverse operation (epoch->local) works
            match expected {
                Unambiguous(offset) => {
                    let epoch = to_epoch_s(date, time, offset);
                    assert_eq!(
                        tz.offset_for_instant(epoch),
                        OffsetS::new(offset).unwrap(),
                        "tz: {:?} date: {}, time: {}, offset: {}, {:?}",
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
                        OffsetS::new(a).unwrap(),
                        "(earlier offset) tz: {:?} date: {}, time: {}, offset: {}, {:?}",
                        tz,
                        date,
                        time,
                        a,
                        epoch_a
                    );
                    assert_eq!(
                        tz.offset_for_instant(epoch_b),
                        OffsetS::new(b).unwrap(),
                        "(later offset) tz: {:?} date: {}, time: {}, offset: {}, {:?}",
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

        // At the MIN/MAX epoch boundaries
        assert!(tz.offset_for_instant(EpochSecs::MAX) == OffsetS::new(4800).unwrap());
    }
}
