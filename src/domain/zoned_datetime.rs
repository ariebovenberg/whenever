use super::{
    date::Date,
    difference::{self, CalendarIncrement, DifferenceUnitSet},
    instant::Instant,
    itemized_date_delta::ItemizedDateDelta,
    itemized_delta::ItemizedDelta,
    local::{Disambiguation, LocalMapping, LocalSeconds, ResolveError, ResolvePolicy},
    offset_datetime::OffsetDateTime,
    plain_datetime::{DateTimeBoundaryUnit, PlainDateTime},
    round,
    scalar::{EpochSecs, NegateIf, Offset, SubSecNanos},
    time::{Time, TimeBoundaryUnit},
    time_delta::TimeDelta,
    units::{NS_PER_DAY, NS_PER_SECOND, S_PER_DAY},
};
use crate::common::{
    fmt::{self, Sink},
    parse::Scan,
};
use crate::tz::tzif::TimeZone;
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

    /// The date of the day this value lies in. A day is chosen by the
    /// instant, not by the local date: past a repeated midnight, the second
    /// pass of the evening before lies in the day that has already started.
    pub(crate) fn day(&self) -> Date {
        let Self { date, ref tz, .. } = *self;
        match date
            .tomorrow()
            .and_then(|d| Some((d, d.at(Time::MIN).resolve_derived(tz)?)))
        {
            Some((tomorrow, start)) if self.to_instant() >= start.to_instant() => tomorrow,
            _ => date,
        }
    }

    /// The start of this value's day and of the next, resolved the way
    /// `start_of("day")` resolves a boundary. `day_length()` and day rounding
    /// both read them from here, so neither can drift from the boundary.
    pub(crate) fn day_bounds(&self) -> Option<(OffsetDateTime, OffsetDateTime)> {
        let Self { date, ref tz, .. } = *self;
        let start_of = |d: Date| d.at(Time::MIN).resolve_derived(tz);
        let tomorrow = date.tomorrow()?;
        let bounds = (start_of(date)?, start_of(tomorrow)?);
        // See `day()`
        Some(if self.to_instant() >= bounds.1.to_instant() {
            (bounds.1, start_of(tomorrow.tomorrow()?)?)
        } else {
            bounds
        })
    }

    pub(crate) fn round_day(&self, mode: round::Mode) -> Option<OffsetDateTime> {
        // A day is not a fixed length, so the fraction to round is the time
        // elapsed since the start of the day over the day's own length.
        let (day_start, next_day_start) = self.day_bounds()?;
        let day_ns = next_day_start
            .to_instant()
            .diff(day_start.to_instant())
            .total_nanos();
        let elapsed_ns = self
            .to_fixed_offset()
            .to_instant()
            .diff(day_start.to_instant())
            .total_nanos();
        // The value lies within its day: the loader rejects offset changes
        // of more than 24 hours and overlapping gaps and folds
        // (`load_transitions`), so `day_bounds()` steps one day at most.
        debug_assert!(day_ns > 1 && (0..day_ns).contains(&elapsed_ns));
        let (day_ns, elapsed_ns) = (day_ns as u64, elapsed_ns as u64);
        // The start of the day is the even multiple
        let expand = mode.to_abs(false).rounds_up(
            elapsed_ns > 0,
            elapsed_ns.cmp(&(day_ns - elapsed_ns)),
            false,
        );
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
        self.resolve_in(
            tz,
            ResolvePolicy::PreserveOffset(offset, Disambiguation::Compatible),
        )
        .ok()
    }

    /// Resolve a calendar-unit boundary derived from an existing value, which
    /// every value on the date must share: a repeated one takes the earlier
    /// occurrence, and a skipped one snaps to the end of the gap, so that
    /// successive intervals stay contiguous.
    #[inline]
    pub(crate) fn resolve_derived(self, tz: &TimeZone) -> Option<OffsetDateTime> {
        match tz.mapping_for_local(self.local_seconds()) {
            LocalMapping::Unique { offset } => self.assume_offset(offset),
            LocalMapping::Fold { before, .. } => self.assume_offset(before),
            LocalMapping::Gap {
                transition, after, ..
            } => transition.datetime(self.time.subsec).assume_offset(after),
        }
    }
}

/// A point on the timeline: epoch seconds and nanoseconds. Kept apart, since
/// nanoseconds over the whole range overflow an `i64` and `i128` division is
/// slow.
type Point = (i64, i32);

fn point_to_instant((secs, subsec): Point) -> Option<Instant> {
    Some(Instant {
        epoch: EpochSecs::new(secs)?,
        subsec: SubSecNanos::new_unchecked(subsec),
    })
}

/// The boundaries of a unit shorter than a day around a value
struct TimeUnitBounds {
    /// The latest boundary at or before the value
    start: Point,
    /// The earliest boundary after the value
    next: Point,
    /// Whether `start` is an odd multiple of the unit within its local day
    start_odd: bool,
}

const NS: i64 = NS_PER_SECOND as i64;
const S_PER_DAY_I64: i64 = S_PER_DAY as i64;

/// The multiple of `unit` at or before the clock reading of `t` at `offset`:
/// its local day, and its nanoseconds since that day's midnight
fn floor_multiple((secs, subsec): Point, offset: Offset, unit: i64) -> (i64, i64) {
    let local = secs + offset.get() as i64;
    let nanos = local.rem_euclid(S_PER_DAY_I64) * NS + subsec as i64;
    (local.div_euclid(S_PER_DAY_I64), nanos - nanos % unit)
}

/// The local seconds and nanoseconds of a multiple, which may lie outside
/// its day
fn local_point(day: i64, nanos: i64) -> Point {
    (
        day * S_PER_DAY_I64 + nanos.div_euclid(NS),
        nanos.rem_euclid(NS) as i32,
    )
}

fn is_odd_multiple(nanos: i64, unit: i64) -> bool {
    nanos.rem_euclid(NS_PER_DAY as i64) / unit % 2 == 1
}

impl ZonedDateTime {
    /// The start of the unit this value lies in, as ADR 0003 defines it
    pub(crate) fn start_of(&self, unit: DateTimeBoundaryUnit) -> Option<OffsetDateTime> {
        match unit {
            DateTimeBoundaryUnit::Time(unit) => self.start_of_time_unit(unit),
            DateTimeBoundaryUnit::Date(_) | DateTimeBoundaryUnit::Day => self
                .day()
                .at(Time::MIN)
                .start_of_unit(unit)?
                .resolve_derived(&self.tz),
        }
    }

    /// One nanosecond before the start of the next unit
    pub(crate) fn end_of(&self, unit: DateTimeBoundaryUnit) -> Option<OffsetDateTime> {
        match unit {
            DateTimeBoundaryUnit::Time(unit) => self.end_of_time_unit(unit),
            DateTimeBoundaryUnit::Date(_) | DateTimeBoundaryUnit::Day => self
                .day()
                .at(Time::MIN)
                .end_of_unit(unit)?
                .date
                .tomorrow()?
                .at(Time::MIN)
                .resolve_derived(&self.tz)?
                .to_instant()
                .shift(-TimeDelta::RESOLUTION)?
                .to_offset_in(&self.tz),
        }
    }

    // ADR 0003 defines the boundaries of a unit shorter than a day: each
    // multiple of the unit on the local clock, at both occurrences in a fold
    // at least as long as the unit, at the earlier one in a shorter fold,
    // and at the end of a gap. Where a multiple around the value occurs only
    // at the value's own offset, it is the boundary on that side: another
    // would take two transitions within a unit. Elsewhere,
    // `time_unit_bounds_near_transition()` searches the boundaries.

    /// Whether the local time `nanos` after this value's midnight, up to a
    /// day, occurs only at this value's offset
    fn only_at_own_offset(&self, nanos: u64) -> bool {
        let midnight = self.date.at(Time::MIN).local_seconds().get();
        matches!(
            self.tz.mapping_for_local(LocalSeconds::clamp(
                midnight + (nanos / NS_PER_SECOND as u64) as i64
            )),
            LocalMapping::Unique { offset } if offset == self.offset
        )
    }

    fn start_of_time_unit(&self, unit: TimeBoundaryUnit) -> Option<OffsetDateTime> {
        let start = self.time.start_of(unit);
        if self.only_at_own_offset(start.total_nanos()) {
            return self.date.at(start).assume_offset(self.offset);
        }
        let start = self.time_unit_bounds_near_transition(unit.ns()).start;
        point_to_instant(start)?.to_offset_in(&self.tz)
    }

    fn end_of_time_unit(&self, unit: TimeBoundaryUnit) -> Option<OffsetDateTime> {
        let end = self.time.end_of(unit);
        if self.only_at_own_offset(end.total_nanos() + 1) {
            return self.date.at(end).assume_offset(self.offset);
        }
        let (secs, subsec) = self.time_unit_bounds_near_transition(unit.ns()).next;
        let end = if subsec == 0 {
            (secs - 1, NS as i32 - 1)
        } else {
            (secs, subsec - 1)
        };
        point_to_instant(end)?.to_offset_in(&self.tz)
    }

    /// Round to the boundary at or before this value, or the one after it
    pub(crate) fn round_time_unit(
        &self,
        unit_ns: u64,
        mode: round::Mode,
    ) -> Option<OffsetDateTime> {
        let nanos = self.time.total_nanos();
        let floor = nanos - nanos % unit_ns;
        if self.only_at_own_offset(floor) && self.only_at_own_offset(floor + unit_ns) {
            let (time, next_day) = self.time.round(unit_ns, mode);
            let date = if next_day == 1 {
                self.date.tomorrow()?
            } else {
                self.date
            };
            return date.at(time).assume_offset(self.offset);
        }
        let TimeUnitBounds {
            start,
            next,
            start_odd,
        } = self.time_unit_bounds_near_transition(unit_ns);
        let Instant { epoch, subsec } = self.to_instant();
        let elapsed = (epoch.get() - start.0) * NS + (subsec.get() - start.1) as i64;
        let span = (next.0 - start.0) * NS + (next.1 - start.1) as i64;
        let round_up =
            mode.to_abs(false)
                .rounds_up(elapsed > 0, elapsed.cmp(&(span - elapsed)), start_odd);
        point_to_instant(if round_up { next } else { start })?.to_offset_in(&self.tz)
    }

    #[cold]
    fn time_unit_bounds_near_transition(&self, unit_ns: u64) -> TimeUnitBounds {
        let tz = &*self.tz;
        let unit = unit_ns as i64;
        let Instant { epoch, subsec } = self.to_instant();
        let t = (epoch.get(), subsec.get());
        let offset_at = |secs: i64| tz.offset_for_instant(EpochSecs::clamp(secs));
        // (instant, multiple as a local point, its nanoseconds in the day)
        let mut start: Option<(Point, Point, i64)> = None;
        let mut next: Option<Point> = None;
        let mut consider = |at: Point, local: Point, nanos: i64| {
            if at <= t {
                if start.is_none_or(|(s, l, _)| (at, local) > (s, l)) {
                    start = Some((at, local, nanos));
                }
            } else if next.is_none_or(|n| at < n) {
                next = Some(at);
            }
        };
        // Near a transition, the boundaries around the instant are multiples
        // on the clock of one of the offsets around it. The floor under each
        // is not enough: the instant may read as a multiple that lies after
        // it, and a transition within a unit after it moves the first
        // multiple of the new offset past the next one of the old.
        let offsets = [
            self.offset,
            offset_at(t.0 + (t.1 as i64 - unit).div_euclid(NS)),
            offset_at(t.0 + (t.1 as i64 + unit).div_euclid(NS)),
        ];
        for (i, &o) in offsets.iter().enumerate() {
            if offsets[..i].contains(&o) {
                continue;
            }
            let (day, floor) = floor_multiple(t, o, unit);
            for nanos in [floor - unit, floor, floor + unit, floor + 2 * unit] {
                let local = local_point(day, nanos);
                let at = |offset: Offset| (local.0 - offset.get() as i64, local.1);
                match tz.mapping_for_local(LocalSeconds::clamp(local.0)) {
                    LocalMapping::Unique { offset } => consider(at(offset), local, nanos),
                    LocalMapping::Fold { before, after, .. } => {
                        consider(at(before), local, nanos);
                        if before.sub(after).get() as i64 * NS >= unit {
                            consider(at(after), local, nanos);
                        }
                    }
                    LocalMapping::Gap {
                        transition, after, ..
                    } => consider((transition.get() - after.get() as i64, 0), local, nanos),
                }
            }
        }
        // The multiples of the value's own clock reading bracket it. Safe:
        // `mapping_for_local` agrees with `offset_for_instant`, since the
        // loader rejects overlapping gaps and folds (`load_transitions`) and
        // a POSIX TZ string that disagrees with the last record.
        let (start, _, nanos) = start.unwrap();
        TimeUnitBounds {
            start,
            next: next.unwrap(),
            start_odd: is_odd_multiple(nanos, unit),
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
    // Only the bracket structure is a format concern: whether the ID inside
    // names a time zone is for the store to decide, as for every other ID.
    let tz = s.rest();
    (tz.len() >= 2
        && tz[0] == b'['
        && tz.iter().position(|&byte| byte == b']') == Some(tz.len() - 1)
        && tz.is_ascii())
    .then(|| {
        // SAFETY: the preceding condition established that the bytes are ASCII.
        unsafe { std::str::from_utf8_unchecked(&tz[1..tz.len() - 1]) }
    })
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

/// The date on which `b` comes closest to `a` without passing it: the exact
/// remainder then has the sign of the difference.
///
/// It is usually the date of `a` or the one next to it. A gap of a day or
/// more (Samoa, 2011) steps further away, and a fold across midnight
/// (St. John's, 2010) steps past the date of `a`: past a repeated midnight,
/// the second pass of the evening before lies in the day that has already
/// started.
pub(crate) fn zoned_target(
    mut target_date: Date,
    a_inst: Instant,
    b: &ZonedDateTime,
    negative: bool,
) -> Option<Date> {
    let past = |shifted: Instant| {
        if negative {
            shifted < a_inst
        } else {
            shifted > a_inst
        }
    };
    let shifted_on = |d: Date| Some(b.with_date(d)?.to_instant());
    // A step along the direction of the difference, or against it
    let step = |d: Date, along: bool| {
        if along != negative {
            d.tomorrow()
        } else {
            d.yesterday()
        }
    };
    let mut shifted = shifted_on(target_date)?;
    if past(shifted) {
        target_date = step(target_date, false)?;
        while past(shifted_on(target_date)?) {
            target_date = step(target_date, false)?;
        }
    } else {
        // A date past the range is past `a` too
        while let Some(next) = step(target_date, true) {
            let next_shifted = shifted_on(next)?;
            // A skipped day resolves to the same time as the next
            if past(next_shifted) || next_shifted == shifted {
                break;
            }
            target_date = next;
            shifted = next_shifted;
        }
    }
    Some(target_date)
}

/// The difference from `b` to `a` in a calendar unit, with the fraction of
/// the way from the truncated amount to the next.
pub(crate) fn zoned_calendar_total(
    a_inst: Instant,
    b: &ZonedDateTime,
    target_date: Date,
    unit: difference::CalendarUnit,
    negative: bool,
) -> Option<f64> {
    let (trunc_amount, trunc_date, mut expand_date) = difference::date_diff_single_unit(
        target_date,
        b.date,
        CalendarIncrement::MIN,
        unit,
        negative,
    )?;
    let trunc = b.with_date(trunc_date.into())?.to_instant();
    let mut expand = b.with_date(expand_date.into())?.to_instant();
    let mut expand_amount = trunc_amount + 1.negate_if(negative);
    // A skipped day can resolve the expanded endpoint onto the truncated
    // one, or short of `a`: step it on until it reaches `a`.
    while if negative {
        expand > a_inst
    } else {
        expand < a_inst
    } {
        let (amount, _, next) = difference::date_diff_single_unit(
            expand_date.resolve(),
            b.date,
            CalendarIncrement::MIN,
            unit,
            negative,
        )?;
        expand_amount = amount + 1.negate_if(negative);
        expand_date = next;
        expand = b.with_date(expand_date.into())?.to_instant();
    }
    // The endpoints coincide only where `a` is the truncated value
    let fraction = if expand == trunc {
        0.0
    } else {
        a_inst.diff(trunc).total_nanos() as f64 / expand.diff(trunc).total_nanos() as f64
    };
    Some(trunc_amount as f64 + (expand_amount - trunc_amount) as f64 * fraction)
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
    if exact_units.is_empty() {
        let increment = round_increment.to_calendar()?;
        let mode = round_mode.to_abs(negative);
        let short_of_a = |t: Instant| if negative { t > a_inst } else { t < a_inst };
        let diff_to = |d: difference::InterimDate| {
            difference::date_diff(d.resolve(), b.date, increment, calendar_units, negative)
        };
        let mut expand_date = expand_date;
        let mut expand = b.with_date(expand_date.into())?.to_instant();
        // A skipped day can resolve the expanded endpoint onto the truncated
        // one, or short of `a`: step it on until it reaches `a`.
        while mode != round::AbsMode::Trunc && short_of_a(expand) {
            expand_date = diff_to(expand_date)?.2;
            expand = b.with_date(expand_date.into())?.to_instant();
        }
        if ddelta.round_by_time(
            calendar_units.smallest(),
            a_inst,
            trunc,
            expand,
            mode,
            increment,
            negative,
        ) {
            // The larger units take the carry, and the smallest stays a
            // multiple of the increment. Counted on the dates, and stepped
            // on where a skipped day resolves the carried date short of `a`.
            let (mut carried, mut carried_date, mut next) = diff_to(expand_date)?;
            while short_of_a(b.with_date(carried_date.into())?.to_instant()) {
                (carried, carried_date, next) = diff_to(next)?;
            }
            ddelta = carried;
        }
        let mut result = ItemizedDelta::UNSET;
        result.fill_calendar_units(ddelta);
        return Some(result);
    }
    let diff = a_inst.diff(trunc);
    let rounded = diff.round_in_units(exact_units, round_increment, round_mode)?;
    if calendar_units.is_empty() || rounded.abs() <= diff.abs() {
        let mut result = rounded.itemize(exact_units)?;
        result.fill_calendar_units(ddelta);
        return Some(result);
    }
    // Rounded up: the larger units take the carry, and the smallest stays a
    // multiple of the increment
    let endpoint = trunc.shift(rounded)?.to_offset_in(&b.tz)?;
    let endpoint_inst = endpoint.to_instant();
    zoned_since_in_units(
        endpoint,
        endpoint_inst,
        b,
        zoned_target(endpoint.date, endpoint_inst, b, negative)?,
        units,
        round::Mode::Trunc,
        round_increment,
        negative,
    )
}
