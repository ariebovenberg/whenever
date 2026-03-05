//! Calendar difference logic for since()/until() methods.
//! Rust equivalent of _math.py's date_diff and custom_round.
use std::cmp::Ordering;

use crate::{
    classes::{
        date::Date, instant::Instant, itemized_date_delta::ItemizedDateDelta,
        itemized_delta::ItemizedDelta, time_delta::TimeDelta,
    },
    common::{
        round,
        scalar::{DeltaDays, DeltaField, DeltaMonths, Month, Year},
    },
    py::*,
    pymodule::State,
};

/// A Date-like struct that allows Feb 29 on non-leap years.
/// Resolving to a real Date clamps the day (e.g. Feb 29 → Feb 28).
#[derive(Debug, Copy, Clone)]
pub(crate) struct InterimDate {
    year: Year,
    month: Month,
    day: u8,
}

impl InterimDate {
    /// Resolve to a real Date, clamping invalid days to the last day of the month.
    pub(crate) fn resolve(self) -> Date {
        Date::new_clamp_days(self.year, self.month, self.day)
    }

    /// Replace the year of an interim date, preserving the day even if invalid.
    fn replace_year(self, year: Year) -> InterimDate {
        InterimDate {
            year,
            month: self.month,
            day: self.day,
        }
    }

    // Similar to Date::shift_months, but works on InterimDate.
    // (Can't fully reuse shift_months because InterimDate may have day=29 on non-leap year)
    fn shift_months(self, diff: i32) -> Option<Date> {
        DeltaMonths::new(diff)
            .and_then(|d| self.month.shift(self.year, d))
            .map(|(y, m)| Date::new_clamp_days(y, m, self.day))
    }
}

impl From<Date> for InterimDate {
    fn from(d: Date) -> Self {
        InterimDate {
            year: d.year,
            month: d.month,
            day: d.day,
        }
    }
}

impl From<InterimDate> for Date {
    fn from(d: InterimDate) -> Self {
        d.resolve()
    }
}

/// Result of a single-unit diff: (value, trunc_date, expand_date)
type CalDiff = (i32, InterimDate, InterimDate);

// TODO: prevent increment overflow!
fn years_diff(a: Date, b: InterimDate, increment: i32, sign: i8) -> Option<CalDiff> {
    let diff = (a.year.get() as i32 - b.year.get() as i32) / increment * increment;
    let shift = b.replace_year(b.year.add_i32(diff)?);

    let overshot = if diff > 0 {
        shift.resolve() > a
    } else if diff < 0 {
        shift.resolve() < a
    } else {
        false
    };

    if overshot {
        let adj = diff - increment * sign as i32;
        let adj_year = b.year.add_i32(adj)?;
        Some((adj, b.replace_year(adj_year), shift))
    } else {
        let exp_year = b.year.add_i32(diff + increment * sign as i32)?;
        Some((diff, shift, b.replace_year(exp_year)))
    }
}

fn months_diff(a: Date, b: InterimDate, increment: i32, sign: i8) -> Option<CalDiff> {
    let diff = ((a.year.get() as i32 - b.year.get() as i32) * 12
        + (a.month as i32 - b.month as i32))
        / increment
        * increment;
    let shift = b.shift_months(diff)?;

    let overshot = if diff > 0 {
        shift > a
    } else if diff < 0 {
        shift < a
    } else {
        false
    };

    if overshot {
        let adj = diff - increment * sign as i32;
        Some((adj, b.shift_months(adj)?.into(), shift.into()))
    } else {
        Some((
            diff,
            shift.into(),
            b.shift_months(diff + increment * sign as i32)?.into(),
        ))
    }
}

fn weeks_diff(a: Date, b: InterimDate, increment: i32, sign: i8) -> Option<CalDiff> {
    let (days, trunc, expand) = days_diff(a, b, increment * 7, sign)?;
    Some((days / 7, trunc, expand))
}

fn days_diff(a: Date, b: InterimDate, increment: i32, sign: i8) -> Option<CalDiff> {
    let b_resolved = b.resolve();
    let delta = a.unix_days().diff(b_resolved.unix_days());
    // SAFETY: truncated value (towards zero) never overflows
    let trunc_value = DeltaDays::new_unchecked(delta.get() / increment * increment);

    let trunc_date = b_resolved.shift_days(trunc_value)?;
    let expand_date = trunc_date.shift_days(DeltaDays::new(increment * sign as i32)?)?;
    Some((trunc_value.get(), trunc_date.into(), expand_date.into()))
}

// Similar to date_delta::Unit, but with explicit discriminants for array indexing.
// Not unified because date_delta is being removed in the next release.
/// Calendar unit for date diffing
#[derive(Debug, Copy, Clone, PartialEq, Eq, PartialOrd, Ord)]
pub(crate) enum CalUnit {
    Years = 0,
    Months = 1,
    Weeks = 2,
    Days = 3,
}

impl CalUnit {
    pub(crate) fn from_py(v: PyObj, state: &State) -> PyResult<Self> {
        find_interned(v, |v, eq| {
            Some(if eq(v, state.str_years) {
                CalUnit::Years
            } else if eq(v, state.str_months) {
                CalUnit::Months
            } else if eq(v, state.str_weeks) {
                CalUnit::Weeks
            } else if eq(v, state.str_days) {
                CalUnit::Days
            } else {
                None?
            })
        })
        .ok_or_else_value_err(|| {
            format!("Invalid unit {v}. Unit must be one of 'years', 'months', 'weeks', 'days'")
        })
    }
}

/// Full unit for delta diffing (calendar + exact)
#[derive(Debug, Copy, Clone, PartialEq, Eq, PartialOrd, Ord)]
pub(crate) enum DeltaUnit {
    Years = 0,
    Months = 1,
    Weeks = 2,
    Days = 3,
    Hours = 4,
    Minutes = 5,
    Seconds = 6,
    Nanoseconds = 7,
}

impl DeltaUnit {
    pub(crate) fn from_py(v: PyObj, state: &State) -> PyResult<Self> {
        find_interned(v, |v, eq| {
            Some(if eq(v, state.str_years) {
                DeltaUnit::Years
            } else if eq(v, state.str_months) {
                DeltaUnit::Months
            } else if eq(v, state.str_weeks) {
                DeltaUnit::Weeks
            } else if eq(v, state.str_days) {
                DeltaUnit::Days
            } else if eq(v, state.str_hours) {
                DeltaUnit::Hours
            } else if eq(v, state.str_minutes) {
                DeltaUnit::Minutes
            } else if eq(v, state.str_seconds) {
                DeltaUnit::Seconds
            } else if eq(v, state.str_nanoseconds) {
                DeltaUnit::Nanoseconds
            } else {
                None?
            })
        })
        .ok_or_else_value_err(|| format!(
            "Invalid unit {v}. Unit must be one of 'years', 'months', 'weeks', 'days', 'hours', 'minutes', 'seconds', 'nanoseconds'"
        ))
    }

    pub(crate) fn to_exact(self, days_are_24h: bool) -> Result<ExactUnit, CalUnit> {
        Ok(match self {
            DeltaUnit::Weeks if days_are_24h => ExactUnit::Weeks,
            DeltaUnit::Days if days_are_24h => ExactUnit::Days,
            DeltaUnit::Hours => ExactUnit::Hours,
            DeltaUnit::Minutes => ExactUnit::Minutes,
            DeltaUnit::Seconds => ExactUnit::Seconds,
            DeltaUnit::Nanoseconds => ExactUnit::Nanoseconds,
            DeltaUnit::Years => return Err(CalUnit::Years),
            DeltaUnit::Months => return Err(CalUnit::Months),
            DeltaUnit::Weeks => return Err(CalUnit::Weeks),
            DeltaUnit::Days => return Err(CalUnit::Days),
        })
    }

    /// Parse from Python string, but only allow exact (non-calendar) units + days/weeks.
    pub(crate) fn from_exact_py(v: PyObj, state: &State) -> PyResult<Self> {
        find_interned(v, |v, eq| {
            Some(if eq(v, state.str_weeks) {
                DeltaUnit::Weeks
            } else if eq(v, state.str_days) {
                DeltaUnit::Days
            } else if eq(v, state.str_hours) {
                DeltaUnit::Hours
            } else if eq(v, state.str_minutes) {
                DeltaUnit::Minutes
            } else if eq(v, state.str_seconds) {
                DeltaUnit::Seconds
            } else if eq(v, state.str_nanoseconds) {
                DeltaUnit::Nanoseconds
            } else {
                None?
            })
        })
        .ok_or_else_value_err(|| format!(
            "Invalid unit {v}. Unit must be one of 'weeks', 'days', 'hours', 'minutes', 'seconds', 'nanoseconds'"
        ))
    }

    pub(crate) fn to_cal(self) -> Option<CalUnit> {
        match self {
            DeltaUnit::Years => Some(CalUnit::Years),
            DeltaUnit::Months => Some(CalUnit::Months),
            DeltaUnit::Weeks => Some(CalUnit::Weeks),
            DeltaUnit::Days => Some(CalUnit::Days),
            _ => None,
        }
    }

    /// Nanoseconds per unit (for exact units)
    fn ns_per_unit(self) -> i64 {
        match self {
            DeltaUnit::Hours => 3_600_000_000_000,
            DeltaUnit::Minutes => 60_000_000_000,
            DeltaUnit::Seconds => 1_000_000_000,
            DeltaUnit::Nanoseconds => 1,
            // weeks/days also have ns equivalents for time-based computations
            DeltaUnit::Weeks => 604_800_000_000_000,
            DeltaUnit::Days => 86_400_000_000_000,
            _ => unreachable!("calendar units have no fixed ns"),
        }
    }

    /// Reconstruct from bit index. Only valid for 0..=7.
    fn from_index(i: u8) -> Self {
        match i {
            0 => DeltaUnit::Years,
            1 => DeltaUnit::Months,
            2 => DeltaUnit::Weeks,
            3 => DeltaUnit::Days,
            4 => DeltaUnit::Hours,
            5 => DeltaUnit::Minutes,
            6 => DeltaUnit::Seconds,
            7 => DeltaUnit::Nanoseconds,
            _ => unreachable!(),
        }
    }

    // TODO HIGH: should be only on CalUnit
    fn diff_into(
        self,
        a: Date,
        trunc: InterimDate,
        inc: i32,
        sign: i8,
        result: &mut ItemizedDateDelta,
    ) -> Option<(InterimDate, InterimDate)> {
        match self {
            DeltaUnit::Years => {
                let (v, t, e) = years_diff(a, trunc, inc, sign)?;
                result.years = DeltaField::new_unchecked(v);
                Some((t, e))
            }
            DeltaUnit::Months => {
                let (v, t, e) = months_diff(a, trunc, inc, sign)?;
                result.months = DeltaField::new_unchecked(v);
                Some((t, e))
            }
            DeltaUnit::Weeks => {
                let (v, t, e) = weeks_diff(a, trunc, inc, sign)?;
                result.weeks = DeltaField::new_unchecked(v);
                Some((t, e))
            }
            DeltaUnit::Days => {
                let (v, t, e) = days_diff(a, trunc, inc, sign)?;
                result.days = DeltaField::new_unchecked(v);
                Some((t, e))
            }
            _ => unreachable!(),
        }
    }
}

// TODO: make this log 2
/// Full unit for delta diffing (calendar + exact)
#[derive(Debug, Copy, Clone, PartialEq, Eq, PartialOrd, Ord)]
pub(crate) enum ExactUnit {
    // Values for compatibility with DeltaUnit
    Weeks = 2,
    Days = 3,
    Hours = 4,
    Minutes = 5,
    Seconds = 6,
    Nanoseconds = 7,
}

impl ExactUnit {
    /// Nanoseconds per unit (for exact units)
    pub(crate) fn in_nanos(self) -> i64 {
        match self {
            ExactUnit::Hours => 3_600_000_000_000,
            ExactUnit::Minutes => 60_000_000_000,
            ExactUnit::Seconds => 1_000_000_000,
            ExactUnit::Nanoseconds => 1,
            // weeks/days also have ns equivalents for time-based computations
            ExactUnit::Weeks => 604_800_000_000_000,
            ExactUnit::Days => 86_400_000_000_000,
        }
    }
}

/// Bitfield set of units. Bit 0 = Years, bit 7 = Nanoseconds.
#[derive(Debug, Copy, Clone, PartialEq, Eq)]
pub(crate) struct UnitSet(u8);

const CAL_MASK: u8 = 0x0F; // bits 0-3: Years, Months, Weeks, Days

impl UnitSet {
    pub(crate) const EMPTY: Self = Self(0);

    pub(crate) fn insert(&mut self, unit: DeltaUnit) {
        self.0 |= 1 << unit as u8;
    }

    pub(crate) fn insert_cal(&mut self, unit: CalUnit) {
        self.0 |= 1 << unit as u8;
    }

    pub(crate) fn contains(self, unit: DeltaUnit) -> bool {
        self.0 & (1 << unit as u8) != 0
    }

    pub(crate) fn is_empty(self) -> bool {
        self.0 == 0
    }

    /// Whether the set contains days or weeks
    pub(crate) fn has_days_or_weeks(self) -> bool {
        self.0 & ((1 << DeltaUnit::Days as u8) | (1 << DeltaUnit::Weeks as u8)) != 0
    }

    /// The calendar-only subset (years, months, weeks, days)
    pub(crate) fn cal_only(self) -> Self {
        Self(self.0 & CAL_MASK)
    }

    /// The exact-only subset (hours, minutes, seconds, nanoseconds)
    pub(crate) fn exact_only(self) -> Self {
        Self(self.0 & !CAL_MASK)
    }

    /// The smallest (highest-numbered) unit in the set
    pub(crate) fn smallest(self) -> DeltaUnit {
        debug_assert!(!self.is_empty());
        DeltaUnit::from_index(7 - self.0.leading_zeros() as u8)
    }

    /// Iterate units in order (largest first: Years → Nanoseconds)
    pub(crate) fn iter(self) -> UnitSetIter {
        UnitSetIter(self.0)
    }

    /// Combine two unit sets
    pub(crate) fn union(self, other: Self) -> Self {
        Self(self.0 | other.0)
    }
}

/// Iterator over set bits in a UnitSet, yielding DeltaUnit in order.
pub(crate) struct UnitSetIter(u8);

impl Iterator for UnitSetIter {
    type Item = DeltaUnit;

    fn next(&mut self) -> Option<DeltaUnit> {
        if self.0 == 0 {
            return None;
        }
        let bit = self.0.trailing_zeros() as u8;
        self.0 &= self.0 - 1; // clear lowest set bit
        Some(DeltaUnit::from_index(bit))
    }
}

/// Parsed since/until arguments for full delta (calendar + exact)
pub(crate) struct FullSinceUntilArgs {
    pub(crate) units: UnitSet,
    pub(crate) single_unit_mode: bool,
    pub(crate) round_mode: round::Mode,
    // FUTURE: consider making round_increment a TimeDelta instead of i32
    // to support larger increments and TimeDelta-based rounding
    pub(crate) round_increment: i32,
}

impl FullSinceUntilArgs {
    /// Split into calendar and exact unit sets
    pub(crate) fn split_cal_exact(&self) -> (UnitSet, UnitSet) {
        (self.units.cal_only(), self.units.exact_only())
    }

    pub(crate) fn smallest_unit(&self) -> DeltaUnit {
        self.units.smallest()
    }
}

/// Parse optional round_mode and round_increment keyword arguments.
pub(crate) fn parse_rounding_kwargs(
    state: &State,
    round_mode_obj: Option<PyObj>,
    round_inc_obj: Option<PyObj>,
) -> PyResult<(round::Mode, i32)> {
    let round_mode = round_mode_obj
        .map(|v| {
            round::Mode::from_py_named(
                "round_mode",
                v,
                state.str_floor,
                state.str_ceil,
                state.str_trunc,
                state.str_expand,
                state.str_half_floor,
                state.str_half_ceil,
                state.str_half_even,
                state.str_half_trunc,
                state.str_half_expand,
            )
        })
        .transpose()?
        .unwrap_or(round::Mode::Trunc);

    let round_increment = round_inc_obj
        .map(|v| {
            let inc = v
                .cast_allow_subclass::<PyInt>()
                .ok_or_type_err("round_increment must be an integer")?
                .to_i64()?;
            if inc <= 0 || inc > i32::MAX as i64 {
                raise_value_err("round_increment must be a positive integer")?;
            }
            Ok(inc as i32)
        })
        .transpose()?
        .unwrap_or(1);

    Ok((round_mode, round_increment))
}

/// Parse the kwargs for full since()/until() (PlainDateTime, OffsetDateTime, ZonedDateTime).
pub(crate) fn parse_full_since_kwargs(
    state: &State,
    args: &[PyObj],
    kwargs: &mut IterKwargs,
) -> PyResult<FullSinceUntilArgs> {
    let &State {
        str_unit,
        str_units,
        str_round_mode,
        str_round_increment,
        str_floor,
        str_ceil,
        str_trunc,
        str_expand,
        str_half_floor,
        str_half_ceil,
        str_half_even,
        str_half_trunc,
        str_half_expand,
        ..
    } = state;

    if args.len() > 1 {
        raise_type_err(format!(
            "since()/until() takes at most 1 positional argument, got {}",
            args.len()
        ))?;
    }
    let nargs = args.len() + kwargs.len() as usize;
    if nargs < 1 || nargs > 5 {
        raise_type_err(format!(
            "since()/until() takes 1 to 5 arguments, got {nargs}",
        ))?;
    }
    let mut unit_obj: Option<PyObj> = None;
    let mut units_obj: Option<PyObj> = None;
    let mut round_mode_obj: Option<PyObj> = None;
    let mut round_inc_obj: Option<PyObj> = None;

    handle_kwargs("since()/until()", kwargs, |key, value, eq| {
        if eq(key, str_unit) {
            unit_obj = Some(value);
        } else if eq(key, str_units) {
            units_obj = Some(value);
        } else if eq(key, str_round_mode) {
            round_mode_obj = Some(value);
        } else if eq(key, str_round_increment) {
            round_inc_obj = Some(value);
        } else {
            return Ok(false);
        }
        Ok(true)
    })?;

    let (units, single_unit_mode) = match (unit_obj, units_obj) {
        (Some(_), Some(_)) => {
            return raise_type_err("Cannot specify both 'unit' and 'units'");
        }
        (Some(u), None) => {
            let unit = DeltaUnit::from_py(u, state)?;
            let mut set = UnitSet::EMPTY;
            set.insert(unit);
            (set, true)
        }
        (None, Some(seq)) => (parse_delta_units_sequence(seq, state)?, false),
        (None, None) => {
            return raise_type_err("Must specify either 'unit' or 'units'");
        }
    };

    let round_mode = round_mode_obj
        .map(|v| {
            round::Mode::from_py_named(
                "round_mode",
                v,
                str_floor,
                str_ceil,
                str_trunc,
                str_expand,
                str_half_floor,
                str_half_ceil,
                str_half_even,
                str_half_trunc,
                str_half_expand,
            )
        })
        .transpose()?
        .unwrap_or(round::Mode::Trunc);

    let round_increment = round_inc_obj
        .map(|v| {
            let inc = v
                .cast_allow_subclass::<PyInt>()
                .ok_or_type_err("round_increment must be an integer")?
                .to_i64()?;
            if inc <= 0 || inc > i32::MAX as i64 {
                raise_value_err("round_increment must be a positive integer")?;
            }
            Ok(inc as i32)
        })
        .transpose()?
        .unwrap_or(1);

    Ok(FullSinceUntilArgs {
        units,
        single_unit_mode,
        round_mode,
        round_increment,
    })
}

/// Parse a Python sequence of full delta unit strings.
pub(crate) fn parse_delta_units_sequence(seq: PyObj, state: &State) -> PyResult<UnitSet> {
    let len = seq.seq_len().ok_or_type_err("Units must be a sequence")?;
    if len == 0 {
        raise_value_err("'units' cannot be an empty sequence")?;
    }
    if len > 8 {
        raise_value_err("Too many units (max 8)")?;
    }

    let mut units = UnitSet::EMPTY;
    let mut prev_idx: Option<usize> = None;

    for i in 0..len {
        let item = seq.seq_getitem(i)?;
        let unit = DeltaUnit::from_py(item.borrow(), state)?;
        let idx = unit as usize;

        if let Some(prev) = prev_idx {
            if idx == prev {
                raise_value_err("units cannot contain duplicates")?;
            }
            if idx < prev {
                raise_value_err("units must be in decreasing order of size")?;
            }
        }
        units.insert(unit);
        prev_idx = Some(idx);
    }

    Ok(units)
}

// TODO LOW does foo.since(bar, unit='nanoseconds') handle correctly?
// TODO LOW naming
pub(crate) fn time_delta_in_single_unit(
    td: TimeDelta,
    unit: DeltaUnit,
    round_increment: i32,
    round_mode: round::Mode,
) -> PyReturn {
    // TODO MEDIUM: cleaner, clarify only time units allowed
    debug_assert!(!unit.to_cal().is_some());
    let increment_ns = unit.ns_per_unit() * round_increment as i64;
    let rounded = td
        .round(increment_ns, round_mode)
        .ok_or_value_err("Rounding result out of range")?;
    // OPTIMIZE
    (rounded.total_nanos() / unit.ns_per_unit() as i128).to_py()
}

/// Decompose a TimeDelta into the given exact units.
/// Applies rounding to the smallest unit first, then does successive divmod.
pub(crate) fn time_delta_in_units(
    td: TimeDelta,
    units: UnitSet,
    round_increment: i32,
    round_mode: round::Mode,
) -> Option<ItemizedDelta> {
    // Perform the rounding
    let smallest = units.smallest();
    let increment_ns = smallest.ns_per_unit() * round_increment as i64;
    let rounded = td.round(increment_ns, round_mode)?;

    let mut remaining = rounded.total_nanos();
    let mut target = ItemizedDelta::UNSET;

    type Setter = fn(&mut ItemizedDelta, i128);

    let fields: &[(DeltaUnit, Setter)] = &[
        (DeltaUnit::Weeks, |t, v| {
            t.weeks = DeltaField::new_unchecked(v as i32)
        }),
        (DeltaUnit::Days, |t, v| {
            t.days = DeltaField::new_unchecked(v as i32)
        }),
        (DeltaUnit::Hours, |t, v| {
            t.hours = DeltaField::new_unchecked(v as i32)
        }),
        (DeltaUnit::Minutes, |t, v| {
            t.minutes = DeltaField::new_unchecked(v as i64)
        }),
        (DeltaUnit::Seconds, |t, v| {
            t.seconds = DeltaField::new_unchecked(v as i64)
        }),
    ];

    for (unit, setter) in fields {
        if units.contains(*unit) {
            let per = unit.ns_per_unit() as i128;
            let value = remaining / per;
            remaining %= per;
            setter(&mut target, value);
        }
    }

    if units.contains(DeltaUnit::Nanoseconds) {
        target.nanos = DeltaField::new_unchecked(remaining as i32);
    }

    Some(target)
}

// TODO MEDIUM Copy?
/// Parsed since/until arguments for Date
pub(crate) struct SinceUntilArgs {
    pub(crate) units: UnitSet,
    pub(crate) single_unit_mode: bool, // TODO HIGH: this should be expressed in enum
    pub(crate) round_mode: round::Mode,
    pub(crate) round_increment: i32,
}

/// Parse the kwargs for Date.since()/until().
/// `args[0]` is the positional arg `b` (already extracted by caller).
pub(crate) fn parse_date_since_kwargs(
    state: &State,
    args: &[PyObj],
    kwargs: &mut IterKwargs,
) -> PyResult<SinceUntilArgs> {
    let &State {
        str_unit,
        str_units,
        str_round_mode,
        str_round_increment,
        str_floor,
        str_ceil,
        str_trunc,
        str_expand,
        str_half_floor,
        str_half_ceil,
        str_half_even,
        str_half_trunc,
        str_half_expand,
        ..
    } = state;

    if args.len() > 1 {
        raise_type_err(format!(
            "since()/until() takes at most 1 positional argument, got {}",
            args.len()
        ))?;
    }
    let nargs = args.len() + kwargs.len() as usize;
    if nargs < 1 || nargs > 5 {
        raise_type_err(format!(
            "since()/until() takes 1 to 5 arguments, got {nargs}",
        ))?;
    }
    let mut unit_obj: Option<PyObj> = None;
    let mut units_obj: Option<PyObj> = None;
    let mut round_mode_obj: Option<PyObj> = None;
    let mut round_inc_obj: Option<PyObj> = None;

    handle_kwargs("since()/until()", kwargs, |key, value, eq| {
        if eq(key, str_unit) {
            unit_obj = Some(value);
        } else if eq(key, str_units) {
            units_obj = Some(value);
        } else if eq(key, str_round_mode) {
            round_mode_obj = Some(value);
        } else if eq(key, str_round_increment) {
            round_inc_obj = Some(value);
        } else {
            return Ok(false);
        }
        Ok(true)
    })?;

    // Parse unit/units
    let (units, single_unit_mode) = match (unit_obj, units_obj) {
        (Some(_), Some(_)) => {
            return raise_type_err("Cannot specify both 'unit' and 'units'");
        }
        (Some(u), None) => {
            let unit = CalUnit::from_py(u, state)?;
            let mut set = UnitSet::EMPTY;
            set.insert_cal(unit);
            (set, true)
        }
        (None, Some(seq)) => (parse_cal_units_sequence(seq, state)?, false),
        (None, None) => {
            return raise_type_err("Must specify either 'unit' or 'units'");
        }
    };

    // Parse round_mode
    let round_mode = round_mode_obj
        .map(|v| {
            round::Mode::from_py_named(
                "round_mode",
                v,
                str_floor,
                str_ceil,
                str_trunc,
                str_expand,
                str_half_floor,
                str_half_ceil,
                str_half_even,
                str_half_trunc,
                str_half_expand,
            )
        })
        .transpose()?
        .unwrap_or(round::Mode::Trunc);

    // TODO LATER: do we have tests that have this huge increment values?
    // Parse round_increment
    let round_increment = round_inc_obj
        .map(|v| {
            let inc = v
                .cast_allow_subclass::<PyInt>()
                .ok_or_type_err("round_increment must be an integer")?
                .to_i64()?;
            if inc <= 0 || inc > i32::MAX as i64 {
                raise_value_err("round_increment must be a positive integer")?;
            }
            Ok(inc as i32)
        })
        .transpose()?
        .unwrap_or(1);

    Ok(SinceUntilArgs {
        units,
        single_unit_mode,
        round_mode,
        round_increment,
    })
}

/// Parse a Python sequence of unit strings into a UnitSet of CalUnits.
/// Validates ordering (decreasing) and no duplicates.
pub(crate) fn parse_cal_units_sequence(seq: PyObj, state: &State) -> PyResult<UnitSet> {
    let len = seq.seq_len().ok_or_type_err("Units must be a sequence")?;
    if len == 0 {
        raise_value_err("'units' cannot be an empty sequence")?;
    }
    if len > 4 {
        raise_value_err("Too many units (max 4 for date units)")?;
    }

    let mut units = UnitSet::EMPTY;
    let mut prev_unit: Option<CalUnit> = None;

    for i in 0..len {
        let item = seq.seq_getitem(i)?;
        let unit = CalUnit::from_py(item.borrow(), state)?;

        if let Some(prev) = prev_unit {
            if unit == prev {
                raise_value_err("units cannot contain duplicates")?;
            }
            // Note ordering is inverted because 0=Years is largest, 3=Days is smallest
            if unit < prev {
                raise_value_err("units must be in decreasing order of size")?;
            }
        }
        units.insert_cal(unit);
        prev_unit = Some(unit);
    }

    // FYI: I was able to remove the bool()
    // The bool indicates single-unit mode (only used in parse_since_until_args)
    Ok(units)
}

impl DeltaUnit {}

/// Compute multi-unit date difference, progressively applying each unit.
/// Returns (results_per_unit, trunc_date, expand_date).
/// NOTE: the reason that `sign` is passed in separately instead of just
/// being deduced from the order of `a` and `b` is that the function needs
/// to be used with identical dates but with different times of day.
/// The sign determines the direction of rounding.
pub(crate) fn date_diff(
    a: Date,
    b: Date,
    round_increment: i32,
    units: UnitSet, // time units ignored
    sign: i8,
) -> Option<(ItemizedDateDelta, InterimDate, InterimDate)> {
    let smallest = units.smallest();
    let mut result = ItemizedDateDelta::UNSET;
    let mut trunc = b.into();
    let mut expand = a.into();
    for unit in units.cal_only().iter() {
        let inc = if unit == smallest { round_increment } else { 1 };
        let (new_trunc, new_expand) = unit.diff_into(a, trunc, inc, sign, &mut result)?;
        trunc = new_trunc;
        expand = new_expand;
    }

    Some((result, trunc, expand))
}

// TODO HIGH: remove?
pub(crate) fn date_diff_single_unit(
    a: Date,
    b: Date,
    round_increment: i32,
    unit: CalUnit,
    sign: i8,
) -> Option<CalDiff> {
    Some(match unit {
        CalUnit::Years => years_diff(a, b.into(), round_increment, sign)?,
        CalUnit::Months => months_diff(a, b.into(), round_increment, sign)?,
        CalUnit::Weeks => weeks_diff(a, b.into(), round_increment, sign)?,
        CalUnit::Days => days_diff(a, b.into(), round_increment, sign)?,
    })
}

pub(crate) fn round_by_days(
    value: i32,
    target: Date,
    trunc: Date,
    expand: Date,
    mode: round::Mode,
    increment: i32,
    sign: i8,
) -> i32 {
    let abs_mode = mode.to_abs_with_sign(sign);
    if abs_mode == round::AbsMode::Trunc {
        value
    } else {
        let trunc_date = trunc.unix_days();
        let r = target.unix_days().diff(trunc_date).abs().get();
        let e = expand.unix_days().diff(trunc_date).abs().get();
        debug_assert!(e > 0, "expand and trunc dates cannot be the same");
        round(value, r > 0, r.cmp(&(e - r)), abs_mode, increment, sign)
    }
}

// dedup with ItemizedDateDelta method
pub(crate) fn round_by_time(
    value: i32,
    target: Instant,
    trunc: Instant,
    expand: Instant,
    mode: round::Mode,
    increment: i32,
    sign: i8,
) -> i32 {
    let abs_mode = mode.to_abs_with_sign(sign);
    // Only run the rounding logic if the rounding mode isn't already trunc
    // since that mode doesn't require any work.
    if abs_mode == round::AbsMode::Trunc {
        // Truncated value (the common case)
        value
    } else {
        let r = target.diff(trunc).abs();
        let e = expand.diff(trunc).abs();
        debug_assert!(!e.is_zero());
        // r.cmp(e - r) is equivalent to (r * 2).cmp(e), avoiding overflow
        let half_cmp = r.cmp(&(e.checked_add(-r).unwrap()));
        round(value, !r.is_zero(), half_cmp, abs_mode, increment, sign)
    }
}

fn round(
    trunc_value: i32,
    has_remainder: bool,
    half_cmp: Ordering,
    mode: round::AbsMode,
    increment: i32,
    sign: i8,
) -> i32 {
    debug_assert!(increment > 0);
    let do_expand = match mode {
        round::AbsMode::Trunc => unreachable!("trunc should be handled by caller"),
        round::AbsMode::Expand => has_remainder,
        round::AbsMode::HalfEven => {
            half_cmp == Ordering::Greater
                || (half_cmp == Ordering::Equal
                    && !(trunc_value / increment).unsigned_abs().is_multiple_of(2))
        }
        round::AbsMode::HalfTrunc => half_cmp == Ordering::Greater,
        round::AbsMode::HalfExpand => half_cmp != Ordering::Less,
    };

    trunc_value
        + if do_expand {
            increment * sign as i32
        } else {
            0
        }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn d(year: u16, month: u8, day: u8) -> Date {
        Date::new(Year::new(year).unwrap(), Month::new(month).unwrap(), day).unwrap()
    }

    #[test]
    fn test_years_diff_basic() {
        let (diff, _, _) = years_diff(d(2023, 4, 15), d(2020, 1, 1).into(), 1, 1).unwrap();
        assert_eq!(diff, 3);
    }

    #[test]
    fn test_years_diff_leap_day() {
        // Feb 29, 2020 to Feb 28, 2021: pending leap day resolves to Feb 28
        let (diff, trunc, _) = years_diff(d(2021, 2, 28), d(2020, 2, 29).into(), 1, 1).unwrap();
        assert_eq!(diff, 1);
        assert_eq!(trunc.resolve(), d(2021, 2, 28));
    }

    #[test]
    fn test_months_diff_basic() {
        let (diff, _, _) = months_diff(d(2023, 4, 15), d(2023, 1, 1).into(), 1, 1).unwrap();
        assert_eq!(diff, 3);
    }

    #[test]
    fn test_days_diff_basic() {
        let (diff, _, _) = days_diff(d(2023, 1, 10), d(2023, 1, 1).into(), 1, 1).unwrap();
        assert_eq!(diff, 9);
    }

    #[test]
    fn test_date_diff_years_months() {
        let mut units = UnitSet::EMPTY;
        units.insert_cal(CalUnit::Years);
        units.insert_cal(CalUnit::Months);
        let (results, _, _) = date_diff(d(2023, 4, 15), d(2020, 1, 1), 1, units, 1).unwrap();
        assert_eq!(results[CalUnit::Years as usize], 3);
        assert_eq!(results[CalUnit::Months as usize], 3);
    }

    #[test]
    fn test_custom_round_expand() {
        // has_remainder=true, half_cmp irrelevant for Expand
        assert_eq!(
            custom_round(3, true, Ordering::Less, round::AbsMode::Expand, 1),
            4
        );
        // has_remainder=false
        assert_eq!(
            custom_round(3, false, Ordering::Less, round::AbsMode::Expand, 1),
            3
        );
    }

    #[test]
    fn test_custom_round_half_even() {
        // exact tie (Equal), trunc_value/inc is odd → expand
        assert_eq!(
            custom_round(3, true, Ordering::Equal, round::AbsMode::HalfEven, 1),
            4
        );
        // exact tie (Equal), trunc_value/inc is even → trunc
        assert_eq!(
            custom_round(4, true, Ordering::Equal, round::AbsMode::HalfEven, 1),
            4
        );
        // above tie → expand
        assert_eq!(
            custom_round(4, true, Ordering::Greater, round::AbsMode::HalfEven, 1),
            5
        );
        // below tie → trunc
        assert_eq!(
            custom_round(4, true, Ordering::Less, round::AbsMode::HalfEven, 1),
            4
        );
    }
}
