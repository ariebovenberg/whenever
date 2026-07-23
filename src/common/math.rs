//! Calendar difference logic for since()/until() methods.
//! Rust equivalent of _math.py's date_diff and custom_round.
use std::cmp::Ordering;
use std::num::NonZeroU128;

use crate::{
    common::round,
    domain::{
        date::Date,
        instant::Instant,
        itemized_date_delta::ItemizedDateDelta,
        scalar::{DeltaDays, DeltaField, DeltaMonths, Month, Year, *},
        time_delta::TimeDelta,
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
type CalendarDiff = (i32, InterimDate, InterimDate);

fn years_diff(
    a: Date,
    b: InterimDate,
    increment: CalendarIncrement,
    neg: bool,
) -> Option<CalendarDiff> {
    let diff = increment.truncate(a.year.get() as i32 - b.year.get() as i32);
    let shift = b.replace_year(b.year.add_i32(diff)?);

    let overshot = if diff > 0 {
        shift.resolve() > a
    } else if diff < 0 {
        shift.resolve() < a
    } else {
        false
    };

    if overshot {
        let adj = diff - increment.get().negate_if(neg);
        let adj_year = b.year.add_i32(adj)?;
        Some((adj, b.replace_year(adj_year), shift))
    } else {
        let exp_year = b.year.add_i32(diff + increment.get().negate_if(neg))?;
        Some((diff, shift, b.replace_year(exp_year)))
    }
}

fn months_diff(
    a: Date,
    b: InterimDate,
    increment: CalendarIncrement,
    neg: bool,
) -> Option<CalendarDiff> {
    let diff = increment.truncate(
        (a.year.get() as i32 - b.year.get() as i32) * 12 + (a.month as i32 - b.month as i32),
    );
    let shift = b.shift_months(diff)?;

    let overshot = if diff > 0 {
        shift > a
    } else if diff < 0 {
        shift < a
    } else {
        false
    };

    if overshot {
        let adj = diff - increment.get().negate_if(neg);
        Some((adj, b.shift_months(adj)?.into(), shift.into()))
    } else {
        Some((
            diff,
            shift.into(),
            b.shift_months(diff + increment.get().negate_if(neg))?
                .into(),
        ))
    }
}

fn weeks_diff(
    a: Date,
    b: InterimDate,
    increment: CalendarIncrement,
    neg: bool,
) -> Option<CalendarDiff> {
    let (days, trunc, expand) = days_diff(a, b, CalendarIncrement::new(increment.get() * 7)?, neg)?;
    Some((days / 7, trunc, expand))
}

fn days_diff(
    a: Date,
    b: InterimDate,
    increment: CalendarIncrement,
    neg: bool,
) -> Option<CalendarDiff> {
    let b_resolved = b.resolve();
    let delta = a.unix_days().diff(b_resolved.unix_days());
    // SAFETY: truncated value (towards zero) never overflows
    let trunc_value = DeltaDays::new_unchecked(increment.truncate(delta.get()));

    let trunc_date = b_resolved.shift_days(trunc_value)?;
    let expand_date = trunc_date.shift_days(DeltaDays::new(increment.get().negate_if(neg))?)?;
    Some((trunc_value.get(), trunc_date.into(), expand_date.into()))
}

/// Calendar unit for date difference operations.
#[derive(Debug, Copy, Clone, PartialEq, Eq, PartialOrd, Ord)]
pub(crate) enum CalendarUnit {
    Years,
    Months,
    Weeks,
    Days,
}

impl CalendarUnit {
    pub(crate) fn from_py(v: PyObj, state: &State) -> PyResult<Self> {
        find_interned(v, |v, eq| {
            Some(if eq(v, *state.str_years) {
                CalendarUnit::Years
            } else if eq(v, *state.str_months) {
                CalendarUnit::Months
            } else if eq(v, *state.str_weeks) {
                CalendarUnit::Weeks
            } else if eq(v, *state.str_days) {
                CalendarUnit::Days
            } else {
                None?
            })
        })
        .ok_or_else_value_err(|| {
            format!("Invalid unit {v}. Unit must be one of 'years', 'months', 'weeks', 'days'")
        })
    }

    fn diff_into(
        self,
        a: Date,
        trunc: InterimDate,
        inc: CalendarIncrement,
        neg: bool,
        result: &mut ItemizedDateDelta,
    ) -> Option<(InterimDate, InterimDate)> {
        match self {
            CalendarUnit::Years => {
                let (v, t, e) = years_diff(a, trunc, inc, neg)?;
                result.years = DeltaField::new_unchecked(v);
                Some((t, e))
            }
            CalendarUnit::Months => {
                let (v, t, e) = months_diff(a, trunc, inc, neg)?;
                result.months = DeltaField::new_unchecked(v);
                Some((t, e))
            }
            CalendarUnit::Weeks => {
                let (v, t, e) = weeks_diff(a, trunc, inc, neg)?;
                result.weeks = DeltaField::new_unchecked(v);
                Some((t, e))
            }
            CalendarUnit::Days => {
                let (v, t, e) = days_diff(a, trunc, inc, neg)?;
                result.days = DeltaField::new_unchecked(v);
                Some((t, e))
            }
        }
    }

    pub(crate) fn field(self, d: &mut ItemizedDateDelta) -> &mut DeltaField<i32> {
        match self {
            CalendarUnit::Years => &mut d.years,
            CalendarUnit::Months => &mut d.months,
            CalendarUnit::Weeks => &mut d.weeks,
            CalendarUnit::Days => &mut d.days,
        }
    }

    pub(crate) fn from_index_unchecked(i: u8) -> Self {
        match i {
            0 => CalendarUnit::Years,
            1 => CalendarUnit::Months,
            2 => CalendarUnit::Weeks,
            3 => CalendarUnit::Days,
            _ => panic!("invalid calendar unit index"),
        }
    }
}

/// Bitfield set of calendar units. Bit 0 = Years, bit 3 = Days. Exact units (Hours, Minutes,
/// Seconds, Nanoseconds, etc.) are not included.
#[derive(Copy, Clone, PartialEq, Eq)]
pub(crate) struct CalendarUnitSet(u8);

impl std::fmt::Debug for CalendarUnitSet {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        let mut list = f.debug_list();
        for unit in [
            CalendarUnit::Years,
            CalendarUnit::Months,
            CalendarUnit::Weeks,
            CalendarUnit::Days,
        ] {
            if self.0 & (1 << unit as u8) != 0 {
                list.entry(&unit);
            }
        }
        list.finish()
    }
}

impl CalendarUnitSet {
    pub(crate) const EMPTY: Self = Self(0);

    pub(crate) fn insert(&mut self, unit: CalendarUnit) {
        self.0 |= 1 << unit as u8;
    }

    pub(crate) fn is_empty(self) -> bool {
        self.0 == 0
    }

    pub(crate) fn smallest(self) -> CalendarUnit {
        debug_assert!(!self.is_empty());
        CalendarUnit::from_index_unchecked(7 - self.0.leading_zeros() as u8)
    }

    pub(crate) fn from_py(v: PyObj, state: &State) -> PyResult<Self> {
        let mut units = CalendarUnitSet::EMPTY;
        let mut prev: Option<CalendarUnit> = None;

        for item in v.to_tuple()?.iter() {
            let unit = CalendarUnit::from_py(item, state)?;

            if let Some(p) = prev {
                if p == unit {
                    raise_value_err("units cannot contain duplicates")?;
                }
                if p > unit {
                    raise_value_err("units must be in decreasing order of size")?;
                }
            }
            units.insert(unit);
            prev = Some(unit);
        }

        if units.is_empty() {
            raise_value_err("units cannot be empty")?;
        }
        Ok(units)
    }

    pub(crate) fn iter(self) -> CalendarUnitSetIter {
        CalendarUnitSetIter(self.0)
    }
}

/// Iterator over set bits in a CalendarUnitSet, yielding CalendarUnit in order.
/// Units are returned in decreasing order of size (Years → Days).
pub(crate) struct CalendarUnitSetIter(u8);

impl Iterator for CalendarUnitSetIter {
    type Item = CalendarUnit;

    fn next(&mut self) -> Option<CalendarUnit> {
        if self.0 == 0 {
            return None;
        }
        let bit = self.0.trailing_zeros() as u8;
        self.0 &= self.0 - 1; // clear lowest set bit
        Some(CalendarUnit::from_index_unchecked(bit))
    }
}

/// Unit accepted by datetime difference operations.
#[derive(Debug, Copy, Clone, PartialEq, Eq, PartialOrd, Ord)]
#[repr(u8)]
pub(crate) enum DifferenceUnit {
    Years,
    Months,
    Weeks,
    Days,
    Hours,
    Minutes,
    Seconds,
    Nanoseconds,
}

impl DifferenceUnit {
    pub(crate) fn from_py(v: PyObj, state: &State) -> PyResult<Self> {
        find_interned(v, |v, eq| {
            Some(if eq(v, *state.str_years) {
                DifferenceUnit::Years
            } else if eq(v, *state.str_months) {
                DifferenceUnit::Months
            } else if eq(v, *state.str_weeks) {
                DifferenceUnit::Weeks
            } else if eq(v, *state.str_days) {
                DifferenceUnit::Days
            } else if eq(v, *state.str_hours) {
                DifferenceUnit::Hours
            } else if eq(v, *state.str_minutes) {
                DifferenceUnit::Minutes
            } else if eq(v, *state.str_seconds) {
                DifferenceUnit::Seconds
            } else if eq(v, *state.str_nanoseconds) {
                DifferenceUnit::Nanoseconds
            } else {
                None?
            })
        })
        .ok_or_else_value_err(|| format!(
            "Invalid unit {v}. Unit must be one of 'years', 'months', 'weeks', 'days', 'hours', 'minutes', 'seconds', 'nanoseconds'"
        ))
    }

    pub(crate) fn to_exact(self, days_are_24h: bool) -> Result<ExactUnit, CalendarUnit> {
        Ok(match self {
            DifferenceUnit::Weeks if days_are_24h => ExactUnit::Weeks,
            DifferenceUnit::Days if days_are_24h => ExactUnit::Days,
            DifferenceUnit::Hours => ExactUnit::Hours,
            DifferenceUnit::Minutes => ExactUnit::Minutes,
            DifferenceUnit::Seconds => ExactUnit::Seconds,
            DifferenceUnit::Nanoseconds => ExactUnit::Nanoseconds,
            DifferenceUnit::Years => return Err(CalendarUnit::Years),
            DifferenceUnit::Months => return Err(CalendarUnit::Months),
            DifferenceUnit::Weeks => return Err(CalendarUnit::Weeks),
            DifferenceUnit::Days => return Err(CalendarUnit::Days),
        })
    }

    /// Reconstruct from bit index. Only valid for 0..=7.
    fn from_index(i: u8) -> Self {
        match i {
            0 => DifferenceUnit::Years,
            1 => DifferenceUnit::Months,
            2 => DifferenceUnit::Weeks,
            3 => DifferenceUnit::Days,
            4 => DifferenceUnit::Hours,
            5 => DifferenceUnit::Minutes,
            6 => DifferenceUnit::Seconds,
            7 => DifferenceUnit::Nanoseconds,
            _ => unreachable!(),
        }
    }
}

/// Unit treated as exact, with days fixed at 24 hours.
#[derive(Debug, Copy, Clone, PartialEq, Eq, PartialOrd, Ord)]
#[repr(u8)]
pub(crate) enum ExactUnit {
    Weeks,
    Days,
    Hours,
    Minutes,
    Seconds,
    Milliseconds,
    Microseconds,
    Nanoseconds,
}

impl ExactUnit {
    pub(crate) const fn in_nanos(self) -> i64 {
        match self {
            ExactUnit::Hours => NS_PER_HOUR as i64,
            ExactUnit::Minutes => NS_PER_MINUTE as i64,
            ExactUnit::Seconds => NS_PER_SEC as i64,
            ExactUnit::Nanoseconds => 1,
            ExactUnit::Milliseconds => 1_000_000,
            ExactUnit::Microseconds => 1_000,
            // weeks/days also have ns equivalents when treating days as always 24h
            ExactUnit::Weeks => NS_PER_WEEK as i64,
            ExactUnit::Days => NS_PER_DAY as i64,
        }
    }

    pub(crate) const fn from_index(i: u8) -> Self {
        match i {
            0 => ExactUnit::Weeks,
            1 => ExactUnit::Days,
            2 => ExactUnit::Hours,
            3 => ExactUnit::Minutes,
            4 => ExactUnit::Seconds,
            5 => ExactUnit::Milliseconds,
            6 => ExactUnit::Microseconds,
            7 => ExactUnit::Nanoseconds,
            _ => unreachable!(),
        }
    }

    pub(crate) const fn name(self) -> &'static str {
        match self {
            ExactUnit::Weeks => "weeks",
            ExactUnit::Days => "days",
            ExactUnit::Hours => "hours",
            ExactUnit::Minutes => "minutes",
            ExactUnit::Seconds => "seconds",
            ExactUnit::Milliseconds => "milliseconds",
            ExactUnit::Microseconds => "microseconds",
            ExactUnit::Nanoseconds => "nanoseconds",
        }
    }

    pub(crate) fn parse_py_number(self, v: PyObj) -> PyResult<TimeDelta> {
        // OPTIMIZE: special case for nanoseconds. The rest only needs i64.

        if let Some(i) = v.cast_allow_subclass::<PyInt>() {
            self.parse_py_int(i)
        } else if let Some(f) = v.cast_allow_subclass::<PyFloat>() {
            if self == ExactUnit::Nanoseconds {
                raise_value_err("nanoseconds must be an integer, not a float")?;
            }
            self.parse_py_float(f)
        } else {
            let name = self.name();
            raise_value_err(format!("{name} must be an integer or float"))
        }
    }

    pub(crate) fn parse_py_int(self, i: PyInt) -> PyResult<TimeDelta> {
        TimeDelta::from_nanos(
            i.to_i128()?
                .checked_mul(self.in_nanos() as i128)
                .ok_or_range_err()?,
        )
        .ok_or_range_err()
    }

    pub(crate) fn parse_py_float(self, f: PyFloat) -> PyResult<TimeDelta> {
        TimeDelta::from_nanos_f64(f.to_f64()? * self.in_nanos() as f64).ok_or_range_err()
    }
}

#[derive(Copy, Clone, PartialEq, Eq)]
pub(crate) struct ExactUnitSet(u8);

impl std::fmt::Debug for ExactUnitSet {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        let mut list = f.debug_list();
        for unit in [
            ExactUnit::Weeks,
            ExactUnit::Days,
            ExactUnit::Hours,
            ExactUnit::Minutes,
            ExactUnit::Seconds,
            ExactUnit::Milliseconds,
            ExactUnit::Microseconds,
            ExactUnit::Nanoseconds,
        ] {
            if self.0 & (1 << unit as u8) != 0 {
                list.entry(&unit);
            }
        }
        list.finish()
    }
}

impl ExactUnitSet {
    pub(crate) const EMPTY: Self = Self(0);

    pub(crate) fn insert(&mut self, unit: ExactUnit) {
        self.0 |= 1 << (unit as u8);
    }

    pub(crate) fn contains(self, unit: ExactUnit) -> bool {
        self.0 & (1 << (unit as u8)) != 0
    }

    pub(crate) fn is_empty(self) -> bool {
        self.0 == 0
    }

    pub(crate) fn smallest(self) -> ExactUnit {
        debug_assert!(!self.is_empty());
        ExactUnit::from_index(7 - self.0.leading_zeros() as u8)
    }
}

/// Bitfield set of units. Bit 0 = Years, bit 7 = Nanoseconds.
#[derive(Copy, Clone, PartialEq, Eq)]
pub(crate) struct DifferenceUnitSet(u8);

impl std::fmt::Debug for DifferenceUnitSet {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        let mut list = f.debug_list();
        for unit in [
            DifferenceUnit::Years,
            DifferenceUnit::Months,
            DifferenceUnit::Weeks,
            DifferenceUnit::Days,
            DifferenceUnit::Hours,
            DifferenceUnit::Minutes,
            DifferenceUnit::Seconds,
            DifferenceUnit::Nanoseconds,
        ] {
            if self.0 & (1 << unit as u8) != 0 {
                list.entry(&unit);
            }
        }
        list.finish()
    }
}

const CAL_MASK: u8 = 0x0F; // bits 0-3: Years, Months, Weeks, Days

impl DifferenceUnitSet {
    pub(crate) const EMPTY: Self = Self(0);

    pub(crate) fn insert(&mut self, unit: DifferenceUnit) {
        self.0 |= 1 << unit as u8;
    }

    pub(crate) fn is_empty(self) -> bool {
        self.0 == 0
    }

    pub(crate) fn has_days_or_weeks(self) -> bool {
        self.0 & ((1 << DifferenceUnit::Days as u8) | (1 << DifferenceUnit::Weeks as u8)) != 0
    }

    pub(crate) fn has_calendar(self) -> bool {
        self.0 & CAL_MASK != 0
    }

    pub(crate) fn has_exact(self) -> bool {
        self.0 & 0xF0 != 0 // bits 4-7: Hours, Minutes, Seconds, Nanoseconds
    }

    /// The calendar-only subset (years, months, weeks, days)
    pub(crate) fn calendar_only(self) -> CalendarUnitSet {
        CalendarUnitSet(self.0 & CAL_MASK)
    }

    pub(crate) fn contains(self, unit: DifferenceUnit) -> bool {
        self.0 & (1 << unit as u8) != 0
    }

    /// The exact-only subset (hours, minutes, seconds, nanoseconds).
    /// NOTE: the byte offsets are different between DifferenceUnit and ExactUnit,
    /// so a simple bit shift doesn't work here.
    pub(crate) fn exact_only(self) -> ExactUnitSet {
        let mut exact = ExactUnitSet::EMPTY;
        if self.contains(DifferenceUnit::Hours) {
            exact.insert(ExactUnit::Hours);
        }
        if self.contains(DifferenceUnit::Minutes) {
            exact.insert(ExactUnit::Minutes);
        }
        if self.contains(DifferenceUnit::Seconds) {
            exact.insert(ExactUnit::Seconds);
        }
        if self.contains(DifferenceUnit::Nanoseconds) {
            exact.insert(ExactUnit::Nanoseconds);
        }
        exact
    }

    /// Convert to ExactUnitSet, treating days and weeks as exact units (24h). Returns None if
    /// there are years or months, which cannot be converted to exact units.
    pub(crate) fn to_exact_assuming_24h_days(self) -> Option<ExactUnitSet> {
        if self.contains(DifferenceUnit::Years) || self.contains(DifferenceUnit::Months) {
            None?
        }

        let mut exact = self.exact_only();
        if self.contains(DifferenceUnit::Weeks) {
            exact.insert(ExactUnit::Weeks);
        }
        if self.contains(DifferenceUnit::Days) {
            exact.insert(ExactUnit::Days);
        }

        Some(exact)
    }

    /// The smallest (highest-numbered) unit in the set
    pub(crate) fn smallest(self) -> DifferenceUnit {
        debug_assert!(!self.is_empty());
        DifferenceUnit::from_index(7 - self.0.leading_zeros() as u8)
    }

    pub(crate) fn from_py(v: PyObj, state: &State) -> PyResult<Self> {
        let mut units = DifferenceUnitSet::EMPTY;
        let mut prev: Option<DifferenceUnit> = None;

        if PyStr::isinstance(v) {
            raise_type_err("units must be a sequence of strings, not a single string")?;
        }

        for item in v.to_tuple()?.iter() {
            let unit = DifferenceUnit::from_py(item, state)?;

            if let Some(p) = prev {
                if p == unit {
                    raise_value_err("units cannot contain duplicates")?;
                }
                if p > unit {
                    raise_value_err("units must be in decreasing order of size")?;
                }
            }
            units.insert(unit);
            prev = Some(unit);
        }

        if units.is_empty() {
            raise_value_err("at least one unit must be provided")?;
        }

        if units.contains(DifferenceUnit::Nanoseconds) && !units.contains(DifferenceUnit::Seconds) {
            raise_value_err("nanoseconds can only be specified together with seconds")?;
        }
        Ok(units)
    }

    /// Split into calendar and exact unit sets
    pub(crate) fn split_calendar_exact(&self) -> (CalendarUnitSet, ExactUnitSet) {
        (self.calendar_only(), self.exact_only())
    }
}

/// Unit accepted by `TimeDelta.total()`.
#[derive(Debug, Copy, Clone, PartialEq, Eq)]
pub(crate) enum TotalUnit {
    Years,
    Months,
    Weeks,
    Days,
    Hours,
    Minutes,
    Seconds,
    Milliseconds,
    Microseconds,
    Nanoseconds,
}

impl TotalUnit {
    pub(crate) fn from_py(v: PyObj, state: &State) -> PyResult<Self> {
        find_interned(v, |v, eq| {
            Some(if eq(v, *state.str_years) {
                TotalUnit::Years
            } else if eq(v, *state.str_months) {
                TotalUnit::Months
            } else if eq(v, *state.str_weeks) {
                TotalUnit::Weeks
            } else if eq(v, *state.str_days) {
                TotalUnit::Days
            } else if eq(v, *state.str_hours) {
                TotalUnit::Hours
            } else if eq(v, *state.str_minutes) {
                TotalUnit::Minutes
            } else if eq(v, *state.str_seconds) {
                TotalUnit::Seconds
            } else if eq(v, *state.str_milliseconds) {
                TotalUnit::Milliseconds
            } else if eq(v, *state.str_microseconds) {
                TotalUnit::Microseconds
            } else if eq(v, *state.str_nanoseconds) {
                TotalUnit::Nanoseconds
            } else {
                None?
            })
        })
        .ok_or_else_value_err(|| format!(
            "Invalid unit {v}. Unit must be one of 'years', 'months', 'weeks', 'days', 'hours', 'minutes', 'seconds', 'milliseconds', 'microseconds', 'nanoseconds'"
        ))
    }

    pub(crate) fn to_exact(self, days_are_24h: bool) -> Result<ExactUnit, CalendarUnit> {
        Ok(match self {
            TotalUnit::Weeks if days_are_24h => ExactUnit::Weeks,
            TotalUnit::Days if days_are_24h => ExactUnit::Days,
            TotalUnit::Hours => ExactUnit::Hours,
            TotalUnit::Minutes => ExactUnit::Minutes,
            TotalUnit::Seconds => ExactUnit::Seconds,
            TotalUnit::Nanoseconds => ExactUnit::Nanoseconds,
            TotalUnit::Milliseconds => ExactUnit::Milliseconds,
            TotalUnit::Microseconds => ExactUnit::Microseconds,
            TotalUnit::Years => return Err(CalendarUnit::Years),
            TotalUnit::Months => return Err(CalendarUnit::Months),
            TotalUnit::Weeks => return Err(CalendarUnit::Weeks),
            TotalUnit::Days => return Err(CalendarUnit::Days),
        })
    }
}

#[derive(Copy, Clone)]
enum UnitsOrUnit {
    One(DifferenceUnit),
    Seq(DifferenceUnitSet),
}

/// Parsed kwargs from `since()`/`until()` calls.
///
/// Two mutually exclusive forms:
/// - `Total(unit)` — single unit returning a float; `round_mode`/`round_increment` forbidden
/// - `InUnits(units, mode, increment)` — multi-unit ItemizedDelta with optional rounding
#[derive(Debug, Copy, Clone)]
pub(crate) enum SinceUntilKwargs {
    Total(DifferenceUnit),
    InUnits(DifferenceUnitSet, round::Mode, DifferenceIncrement),
}

impl SinceUntilKwargs {
    pub(crate) fn has_calendar(self) -> bool {
        match self {
            SinceUntilKwargs::Total(u) => matches!(
                u,
                DifferenceUnit::Years
                    | DifferenceUnit::Months
                    | DifferenceUnit::Weeks
                    | DifferenceUnit::Days
            ),
            SinceUntilKwargs::InUnits(s, ..) => s.has_calendar(),
        }
    }

    pub(crate) fn has_exact_output(self) -> bool {
        match self {
            SinceUntilKwargs::Total(u) => u.to_exact(false).is_ok(),
            SinceUntilKwargs::InUnits(s, ..) => s.has_exact(),
        }
    }
}

impl SinceUntilKwargs {
    pub(crate) fn parse(fname: &str, state: &State, kwargs: &mut IterKwargs) -> PyResult<Self> {
        Self::parse_with(fname, state, kwargs, |_, _, _| Ok(false))
    }

    pub(crate) fn parse_with<F>(
        fname: &str,
        state: &State,
        kwargs: &mut IterKwargs,
        mut extra_handler: F,
    ) -> PyResult<Self>
    where
        F: FnMut(PyObj, PyObj, StrEqFn) -> PyResult<bool>,
    {
        let mut round_mode = round::Mode::Trunc;
        let mut round_increment = DifferenceIncrement::MIN;
        let mut units: Option<UnitsOrUnit> = None;
        let mut round_was_set = false;

        handle_kwargs(fname, kwargs, |key, value, eq| {
            if eq(key, *state.str_total) {
                if units.is_some() {
                    raise_type_err("cannot specify both 'total' and 'in_units'")?;
                }
                let unit = DifferenceUnit::from_py(value, state)?;
                units = Some(UnitsOrUnit::One(unit));
            } else if eq(key, *state.str_in_units) {
                if units.is_some() {
                    raise_type_err("cannot specify both 'total' and 'in_units'")?;
                }
                let unit_set = DifferenceUnitSet::from_py(value, state)?;
                units = Some(UnitsOrUnit::Seq(unit_set));
            } else if eq(key, *state.str_round_mode) {
                round_mode =
                    round::Mode::from_py_named("round_mode", value, &state.round_mode_strs)?;
                round_was_set = true;
            } else if eq(key, *state.str_round_increment) {
                round_increment = DifferenceIncrement::from_py(value)?;
                round_was_set = true;
            } else {
                return extra_handler(key, value, eq);
            }
            Ok(true)
        })?;

        match units.ok_or_type_err("must specify either 'total' or 'in_units'")? {
            UnitsOrUnit::One(unit) => {
                if round_was_set {
                    raise_type_err(
                        "'round_mode' and 'round_increment' cannot be used with 'total'",
                    )?;
                }
                Ok(SinceUntilKwargs::Total(unit))
            }
            UnitsOrUnit::Seq(unit_set) => Ok(SinceUntilKwargs::InUnits(
                unit_set,
                round_mode,
                round_increment,
            )),
        }
    }
}

/// Rounding increment in calendar units.
#[derive(Debug, Copy, Clone, PartialEq, Eq)]
pub(crate) struct CalendarIncrement(i32);

impl CalendarIncrement {
    pub(crate) const MIN: Self = Self(1);
    pub(crate) fn new(inc: i32) -> Option<Self> {
        if inc <= 0 || inc > DeltaDays::MAX.get() {
            None
        } else {
            Some(Self(inc))
        }
    }

    pub(crate) fn from_i64(inc: i64) -> Option<Self> {
        if inc <= 0 || inc > DeltaDays::MAX.get() as i64 {
            None
        } else {
            Some(Self(inc as i32))
        }
    }

    pub(crate) fn from_py(v: PyObj) -> PyResult<Self> {
        let inc = v.expect_int("round_increment")?.to_i64()?;
        Self::from_i64(inc).ok_or_value_err("round_increment must be a positive integer in range")
    }

    pub(crate) fn get(self) -> i32 {
        self.0
    }

    pub(crate) fn truncate(self, v: i32) -> i32 {
        // SAFETY: the resulting value is always closer to 0, so it cannot overflow
        v - (v % self.0)
    }
}

/// Rounding increment for difference operations.
#[derive(Debug, Copy, Clone, PartialEq, Eq)]
pub(crate) struct DifferenceIncrement(NonZeroU128);

impl DifferenceIncrement {
    // SAFETY: 1 is non-zero — but NonZeroU128::new(1).unwrap() also works in const
    pub(crate) const MIN: Self = Self(NonZeroU128::new(1).unwrap());

    pub(crate) fn from_py(v: PyObj) -> PyResult<Self> {
        let inc = v.expect_int("round_increment")?.to_i128()?;
        if inc <= 0 {
            raise_value_err("round_increment must be a positive integer in range")?
        }
        // SAFETY: we just checked that inc > 0, so inc as u128 is valid and non-zero
        Ok(Self(unsafe { NonZeroU128::new_unchecked(inc as u128) }))
    }

    /// Returns the increment as `i128`. Safe because `from_py` ensures the value
    /// fits within `i128::MAX`.
    pub(crate) fn as_i128(self) -> i128 {
        self.0.get() as i128
    }

    pub(crate) fn to_calendar(self) -> Option<CalendarIncrement> {
        CalendarIncrement::new(i32::try_from(self.0.get()).ok()?)
    }
}

#[derive(Debug, Copy, Clone, PartialEq, Eq)]
pub(crate) enum DateDifferenceUnits {
    Total(CalendarUnit),
    InUnits(CalendarUnitSet),
}

/// Compute multi-unit date difference, progressively applying each unit.
/// Returns (results_per_unit, trunc_date, expand_date).
/// The `neg` parameter determines the direction of rounding.
/// It's passed explicitly since it cannot (fully) be determined from `a` and `b`
/// since other context may affect the rounding direction (e.g. time of day)
pub(crate) fn date_diff(
    a: Date,
    b: Date,
    round_increment: CalendarIncrement,
    units: CalendarUnitSet, // time units ignored
    neg: bool,
) -> Option<(ItemizedDateDelta, InterimDate, InterimDate)> {
    let smallest = units.smallest();
    let mut result = ItemizedDateDelta::UNSET;
    let mut trunc = b.into();
    let mut expand = a.into();

    for unit in units.iter() {
        let inc = if unit == smallest {
            round_increment
        } else {
            CalendarIncrement::MIN
        };
        let (new_trunc, new_expand) = unit.diff_into(a, trunc, inc, neg, &mut result)?;
        trunc = new_trunc;
        expand = new_expand;
    }

    Some((result, trunc, expand))
}

pub(crate) fn date_diff_single_unit(
    a: Date,
    b: Date,
    round_increment: CalendarIncrement,
    unit: CalendarUnit,
    neg: bool,
) -> Option<CalendarDiff> {
    Some(match unit {
        CalendarUnit::Years => years_diff(a, b.into(), round_increment, neg)?,
        CalendarUnit::Months => months_diff(a, b.into(), round_increment, neg)?,
        CalendarUnit::Weeks => weeks_diff(a, b.into(), round_increment, neg)?,
        CalendarUnit::Days => days_diff(a, b.into(), round_increment, neg)?,
    })
}

/// Round a calendar unit value by the number of days between the truncated
/// and expanded dates.
pub(crate) fn round_by_days(
    value: i32,
    target: Date,
    trunc: Date,
    expand: Date,
    mode: round::AbsMode,
    increment: CalendarIncrement,
    neg: bool,
) -> i32 {
    if mode == round::AbsMode::Trunc {
        value
    } else {
        let trunc_date = trunc.unix_days();
        let r = target.unix_days().diff(trunc_date).abs().get();
        let e = expand.unix_days().diff(trunc_date).abs().get();
        debug_assert!(e > 0, "expand and trunc dates cannot be the same");
        round(value, r > 0, r.cmp(&(e - r)), mode, increment, neg)
    }
}

// Round a calendar unit value by the amount of time between the truncated
// and expanded datetimes.
pub(crate) fn round_by_time(
    value: i32,
    target: Instant,
    trunc: Instant,
    expand: Instant,
    mode: round::AbsMode,
    increment: CalendarIncrement,
    neg: bool,
) -> i32 {
    // Only run the rounding logic if the rounding mode isn't already trunc
    // since that mode doesn't require any work.
    if mode == round::AbsMode::Trunc {
        // Truncated value (the common case)
        value
    } else {
        let r = target.diff(trunc).abs();
        let e = expand.diff(trunc).abs();
        debug_assert!(!e.is_zero());
        // r.cmp(e - r) is equivalent to (r * 2).cmp(e), avoiding overflow
        let half_cmp = r.cmp(&(e.add(-r).unwrap()));
        round(value, !r.is_zero(), half_cmp, mode, increment, neg)
    }
}

fn round(
    trunc_value: i32,
    has_remainder: bool,
    half_cmp: Ordering,
    mode: round::AbsMode,
    increment: CalendarIncrement,
    negate: bool,
) -> i32 {
    let do_expand = match mode {
        round::AbsMode::Trunc => unreachable!("trunc should be handled by caller"),
        round::AbsMode::Expand => has_remainder,
        round::AbsMode::HalfEven => {
            half_cmp == Ordering::Greater
                || (half_cmp == Ordering::Equal
                    && !(trunc_value / increment.get())
                        .unsigned_abs()
                        .is_multiple_of(2))
        }
        round::AbsMode::HalfTrunc => half_cmp == Ordering::Greater,
        round::AbsMode::HalfExpand => half_cmp != Ordering::Less,
    };

    trunc_value
        + if do_expand {
            increment.get().negate_if(negate)
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
        let (diff, _, _) = years_diff(
            d(2023, 4, 15),
            d(2020, 1, 1).into(),
            CalendarIncrement::MIN,
            false,
        )
        .unwrap();
        assert_eq!(diff, 3);
    }

    #[test]
    fn test_years_diff_leap_day() {
        // Feb 29, 2020 to Feb 28, 2021: pending leap day resolves to Feb 28
        let (diff, trunc, _) = years_diff(
            d(2021, 2, 28),
            d(2020, 2, 29).into(),
            CalendarIncrement::MIN,
            false,
        )
        .unwrap();
        assert_eq!(diff, 1);
        assert_eq!(trunc.resolve(), d(2021, 2, 28));
    }

    #[test]
    fn test_months_diff_basic() {
        let (diff, _, _) = months_diff(
            d(2023, 4, 15),
            d(2023, 1, 1).into(),
            CalendarIncrement::MIN,
            false,
        )
        .unwrap();
        assert_eq!(diff, 3);
    }

    #[test]
    fn test_days_diff_basic() {
        let (diff, _, _) = days_diff(
            d(2023, 1, 10),
            d(2023, 1, 1).into(),
            CalendarIncrement::MIN,
            false,
        )
        .unwrap();
        assert_eq!(diff, 9);
    }

    #[test]
    fn test_date_diff_years_months() {
        let mut units = CalendarUnitSet::EMPTY;
        units.insert(CalendarUnit::Years);
        units.insert(CalendarUnit::Months);
        let (results, _, _) = date_diff(
            d(2023, 4, 15),
            d(2020, 1, 1),
            CalendarIncrement::MIN,
            units,
            false,
        )
        .unwrap();
        assert_eq!(results.years.get_or(0), 3);
        assert_eq!(results.months.get_or(0), 3);
    }

    #[test]
    fn test_round_expand() {
        // has_remainder=true, half_cmp irrelevant for Expand
        assert_eq!(
            round(
                3,
                true,
                Ordering::Less,
                round::AbsMode::Expand,
                CalendarIncrement::MIN,
                false
            ),
            4
        );
        // has_remainder=false
        assert_eq!(
            round(
                3,
                false,
                Ordering::Less,
                round::AbsMode::Expand,
                CalendarIncrement::MIN,
                false
            ),
            3
        );
    }

    #[test]
    fn test_round_half_even() {
        // exact tie (Equal), trunc_value/inc is odd → expand
        assert_eq!(
            round(
                3,
                true,
                Ordering::Equal,
                round::AbsMode::HalfEven,
                CalendarIncrement::MIN,
                false
            ),
            4
        );
        // exact tie (Equal), trunc_value/inc is even → trunc
        assert_eq!(
            round(
                4,
                true,
                Ordering::Equal,
                round::AbsMode::HalfEven,
                CalendarIncrement::MIN,
                false
            ),
            4
        );
        // above tie → expand
        assert_eq!(
            round(
                4,
                true,
                Ordering::Greater,
                round::AbsMode::HalfEven,
                CalendarIncrement::MIN,
                false
            ),
            5
        );
        // below tie → trunc
        assert_eq!(
            round(
                4,
                true,
                Ordering::Less,
                round::AbsMode::HalfEven,
                CalendarIncrement::MIN,
                false
            ),
            4
        );
    }
}
