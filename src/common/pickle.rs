//! Stable pickle payload codecs shared with the pure-Python implementation.
//!
//! All fields are little-endian:
//!
//! | Type | Fields | Bytes |
//! | --- | --- | ---: |
//! | Date | `u16 year, u8 month, u8 day` | 4 |
//! | Time | `u8 hour, u8 minute, u8 second, u32 nanos` | 7 |
//! | PlainDateTime | Date + Time | 11 |
//! | Instant | `i64 epoch seconds, u32 nanos` | 12 |
//! | TimeDelta | `i64 seconds, u32 nanos` | 12 |
//! | OffsetDateTime | PlainDateTime + `i32 offset seconds` | 15 |
//! | ZonedDateTime | OffsetDateTime + separate timezone ID | 15 + ID |

use crate::domain::{
    date::Date,
    instant::Instant,
    offset_datetime::OffsetDateTime,
    plain_datetime::PlainDateTime,
    scalar::{EpochSecs, Month, Offset, SubSecNanos, Year},
    time::Time,
    time_delta::TimeDelta,
};

pub(crate) const DATE_LEN: usize = 4;
pub(crate) const TIME_LEN: usize = 7;
pub(crate) const PLAIN_DATETIME_LEN: usize = DATE_LEN + TIME_LEN;
pub(crate) const INSTANT_LEN: usize = 12;
pub(crate) const TIME_DELTA_LEN: usize = 12;
pub(crate) const OFFSET_DATETIME_LEN: usize = PLAIN_DATETIME_LEN + 4;
pub(crate) const INVALID_DATA: &str = "invalid pickle data";

pub(crate) fn encode_date(value: Date) -> [u8; DATE_LEN] {
    let mut data = [0; DATE_LEN];
    data[..2].copy_from_slice(&value.year.get().to_le_bytes());
    data[2] = value.month.get();
    data[3] = value.day;
    data
}

pub(crate) fn decode_date(data: &[u8]) -> Option<Date> {
    let data: &[u8; DATE_LEN] = data.try_into().ok()?;
    let year = Year::new(u16::from_le_bytes(data[..2].try_into().unwrap()))?;
    let month = Month::new(data[2])?;
    Date::new(year, month, data[3])
}

pub(crate) fn encode_time(value: Time) -> [u8; TIME_LEN] {
    let mut data = [0; TIME_LEN];
    data[0] = value.hour;
    data[1] = value.minute;
    data[2] = value.second;
    data[3..].copy_from_slice(&value.subsec.as_u32().to_le_bytes());
    data
}

pub(crate) fn decode_time(data: &[u8]) -> Option<Time> {
    let data: &[u8; TIME_LEN] = data.try_into().ok()?;
    let nanos = u32::from_le_bytes(data[3..].try_into().unwrap());
    let subsec = i32::try_from(nanos).ok().and_then(SubSecNanos::new)?;
    Time::new(data[0], data[1], data[2], subsec)
}

pub(crate) fn encode_plain(value: PlainDateTime) -> [u8; PLAIN_DATETIME_LEN] {
    let mut data = [0; PLAIN_DATETIME_LEN];
    data[..DATE_LEN].copy_from_slice(&encode_date(value.date));
    data[DATE_LEN..].copy_from_slice(&encode_time(value.time));
    data
}

pub(crate) fn decode_plain(data: &[u8]) -> Option<PlainDateTime> {
    let data: &[u8; PLAIN_DATETIME_LEN] = data.try_into().ok()?;
    Some(PlainDateTime {
        date: decode_date(&data[..DATE_LEN])?,
        time: decode_time(&data[DATE_LEN..])?,
    })
}

pub(crate) fn encode_instant(value: Instant) -> [u8; INSTANT_LEN] {
    let mut data = [0; INSTANT_LEN];
    data[..8].copy_from_slice(&value.epoch.get().to_le_bytes());
    data[8..].copy_from_slice(&value.subsec.as_u32().to_le_bytes());
    data
}

pub(crate) fn decode_instant(data: &[u8]) -> Option<Instant> {
    let data: &[u8; INSTANT_LEN] = data.try_into().ok()?;
    Some(Instant {
        epoch: EpochSecs::new(i64::from_le_bytes(data[..8].try_into().unwrap()))?,
        subsec: decode_subsec(&data[8..])?,
    })
}

pub(crate) fn decode_pre_0_8_instant(data: &[u8]) -> Option<Instant> {
    let data: &[u8; INSTANT_LEN] = data.try_into().ok()?;
    let legacy_epoch = i64::from_le_bytes(data[..8].try_into().unwrap());
    let epoch = legacy_epoch.checked_add(EpochSecs::MIN.get() - 86_400)?;
    Some(Instant {
        epoch: EpochSecs::new(epoch)?,
        subsec: decode_subsec(&data[8..])?,
    })
}

pub(crate) fn encode_time_delta(value: TimeDelta) -> [u8; TIME_DELTA_LEN] {
    let mut data = [0; TIME_DELTA_LEN];
    data[..8].copy_from_slice(&value.secs.get().to_le_bytes());
    data[8..].copy_from_slice(&value.subsec.as_u32().to_le_bytes());
    data
}

pub(crate) fn decode_time_delta(data: &[u8]) -> Option<TimeDelta> {
    let data: &[u8; TIME_DELTA_LEN] = data.try_into().ok()?;
    let secs = i64::from_le_bytes(data[..8].try_into().unwrap());
    let subsec = decode_subsec(&data[8..])?;
    TimeDelta::from_nanos(secs as i128 * 1_000_000_000 + subsec.get() as i128)
}

pub(crate) fn encode_offset(value: OffsetDateTime) -> [u8; OFFSET_DATETIME_LEN] {
    let mut data = [0; OFFSET_DATETIME_LEN];
    data[..PLAIN_DATETIME_LEN].copy_from_slice(&encode_plain(value.to_plain()));
    data[PLAIN_DATETIME_LEN..].copy_from_slice(&value.offset.get().to_le_bytes());
    data
}

pub(crate) fn decode_offset(data: &[u8]) -> Option<OffsetDateTime> {
    let data: &[u8; OFFSET_DATETIME_LEN] = data.try_into().ok()?;
    let plain = decode_plain(&data[..PLAIN_DATETIME_LEN])?;
    let offset = Offset::new(i32::from_le_bytes(
        data[PLAIN_DATETIME_LEN..].try_into().unwrap(),
    ))?;
    plain.assume_offset(offset)
}

fn decode_subsec(data: &[u8]) -> Option<SubSecNanos> {
    let nanos = u32::from_le_bytes(data.try_into().ok()?);
    i32::try_from(nanos).ok().and_then(SubSecNanos::new)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::domain::scalar::{DeltaSeconds, Month, Offset, SubSecNanos, Year};

    fn date(year: u16, month: u8, day: u8) -> Date {
        Date::new(Year::new(year).unwrap(), Month::new(month).unwrap(), day).unwrap()
    }

    fn time(hour: u8, minute: u8, second: u8, nanos: i32) -> Time {
        Time::new(hour, minute, second, SubSecNanos::new(nanos).unwrap()).unwrap()
    }

    #[test]
    fn representative_wire_formats() {
        let date = date(2024, 2, 29);
        let time = time(3, 4, 5, 600_700_800);
        let plain = PlainDateTime { date, time };
        let instant = Instant {
            epoch: EpochSecs::new(-12_345_678).unwrap(),
            subsec: SubSecNanos::new(901_234_567).unwrap(),
        };
        let delta = TimeDelta {
            secs: DeltaSeconds::new(-12_345).unwrap(),
            subsec: SubSecNanos::new(678_901_234).unwrap(),
        };
        let offset = plain.assume_offset(Offset::new(-3_723).unwrap()).unwrap();

        assert_eq!(encode_date(date), [0xe8, 0x07, 2, 29]);
        assert_eq!(encode_time(time), [3, 4, 5, 0x80, 0xf7, 0xcd, 0x23]);
        assert_eq!(
            encode_plain(plain),
            [0xe8, 0x07, 2, 29, 3, 4, 5, 0x80, 0xf7, 0xcd, 0x23]
        );
        assert_eq!(
            encode_instant(instant),
            [
                0xb2, 0x9e, 0x43, 0xff, 0xff, 0xff, 0xff, 0xff, 0x87, 0xbf, 0xb7, 0x35,
            ]
        );
        assert_eq!(
            encode_time_delta(delta),
            [
                0xc7, 0xcf, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xf2, 0x35, 0x77, 0x28,
            ]
        );
        assert_eq!(
            encode_offset(offset),
            [
                0xe8, 0x07, 2, 29, 3, 4, 5, 0x80, 0xf7, 0xcd, 0x23, 0x75, 0xf1, 0xff, 0xff,
            ]
        );
    }

    #[test]
    fn roundtrips_boundaries() {
        for value in [Date::MIN, Date::MAX] {
            assert_eq!(decode_date(&encode_date(value)), Some(value));
        }
        for value in [Time::MIN, Time::MAX] {
            assert_eq!(decode_time(&encode_time(value)), Some(value));
        }
        for value in [PlainDateTime::MIN, PlainDateTime::MAX] {
            assert_eq!(decode_plain(&encode_plain(value)), Some(value));
        }
        for value in [
            Instant {
                epoch: EpochSecs::MIN,
                subsec: SubSecNanos::MIN,
            },
            Instant {
                epoch: EpochSecs::MAX,
                subsec: SubSecNanos::MAX,
            },
        ] {
            assert_eq!(decode_instant(&encode_instant(value)), Some(value));
        }
        for value in [TimeDelta::MIN, TimeDelta::MAX] {
            assert_eq!(decode_time_delta(&encode_time_delta(value)), Some(value));
        }
        for value in [
            PlainDateTime::MIN.assume_offset(Offset::ZERO).unwrap(),
            PlainDateTime::MAX.assume_offset(Offset::ZERO).unwrap(),
        ] {
            assert_eq!(decode_offset(&encode_offset(value)), Some(value));
        }
    }

    #[test]
    fn decodes_pre_0_8_instant() {
        let data = [
            0x49, 0xb4, 0xcb, 0xd6, 0x0e, 0x00, 0x00, 0x00, 0x38, 0x68, 0xde, 0x3a,
        ];
        assert_eq!(
            decode_pre_0_8_instant(&data),
            Some(Instant {
                epoch: EpochSecs::new(1_597_533_129).unwrap(),
                subsec: SubSecNanos::new(987_654_200).unwrap(),
            })
        );
    }

    #[test]
    fn rejects_malformed_payloads() {
        assert_eq!(decode_date(&[1, 2, 3]), None);
        assert_eq!(decode_date(&[0, 0, 1, 1]), None);
        assert_eq!(decode_date(&[0x24, 0x27, 1, 1]), None);
        assert_eq!(decode_date(&[0xe8, 0x07, 13, 1]), None);
        assert_eq!(decode_date(&[0xe8, 0x07, 2, 30]), None);

        assert_eq!(decode_time(&[24, 0, 0, 0, 0, 0, 0]), None);
        assert_eq!(decode_time(&[0, 60, 0, 0, 0, 0, 0]), None);
        assert_eq!(decode_time(&[0, 0, 60, 0, 0, 0, 0]), None);
        assert_eq!(decode_time(&[0, 0, 0, 0, 0xca, 0x9a, 0x3b]), None);

        let mut instant = encode_instant(Instant {
            epoch: EpochSecs::MIN,
            subsec: SubSecNanos::MIN,
        });
        instant[..8].copy_from_slice(&(EpochSecs::MIN.get() - 1).to_le_bytes());
        assert_eq!(decode_instant(&instant), None);

        let mut delta = encode_time_delta(TimeDelta::MAX);
        delta[8] = 1;
        assert_eq!(decode_time_delta(&delta), None);

        let mut offset = encode_offset(PlainDateTime::MIN.assume_offset(Offset::ZERO).unwrap());
        offset[PLAIN_DATETIME_LEN..].copy_from_slice(&86_400_i32.to_le_bytes());
        assert_eq!(decode_offset(&offset), None);

        let mut offset = encode_offset(PlainDateTime::MIN.assume_offset(Offset::ZERO).unwrap());
        offset[PLAIN_DATETIME_LEN..].copy_from_slice(&1_i32.to_le_bytes());
        assert_eq!(decode_offset(&offset), None);

        let mut legacy = [0; INSTANT_LEN];
        legacy[..8].copy_from_slice(&i64::MIN.to_le_bytes());
        assert_eq!(decode_pre_0_8_instant(&legacy), None);
    }
}
