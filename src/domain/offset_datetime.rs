use super::{
    date::Date,
    instant::Instant,
    plain_datetime::PlainDateTime,
    scalar::{Offset, Sign},
    time::Time,
};
use crate::{common::parse::Scan, tz::tzif::is_valid_key};
use std::fmt;

/// A date and time with a fixed offset from UTC.
/// Invariant: the instant represented by the date and time is always within range.
#[derive(Debug, Eq, PartialEq, Copy, Clone)]
pub(crate) struct OffsetDateTime {
    pub(crate) date: Date,
    pub(crate) time: Time,
    pub(crate) offset: Offset,
}

impl OffsetDateTime {
    pub(crate) const fn new_unchecked(date: Date, time: Time, offset: Offset) -> Self {
        Self { date, time, offset }
    }

    pub(crate) fn new(date: Date, time: Time, offset: Offset) -> Option<Self> {
        date.at(time).local_seconds().to_epoch(offset)?;
        Some(Self { date, time, offset })
    }

    pub(crate) fn to_instant(self) -> Instant {
        self.to_plain()
            .assume_utc()
            .shift_by_offset(-self.offset)
            .unwrap()
    }

    pub(crate) const fn to_plain(self) -> PlainDateTime {
        PlainDateTime {
            date: self.date,
            time: self.time,
        }
    }

    pub(crate) fn parse(s: &[u8]) -> Option<Self> {
        Scan::new(s).parse_all(Self::read_iso)
    }

    pub(crate) fn read_iso(s: &mut Scan) -> Option<Self> {
        PlainDateTime::read_iso(s)?
            .with_offset(Offset::read_iso(s)?)
            .and_then(|datetime| {
                skip_tzname(s)?;
                Some(datetime)
            })
    }
}

impl PlainDateTime {
    pub(crate) fn with_offset(self, offset: Offset) -> Option<OffsetDateTime> {
        OffsetDateTime::new(self.date, self.time, offset)
    }

    pub(crate) const fn with_offset_unchecked(self, offset: Offset) -> OffsetDateTime {
        OffsetDateTime {
            date: self.date,
            time: self.time,
            offset,
        }
    }
}

impl Instant {
    pub(crate) fn to_offset(self, offset: Offset) -> Option<OffsetDateTime> {
        Some(
            self.shift_by_offset(offset)?
                .to_utc_plain()
                .with_offset_unchecked(offset),
        )
    }
}

impl Offset {
    pub(crate) fn read_iso(s: &mut Scan) -> Option<Self> {
        let sign = match s.next() {
            Some(b'+') => Sign::Plus,
            Some(b'-') => Sign::Minus,
            Some(b'Z' | b'z') => return Some(Self::ZERO),
            _ => return None,
        };
        let mut total = s.digits00_23()? as i32 * 3600;
        match s.advance_on(b':') {
            Some(true) => {
                total += s.digits00_59()? as i32 * 60;
                if let Some(true) = s.advance_on(b':') {
                    total += s.digits00_59()? as i32;
                }
            }
            Some(false) => {
                if let Some(minutes) = s.digits00_59() {
                    total += minutes as i32 * 60;
                    if let Some(seconds) = s.digits00_59() {
                        total += seconds as i32;
                    }
                }
            }
            None => {}
        }
        Some(Self::new_unchecked(total).with_sign(sign))
    }
}

impl fmt::Display for OffsetDateTime {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        let Self { date, time, offset } = self;
        write!(f, "{date}T{time}{offset}")
    }
}

fn skip_tzname(s: &mut Scan) -> Option<()> {
    if let Some(true) = s.advance_on(b'[') {
        match s.take_until_inclusive(|c| c == b']') {
            Some(tz) if is_valid_key(std::str::from_utf8(&tz[..tz.len() - 1]).ok()?) => (),
            _ => return None,
        }
    }
    Some(())
}
