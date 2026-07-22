use super::{
    date::Date, instant::Instant, itemized_date_delta::ItemizedDateDelta,
    itemized_delta::ItemizedDelta, offset_datetime::OffsetDateTime, plain_datetime::PlainDateTime,
    scalar::Offset, time::Time,
};
use crate::{common::ambiguity::Ambiguity, tz::tzif::TimeZone};
use crate::{
    common::{
        fmt::{self, Sink},
        math::{self, DateRoundIncrement, DeltaUnitSet},
        parse::Scan,
        round,
    },
    tz::tzif::is_valid_key,
};
use std::sync::Arc;

#[derive(Debug, Clone)]
pub(crate) struct ZonedDateTime {
    pub(crate) date: Date,
    pub(crate) time: Time,
    pub(crate) offset: Offset,
    pub(crate) tz: Arc<TimeZone>,
}

impl PartialEq for ZonedDateTime {
    fn eq(&self, other: &Self) -> bool {
        self.date == other.date
            && self.time == other.time
            && self.offset == other.offset
            && self.same_tz(other)
    }
}

impl ZonedDateTime {
    pub(crate) fn same_tz(&self, other: &Self) -> bool {
        Arc::ptr_eq(&self.tz, &other.tz) || *self.tz == *other.tz
    }

    pub(crate) fn to_instant(&self) -> Instant {
        self.to_plain()
            .assume_utc()
            .shift_by_offset(-self.offset)
            .unwrap()
    }

    pub(crate) fn to_plain(&self) -> PlainDateTime {
        PlainDateTime {
            date: self.date,
            time: self.time,
        }
    }

    pub(crate) fn to_fixed_offset(&self) -> OffsetDateTime {
        OffsetDateTime {
            date: self.date,
            time: self.time,
            offset: self.offset,
        }
    }

    pub(crate) fn with_date(&self, date: Date) -> Option<OffsetDateTime> {
        self.to_fixed_offset().with_date_in_tz(date, &self.tz)
    }

    pub(crate) fn round_day(&self, mode: round::Mode) -> Option<OffsetDateTime> {
        let Self {
            date, time, ref tz, ..
        } = *self;
        let get_floor = || date.at(Time::MIN).localize_default(tz);
        let get_ceil = || date.tomorrow()?.at(Time::MIN).localize_default(tz);
        match mode {
            round::Mode::Ceil | round::Mode::Expand => {
                if time == Time::MIN {
                    Some(self.to_fixed_offset())
                } else {
                    get_ceil()
                }
            }
            round::Mode::Floor | round::Mode::Trunc => get_floor(),
            _ => {
                let time_ns = time.total_nanos();
                let floor = get_floor()?;
                let ceil = get_ceil()?;
                let day_ns = ceil.to_instant().diff(floor.to_instant()).total_nanos() as u64;
                debug_assert!(day_ns > 1);
                let threshold = match mode {
                    round::Mode::HalfEven => day_ns / 2 + (time_ns % 2 == 0) as u64,
                    round::Mode::HalfFloor | round::Mode::HalfTrunc => day_ns / 2 + 1,
                    round::Mode::HalfCeil | round::Mode::HalfExpand => day_ns / 2,
                    _ => unreachable!(),
                };
                Some(if time_ns >= threshold { ceil } else { floor })
            }
        }
    }
}

impl PlainDateTime {
    pub(crate) fn localize_default(self, tz: &TimeZone) -> Option<OffsetDateTime> {
        match tz.ambiguity_for_local(self.assume_utc().epoch) {
            Ambiguity::Unambiguous(offset) | Ambiguity::Fold(_, offset, _) => {
                self.with_offset(offset)
            }
            Ambiguity::Gap(_, later_offset, earlier_offset) => self
                .shift_by_offset(later_offset.sub(earlier_offset))?
                .with_offset(later_offset),
        }
    }

    pub(crate) fn localize_using_offset(
        self,
        tz: &TimeZone,
        target: Offset,
    ) -> Option<OffsetDateTime> {
        match tz.ambiguity_for_local(self.assume_utc().epoch) {
            Ambiguity::Unambiguous(offset) => self.with_offset(offset),
            Ambiguity::Fold(_, earlier_offset, later_offset) => {
                self.with_offset(if target == later_offset {
                    later_offset
                } else {
                    earlier_offset
                })
            }
            Ambiguity::Gap(_, later_offset, earlier_offset) => self
                .shift_by_offset(later_offset.sub(earlier_offset))?
                .with_offset(later_offset),
        }
    }
}

impl OffsetDateTime {
    fn with_date_in_tz(self, date: Date, tz: &TimeZone) -> Option<Self> {
        match tz.ambiguity_for_local(date.epoch_at(self.time)) {
            Ambiguity::Unambiguous(offset) => Self::new(date, self.time, offset),
            Ambiguity::Fold(_, earlier_offset, later_offset) => Self::new(
                date,
                self.time,
                if self.offset == later_offset {
                    later_offset
                } else {
                    earlier_offset
                },
            ),
            Ambiguity::Gap(_, later_offset, earlier_offset) => PlainDateTime {
                date,
                time: self.time,
            }
            .shift_by_offset(later_offset.sub(earlier_offset))?
            .with_offset(later_offset),
        }
    }
}

impl Instant {
    pub(crate) fn to_offset_in(self, tz: &TimeZone) -> Option<OffsetDateTime> {
        let offset = tz.offset_for_instant(self.epoch);
        Some(
            self.epoch
                .shift_by_offset(offset)?
                .datetime(self.subsec)
                .with_offset_unchecked(offset),
        )
    }
}

pub(crate) enum OffsetInIsoString {
    Some(Offset),
    Z,
    Missing,
}

pub(crate) fn read_offset_and_tzname<'a>(s: &'a mut Scan) -> Option<(OffsetInIsoString, &'a str)> {
    let offset = match s.peek() {
        Some(b'[') => OffsetInIsoString::Missing,
        Some(b'Z' | b'z') => {
            s.take_unchecked(1);
            OffsetInIsoString::Z
        }
        _ => OffsetInIsoString::Some(Offset::read_iso(s)?),
    };
    let tz = s.rest();
    (tz.len() > 2
        && tz[0] == b'['
        && tz.iter().position(|&byte| byte == b']') == Some(tz.len() - 1)
        && tz.is_ascii())
    .then(|| {
        // SAFETY: the preceding condition established that the bytes are ASCII.
        unsafe { std::str::from_utf8_unchecked(&tz[1..tz.len() - 1]) }
    })
    .filter(|tz| is_valid_key(tz))
    .map(|tz| (offset, tz))
}

pub(crate) struct TzFormat<'a> {
    pub(crate) tz: &'a TimeZone,
}

impl fmt::Chunk for TzFormat<'_> {
    fn len(&self) -> usize {
        self.tz.key.as_ref().map_or(0, |key| key.len() + 2)
    }

    fn write(&self, sink: &mut impl Sink) {
        if let Some(ref tz_key) = self.tz.key {
            sink.write_byte(b'[');
            sink.write(tz_key.as_bytes());
            sink.write_byte(b']');
        }
    }
}

pub(crate) fn zoned_target(
    mut target_date: Date,
    a_inst: Instant,
    b: &ZonedDateTime,
    negative: bool,
) -> Option<Date> {
    if !negative {
        while b.with_date(target_date)?.to_instant() > a_inst {
            target_date = target_date.yesterday()?;
        }
    } else {
        while b.with_date(target_date)?.to_instant() < a_inst {
            target_date = target_date.tomorrow()?;
        }
    }
    Some(target_date)
}

#[allow(clippy::too_many_arguments)]
pub(crate) fn zoned_since_in_units(
    a: OffsetDateTime,
    a_inst: Instant,
    b: &ZonedDateTime,
    target_date: Date,
    units: DeltaUnitSet,
    round_mode: round::Mode,
    round_increment: math::RoundIncrement,
    negative: bool,
) -> Option<ItemizedDelta> {
    let (cal_units, exact_units) = units.split_cal_exact();
    let (mut ddelta, trunc_date, expand_date) = if cal_units.is_empty() {
        (ItemizedDateDelta::UNSET, b.date.into(), a.date.into())
    } else {
        let increment = if exact_units.is_empty() {
            round_increment.to_date()?
        } else {
            DateRoundIncrement::MIN
        };
        math::date_diff(target_date, b.date, increment, cal_units, negative)?
    };

    let trunc = b.with_date(trunc_date.into())?.to_instant();
    let expand = b.with_date(expand_date.into())?.to_instant();
    let mut result = if exact_units.is_empty() {
        ddelta.round_by_time(
            cal_units.smallest(),
            a_inst,
            trunc,
            expand,
            round_mode.to_abs_trunc(negative),
            round_increment.to_date()?,
            negative,
        );
        ItemizedDelta::UNSET
    } else {
        a_inst.diff(trunc).in_exact_units(
            exact_units,
            round_increment,
            round_mode.to_abs_euclid(negative),
        )?
    };
    result.fill_cal_units(ddelta);
    Some(result)
}
