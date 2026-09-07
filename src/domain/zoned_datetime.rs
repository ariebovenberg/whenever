use super::{
    date::Date,
    difference::{self, CalendarIncrement, DifferenceUnitSet},
    instant::Instant,
    itemized_date_delta::ItemizedDateDelta,
    itemized_delta::ItemizedDelta,
    local::{LocalMapping, ResolveError, ResolvePolicy},
    offset_datetime::OffsetDateTime,
    plain_datetime::PlainDateTime,
    round,
    scalar::Offset,
    time::Time,
};
use crate::tz::tzif::TimeZone;
use crate::{
    common::{
        fmt::{self, Sink},
        parse::Scan,
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
        self.to_plain().assume_offset_unchecked(self.offset)
    }

    pub(crate) fn with_date(&self, date: Date) -> Option<OffsetDateTime> {
        self.to_fixed_offset().with_date_in_tz(date, &self.tz)
    }

    /// The start of this value's day and of the next, resolved the way
    /// `start_of("day")` resolves a boundary. `day_length()` and day rounding
    /// both read them from here, so neither can drift from the boundary.
    pub(crate) fn day_bounds(&self) -> Option<(OffsetDateTime, OffsetDateTime)> {
        let Self { date, ref tz, .. } = *self;
        Some((
            date.at(Time::MIN).resolve_derived(tz, None)?,
            date.tomorrow()?.at(Time::MIN).resolve_derived(tz, None)?,
        ))
    }

    pub(crate) fn round_day(&self, mode: round::Mode) -> Option<OffsetDateTime> {
        // A day is not a fixed length, so the fraction to round is the time
        // elapsed since the start of the day over the day's own length.
        let (day_start, next_day_start) = self.day_bounds()?;
        let day_ns = next_day_start
            .to_instant()
            .diff(day_start.to_instant())
            .total_nanos() as u64;
        debug_assert!(day_ns > 1);
        let elapsed_ns = self
            .to_fixed_offset()
            .to_instant()
            .diff(day_start.to_instant())
            .total_nanos() as u64;
        let expand = match mode {
            round::Mode::Floor | round::Mode::Trunc => false,
            round::Mode::Ceil | round::Mode::Expand => elapsed_ns > 0,
            round::Mode::HalfCeil | round::Mode::HalfExpand => elapsed_ns * 2 >= day_ns,
            // A tie rounds to the even multiple, which is the start of the day.
            round::Mode::HalfFloor | round::Mode::HalfTrunc | round::Mode::HalfEven => {
                elapsed_ns * 2 > day_ns
            }
        };
        Some(if expand { next_day_start } else { day_start })
    }
}

impl PlainDateTime {
    #[inline]
    pub(crate) fn resolve_in(
        self,
        tz: &TimeZone,
        policy: ResolvePolicy,
    ) -> Result<OffsetDateTime, ResolveError> {
        tz.mapping_for_local(self.local_seconds())
            .resolve(self, policy)
    }

    #[inline]
    pub(crate) fn resolve_preserving_offset(
        self,
        tz: &TimeZone,
        offset: Offset,
    ) -> Option<OffsetDateTime> {
        self.resolve_in(tz, ResolvePolicy::PreserveOffset(offset))
            .ok()
    }

    /// Resolve a local time derived from an existing value--a unit boundary or
    /// a rounded result--rather than one the caller wrote.
    ///
    /// A repeated local time keeps `current` while it is still valid, and
    /// takes the earlier occurrence otherwise. Pass `None` for a boundary that
    /// every value on the date must share, so that the value's own offset
    /// cannot influence it. A skipped local time snaps to the edge of the gap,
    /// so that successive intervals stay contiguous.
    #[inline]
    pub(crate) fn resolve_derived(
        self,
        tz: &TimeZone,
        current: Option<Offset>,
    ) -> Option<OffsetDateTime> {
        match tz.mapping_for_local(self.local_seconds()) {
            LocalMapping::Unique { offset } => self.assume_offset(offset),
            LocalMapping::Fold { before, after, .. } => {
                self.assume_offset(if current == Some(after) {
                    after
                } else {
                    before
                })
            }
            LocalMapping::Gap {
                transition, after, ..
            } => transition.datetime(self.time.subsec).assume_offset(after),
        }
    }
}

impl OffsetDateTime {
    fn with_date_in_tz(self, date: Date, tz: &TimeZone) -> Option<Self> {
        PlainDateTime {
            date,
            time: self.time,
        }
        .resolve_preserving_offset(tz, self.offset)
    }

    pub(crate) fn into_zoned_unchecked(self, tz: Arc<TimeZone>) -> ZonedDateTime {
        ZonedDateTime {
            date: self.date,
            time: self.time,
            offset: self.offset,
            tz,
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
                .assume_offset_unchecked(offset),
        )
    }

    pub(crate) fn in_timezone(self, tz: Arc<TimeZone>) -> Option<ZonedDateTime> {
        self.to_offset_in(&tz)
            .map(|datetime| datetime.into_zoned_unchecked(tz))
    }
}

pub(crate) enum OffsetInIsoString {
    MinutePrecision(Offset),
    SecondPrecision(Offset),
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
        _ => {
            let (offset, exact) = Offset::read_iso_with_precision(s)?;
            if exact {
                OffsetInIsoString::SecondPrecision(offset)
            } else {
                OffsetInIsoString::MinutePrecision(offset)
            }
        }
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
        self.tz.key.as_ref().map_or(0, |k| k.len() + 2)
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
    units: DifferenceUnitSet,
    round_mode: round::Mode,
    round_increment: difference::DifferenceIncrement,
    negative: bool,
) -> Option<ItemizedDelta> {
    let (calendar_units, exact_units) = units.split_calendar_exact();
    let (mut ddelta, trunc_date, expand_date) = if calendar_units.is_empty() {
        (ItemizedDateDelta::UNSET, b.date.into(), a.date.into())
    } else {
        let increment = if exact_units.is_empty() {
            round_increment.to_calendar()?
        } else {
            CalendarIncrement::MIN
        };
        difference::date_diff(target_date, b.date, increment, calendar_units, negative)?
    };

    let trunc = b.with_date(trunc_date.into())?.to_instant();
    let expand = b.with_date(expand_date.into())?.to_instant();
    let mut result = if exact_units.is_empty() {
        ddelta.round_by_time(
            calendar_units.smallest(),
            a_inst,
            trunc,
            expand,
            round_mode.to_abs_trunc(negative),
            round_increment.to_calendar()?,
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
    result.fill_calendar_units(ddelta);
    Some(result)
}
