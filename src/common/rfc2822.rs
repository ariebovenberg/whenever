use crate::{
    common::math::*,
    common::parse::Scan,
    common::*,
    date::{extract_2_digits, extract_year, Date},
    instant::Instant,
    offset_datetime::OffsetDateTime,
    plain_datetime::DateTime,
    time::Time,
};

const TEMPLATE: [u8; 31] = *b"DDD, 00 MMM 0000 00:00:00 +0000";
const TEMPLATE_GMT: [u8; 29] = *b"DDD, 00 MMM 0000 00:00:00 GMT";

pub(crate) fn write(odt: OffsetDateTime) -> [u8; 31] {
    let OffsetDateTime {
        date,
        time:
            Time {
                hour,
                minute,
                second,
                ..
            },
        offset,
    } = odt;
    let Date { year, month, day } = date;

    // We start with a blank buffer (all spaces) and write into it
    let mut buf = TEMPLATE;
    buf[..3].copy_from_slice(WEEKDAY_NAMES[date.day_of_week() as usize - 1]);
    write_2_digits(day, &mut buf[5..7]);
    buf[8..11].copy_from_slice(MONTH_NAMES[month as usize - 1]);
    write_4_digits(year.get(), &mut buf[12..16]);
    write_2_digits(hour, &mut buf[17..19]);
    write_2_digits(minute, &mut buf[20..22]);
    write_2_digits(second, &mut buf[23..25]);
    buf[26] = if offset.get() >= 0 { b'+' } else { b'-' };
    let offset_abs = offset.get().abs();
    write_2_digits((offset_abs / 3600) as u8, &mut buf[27..29]);
    write_2_digits(((offset_abs % 3600) / 60) as u8, &mut buf[29..]);
    buf
}

pub(crate) fn write_gmt(i: Instant) -> [u8; 29] {
    let DateTime {
        date,
        time:
            Time {
                hour,
                minute,
                second,
                ..
            },
    } = i.to_datetime();
    let Date { year, month, day } = date;

    // We start with a blank buffer (all spaces) and write into it
    let mut buf = TEMPLATE_GMT;
    buf[..3].copy_from_slice(WEEKDAY_NAMES[date.day_of_week() as usize - 1]);
    write_2_digits(day, &mut buf[5..7]);
    buf[8..11].copy_from_slice(MONTH_NAMES[month as usize - 1]);
    write_4_digits(year.get(), &mut buf[12..16]);
    write_2_digits(hour, &mut buf[17..19]);
    write_2_digits(minute, &mut buf[20..22]);
    write_2_digits(second, &mut buf[23..25]);
    buf
}

const WEEKDAY_NAMES: [&[u8]; 7] = [b"Mon", b"Tue", b"Wed", b"Thu", b"Fri", b"Sat", b"Sun"];
const MONTH_NAMES: [&[u8]; 12] = [
    b"Jan", b"Feb", b"Mar", b"Apr", b"May", b"Jun", b"Jul", b"Aug", b"Sep", b"Oct", b"Nov", b"Dec",
];

fn write_2_digits(n: u8, buf: &mut [u8]) {
    buf[0] = n / 10 + b'0';
    buf[1] = n % 10 + b'0';
}

fn write_4_digits(n: u16, buf: &mut [u8]) {
    buf[0] = (n / 1000) as u8 + b'0';
    buf[1] = (n / 100 % 10) as u8 + b'0';
    buf[2] = (n / 10 % 10) as u8 + b'0';
    buf[3] = (n % 10) as u8 + b'0';
}

pub(crate) fn parse(s: &[u8]) -> Option<(Date, Time, Offset)> {
    let mut scan = Scan::new(s);
    scan.ascii_whitespace();

    let weekday_opt = match scan.peek()? {
        c if c.is_ascii_alphabetic() => Some(parse_weekday(&mut scan)?),
        _ => None,
    };

    // Parse the date
    let day = scan.up_to_2_digits()?;
    scan.ascii_whitespace().then_some(())?;
    let month = scan.take(3).and_then(|month_str| {
        Some(if month_str.eq_ignore_ascii_case(b"Jan") {
            Month::January
        } else if month_str.eq_ignore_ascii_case(b"Feb") {
            Month::February
        } else if month_str.eq_ignore_ascii_case(b"Mar") {
            Month::March
        } else if month_str.eq_ignore_ascii_case(b"Apr") {
            Month::April
        } else if month_str.eq_ignore_ascii_case(b"May") {
            Month::May
        } else if month_str.eq_ignore_ascii_case(b"Jun") {
            Month::June
        } else if month_str.eq_ignore_ascii_case(b"Jul") {
            Month::July
        } else if month_str.eq_ignore_ascii_case(b"Aug") {
            Month::August
        } else if month_str.eq_ignore_ascii_case(b"Sep") {
            Month::September
        } else if month_str.eq_ignore_ascii_case(b"Oct") {
            Month::October
        } else if month_str.eq_ignore_ascii_case(b"Nov") {
            Month::November
        } else if month_str.eq_ignore_ascii_case(b"Dec") {
            Month::December
        } else {
            None?
        })
    })?;
    scan.ascii_whitespace().then_some(())?;
    let year = scan
        .take_until(Scan::is_whitespace)
        .and_then(|y_str| match y_str.len() {
            4 => extract_year(y_str, 0),
            2 => extract_2_digits(y_str, 0).map(|y| {
                if y < 50 {
                    Year::new_unchecked(2000 + y as u16)
                } else {
                    Year::new_unchecked(1900 + y as u16)
                }
            }),
            3 => Some(Year::new_unchecked(
                1900 + (extract_digit(y_str, 0)? as u16) * 100
                    + (extract_digit(y_str, 1)? as u16) * 10
                    + (extract_digit(y_str, 2)? as u16),
            )),
            _ => None,
        })?;
    scan.ascii_whitespace();
    let date = Date::new(year, month, day)?;
    if let Some(weekday) = weekday_opt {
        if date.day_of_week() != weekday {
            return None;
        }
    }

    // Parse the time
    let hour = scan.digits00_23()?;
    scan.ascii_whitespace();
    scan.expect(b':')?;
    scan.ascii_whitespace();
    let minute = scan.digits00_59()?;
    let whitespace_after_mins = scan.ascii_whitespace();
    let second = match scan.peek()? {
        b':' => {
            scan.skip(1).ascii_whitespace();
            let val = scan.digits00_59()?;
            // Whitespace after seconds is required!
            scan.ascii_whitespace().then_some(())?;
            val
        }
        _ if whitespace_after_mins => 0,
        _ => None?,
    };

    let time = Time {
        hour,
        minute,
        second,
        subsec: SubSecNanos::MIN,
    };

    // Parse the offset
    let offset = Offset::new_unchecked(match scan.peek()? {
        b'+' => scan.skip(1).digits00_23()? as i32 * 3600 + scan.digits00_59()? as i32 * 60,
        b'-' => -(scan.skip(1).digits00_23()? as i32 * 3600 + scan.digits00_59()? as i32 * 60),
        _ => {
            let tz = match scan.take_until(|b| !b.is_ascii_alphabetic()) {
                Some(tz) => tz,
                None => scan.drain(),
            };
            if tz.is_empty() {
                return None;
            }
            (if tz.eq_ignore_ascii_case(b"GMT") {
                0
            } else if tz.eq_ignore_ascii_case(b"UT") {
                0
            } else if tz.eq_ignore_ascii_case(b"EST") {
                -5
            } else if tz.eq_ignore_ascii_case(b"EDT") {
                -4
            } else if tz.eq_ignore_ascii_case(b"CST") {
                -6
            } else if tz.eq_ignore_ascii_case(b"CDT") {
                -5
            } else if tz.eq_ignore_ascii_case(b"MST") {
                -7
            } else if tz.eq_ignore_ascii_case(b"MDT") {
                -6
            } else if tz.eq_ignore_ascii_case(b"PST") {
                -8
            } else if tz.eq_ignore_ascii_case(b"PDT") {
                -7
            } else {
                0
            }) * 3_600
        }
    });

    scan.ascii_whitespace();
    scan.is_done().then_some((date, time, offset))
}

// TODO: abstract out other functions
fn parse_weekday(s: &mut Scan) -> Option<Weekday> {
    s.take(3)
        .and_then(|day_str| {
            Some(if day_str.eq_ignore_ascii_case(b"Mon") {
                Weekday::Monday
            } else if day_str.eq_ignore_ascii_case(b"Tue") {
                Weekday::Tuesday
            } else if day_str.eq_ignore_ascii_case(b"Wed") {
                Weekday::Wednesday
            } else if day_str.eq_ignore_ascii_case(b"Thu") {
                Weekday::Thursday
            } else if day_str.eq_ignore_ascii_case(b"Fri") {
                Weekday::Friday
            } else if day_str.eq_ignore_ascii_case(b"Sat") {
                Weekday::Saturday
            } else if day_str.eq_ignore_ascii_case(b"Sun") {
                Weekday::Sunday
            } else {
                None?
            })
        })
        .and_then(|day| {
            s.ascii_whitespace();
            s.expect(b',')?;
            s.ascii_whitespace();
            Some(day)
        })
}
