//! Calendar difference logic for since()/until() methods.
//! Rust equivalent of _math.py's date_diff and custom_round.
use crate::{
    classes::{date::Date, time_delta::TimeDelta},
    common::{
        round, scalar::{DeltaDays, Month, Year}
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
    pub(crate) fn resolve(self) -> Date {
        Date {
            year: self.year,
            month: self.month,
            day: self.day.min(self.year.days_in_month(self.month)),
        }
    }

    fn year(self) -> Year {
        self.year
    }

    fn month(self) -> Month {
        self.month
    }

    fn day(self) -> u8 {
        self.day
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

/// Replace the year of an interim date, preserving the day even if invalid.
fn replace_year(d: &InterimDate, year: Year) -> InterimDate {
    InterimDate {
        year,
        month: d.month,
        day: d.day,
    }
}

// Similar to Date::shift_months, but works on InterimDate.
// (Can't fully reuse shift_months because InterimDate may have day=29 on non-leap year)
/// Add `delta` months to an interim date, returning a concrete date.
fn add_months(d: InterimDate, delta: i32) -> Option<Date> {
    let month_raw = d.month() as i32 - 1 + delta;
    let year_delta = month_raw.div_euclid(12);
    let month = Month::new_unchecked(month_raw.rem_euclid(12) as u8 + 1);
    let year = Year::from_i32(d.year().get() as i32 + year_delta)?;
    Some(Date {
        year,
        month,
        day: d.day().min(year.days_in_month(month)),
    })
}

/// Result of a single-unit diff: (abs_diff, trunc_date, expand_date)
type AbsDiff = (i32, InterimDate, InterimDate);

fn shift_year(base: Year, delta: i32) -> Option<Year> {
    let y = base.get() as i32 + delta;
    Year::from_i32(y)
}

fn years_diff(a: Date, b: InterimDate, increment: i32, sign: i8) -> Option<AbsDiff> {
    let diff = (a.year.get() as i32 - b.year().get() as i32) / increment * increment;
    let shift = replace_year(&b, shift_year(b.year(), diff)?);

    let overshot = if diff > 0 {
        shift.resolve() > a
    } else if diff < 0 {
        shift.resolve() < a
    } else {
        false
    };

    if overshot {
        let adj = diff - increment * sign as i32;
        let adj_year = shift_year(b.year(), adj)?;
        Some((
            diff.unsigned_abs() as i32 - increment,
            replace_year(&b, adj_year),
            shift,
        ))
    } else {
        let exp_year = shift_year(b.year(), diff + increment * sign as i32)?;
        Some((
            diff.unsigned_abs() as i32,
            shift,
            replace_year(&b, exp_year),
        ))
    }
}

fn months_diff(a: Date, b: InterimDate, increment: i32, sign: i8) -> Option<AbsDiff> {
    let diff = ((a.year.get() as i32 - b.year().get() as i32) * 12
        + (a.month as i32 - b.month() as i32))
        / increment
        * increment;
    let shift = add_months(b, diff)?;

    let overshot = if diff > 0 {
        shift > a
    } else if diff < 0 {
        shift < a
    } else {
        false
    };

    if overshot {
        let adj = diff - increment * sign as i32;
        Some((
            adj.unsigned_abs() as i32,
            add_months(b, adj)?.into(),
            shift.into(),
        ))
    } else {
        Some((
            diff.unsigned_abs() as i32,
            shift.into(),
            add_months(b, diff + increment * sign as i32)?.into(),
        ))
    }
}

fn weeks_diff(a: Date, b: InterimDate, increment: i32, sign: i8) -> Option<AbsDiff> {
    let (days, trunc, expand) = days_diff(a, b, increment * 7, sign)?;
    Some((days / 7, trunc, expand))
}

fn days_diff(a: Date, b: InterimDate, increment: i32, sign: i8) -> Option<AbsDiff> {
    let b_resolved = b.resolve();
    let raw_diff = a.unix_days().diff(b_resolved.unix_days()).abs().get();
    let diff = raw_diff / increment * increment;

    let trunc = b_resolved.shift_days(DeltaDays::new_unchecked(diff * sign as i32))?;
    let expand =
        b_resolved.shift_days(DeltaDays::new_unchecked((diff + increment) * sign as i32))?;
    Some((diff, trunc.into(), expand.into()))
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
    fn from_py(v: PyObj, state: &State) -> PyResult<Self> {
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
#[derive(Debug, Copy, Clone, PartialEq, Eq)]
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
    fn from_py(v: PyObj, state: &State) -> PyResult<Self> {
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

    pub(crate) fn is_calendar(self) -> bool {
        (self as u8) <= DeltaUnit::Days as u8
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
        (None, Some(seq)) => parse_delta_units_sequence(seq, state)?,
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
fn parse_delta_units_sequence(seq: PyObj, state: &State) -> PyResult<(UnitSet, bool)> {
    let len = unsafe { pyo3_ffi::PySequence_Length(seq.as_ptr()) };
    if len < 0 {
        return Err(PyErrMarker());
    }
    let len = len as usize;
    if len == 0 {
        raise_value_err("'units' cannot be an empty sequence")?;
    }
    if len > 8 {
        raise_value_err("Too many units (max 8)")?;
    }

    let mut units = UnitSet::EMPTY;
    let mut prev_idx: Option<usize> = None;

    for i in 0..len {
        let item =
            unsafe { pyo3_ffi::PySequence_GetItem(seq.as_ptr(), i as isize) }.rust_owned()?;
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

    Ok((units, false))
}

// TODO LATER: perhaps this all blows up anyway because we need to support more arbitrary
// increments up to 1000s of years.
/// Decompose a TimeDelta into the given exact units.
/// Applies rounding to the smallest unit first, then does successive divmod.
pub(crate) fn time_delta_in_units(
    td: TimeDelta,
    units: UnitSet,
    round_increment: i32,
    round_mode: round::Mode,
) -> Option<[i64; 8]> {
    // Round to the smallest unit first
    let smallest = units.smallest();
    let increment_ns = smallest.ns_per_unit() * round_increment as i64;
    let rounded = td.round(increment_ns, round_mode)?;
    let mut remaining = rounded.total_nanos().unsigned_abs();

    let mut results = [0i64; 8];
    for u in units.iter() {
        let ns = u.ns_per_unit() as u128;
        results[u as usize] = (remaining / ns) as i64;
        remaining %= ns;
    }
    Some(results)
}

/// Parsed since/until arguments for Date
pub(crate) struct SinceUntilArgs {
    pub(crate) units: UnitSet,
    pub(crate) single_unit_mode: bool,
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
        (None, Some(seq)) => parse_cal_units_sequence(seq, state)?,
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
fn parse_cal_units_sequence(seq: PyObj, state: &State) -> PyResult<(UnitSet, bool)> {
    let len = unsafe { pyo3_ffi::PySequence_Length(seq.as_ptr()) };
    if len < 0 {
        return Err(PyErrMarker());
    }
    let len = len as usize;
    if len == 0 {
        raise_value_err("'units' cannot be an empty sequence")?;
    }
    if len > 4 {
        raise_value_err("Too many units (max 4 for date units)")?;
    }

    let mut units = UnitSet::EMPTY;
    let mut prev_unit: Option<CalUnit> = None;

    for i in 0..len {
        let item =
            unsafe { pyo3_ffi::PySequence_GetItem(seq.as_ptr(), i as isize) }.rust_owned()?;
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

    Ok((units, false))
}

/// Compute multi-unit date difference, progressively applying each unit.
/// Returns (results_per_unit, trunc_date, expand_date).
pub(crate) fn date_diff(
    a: Date,
    b: Date,
    round_increment: i32,
    units: UnitSet,
    sign: i8,
) -> Option<([i32; 4], InterimDate, InterimDate)> {
    let mut trunc: InterimDate = b.into();
    let mut expand: InterimDate = a.into();
    let mut results = [0i32; 4]; // years, months, weeks, days
    let smallest = units.smallest();

    for unit in units.cal_only().iter() {
        let cal = unit.to_cal().unwrap();
        // Only the last unit gets the round_increment; others use 1
        let inc = if unit == smallest { round_increment } else { 1 };
        let (diff, new_trunc, new_expand) = match cal {
            CalUnit::Years => years_diff(a, trunc, inc, sign)?,
            CalUnit::Months => months_diff(a, trunc, inc, sign)?,
            CalUnit::Weeks => weeks_diff(a, trunc, inc, sign)?,
            CalUnit::Days => days_diff(a, trunc, inc, sign)?,
        };
        results[cal as usize] = diff;
        trunc = new_trunc;
        expand = new_expand;
    }

    Some((results, trunc, expand))
}

/// Custom rounding for calendar units.
/// All values are absolute (non-negative). Sign is handled separately.
///
/// - `trunc_value`: the truncated (towards-zero) value
/// - `remainder`: absolute distance from trunc to actual value (in days or ns)
/// - `expanded`: absolute distance from trunc to expanded value (in days or ns)
/// - `mode`: rounding mode (must NOT be Trunc — caller handles that)
/// - `increment`: the rounding increment
/// - `sign`: 1 or -1
pub(crate) fn custom_round(
    trunc_value: i32,
    // u128 to safely handle both day-level and nanosecond-level distances
    // (large increments like 400 years of nanoseconds exceed i64)
    // TODO NOW: ok, I'm just *not* a fan of 'giving up' and using u128.
    // You had an idea of simplifying the rounding itself by the fact
    // that you only need to really know if remainder >0 and remainder > expanded/2.
    // Take advantage of that, either with a helper method on DeltaDays/TimeDelta
    // or precomputing it. Or maybe this would work: 2 methods round_days(..., DaysDelta, ...) and round_time(..., TimeDelta, ...)
    // that call a round_common() underneath. Only if cleaner than a shared trait though.
    remainder: u128,
    expanded: u128,
    mode: round::Mode,
    increment: i32,
    sign: i8,
) -> i32 {
    debug_assert!(expanded > 0);
    debug_assert!(trunc_value >= 0);
    debug_assert!(increment > 0);
    debug_assert!(expanded != remainder);

    let has_remainder = remainder > 0;
    let do_expand = match mode {
        round::Mode::Trunc => unreachable!("trunc should be handled by caller"),
        round::Mode::Expand => has_remainder,
        round::Mode::Ceil => has_remainder == (sign > 0),
        round::Mode::Floor => has_remainder == (sign < 0),
        round::Mode::HalfEven => {
            remainder * 2 > expanded
                || (remainder * 2 == expanded && (trunc_value / increment) % 2 == 1)
        }
        round::Mode::HalfCeil => {
            let threshold = if sign > 0 { expanded } else { expanded + 1 };
            remainder * 2 >= threshold
        }
        round::Mode::HalfFloor => {
            let threshold = if sign < 0 { expanded } else { expanded + 1 };
            remainder * 2 >= threshold
        }
        round::Mode::HalfTrunc => remainder * 2 > expanded,
        round::Mode::HalfExpand => remainder * 2 >= expanded,
    };

    trunc_value + if do_expand { increment } else { 0 }
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
        assert_eq!(custom_round(3, 5, 10, round::Mode::Expand, 1, 1), 4);
        assert_eq!(custom_round(3, 0, 10, round::Mode::Expand, 1, 1), 3);
    }

    #[test]
    fn test_custom_round_half_even() {
        // exact tie, trunc_value/inc is odd → expand
        assert_eq!(custom_round(3, 5, 10, round::Mode::HalfEven, 1, 1), 4);
        // exact tie, trunc_value/inc is even → trunc
        assert_eq!(custom_round(4, 5, 10, round::Mode::HalfEven, 1, 1), 4);
    }
}
