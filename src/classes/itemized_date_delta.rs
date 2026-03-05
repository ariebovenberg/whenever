use core::ffi::{c_int, c_void};
use pyo3_ffi::*;
use std::{cmp::Ordering, ptr::null_mut as NULL};

use crate::{
    classes::{
        date::{Date, date_since_iddelta},
        date_delta::{Unit, parse_component, parse_prefix},
        instant::Instant,
    },
    common::{
        cal_diff::{self, CalUnit, UnitSet, round_by_days, round_by_time},
        round,
        scalar::{DeltaDays, DeltaField, DeltaMonths, Year},
    },
    docstrings as doc,
    py::*,
    pymodule::State,
};

// TODO: later: why do these have to be unsigned?
// u64 because ItemizedDelta's MAX_MINUTES/MAX_SECONDS exceed u32::MAX
pub(crate) const MAX_YEARS: u64 = Year::MAX.get() as u64;
pub(crate) const MAX_MONTHS: u64 = MAX_YEARS * 12;
pub(crate) const MAX_WEEKS: u64 = MAX_YEARS * 53;
pub(crate) const MAX_DAYS: u64 = MAX_YEARS * 366;

#[derive(Debug, Copy, Clone, PartialEq, Eq)]
pub(crate) struct ItemizedDateDelta {
    pub(crate) years: DeltaField<i32>,
    pub(crate) months: DeltaField<i32>,
    pub(crate) weeks: DeltaField<i32>,
    pub(crate) days: DeltaField<i32>,
}

impl ItemizedDateDelta {
    pub(crate) const UNSET: Self = Self {
        years: DeltaField::UNSET,
        months: DeltaField::UNSET,
        weeks: DeltaField::UNSET,
        days: DeltaField::UNSET,
    };

    pub(crate) fn is_zero(self) -> bool {
        self.derived_sign() == 0
    }

    /// Convert to (DeltaMonths, DeltaDays) for use with Date.shift()
    pub(crate) fn to_months_days(self) -> Option<(DeltaMonths, DeltaDays)> {
        // FYI: I removed the need to go through i64
        DeltaMonths::new(
            (self.years.get_or(0))
                .checked_mul(12)?
                .checked_add(self.months.get_or(0))?,
        )
        .zip(DeltaDays::new(
            (self.weeks.get_or(0))
                .checked_mul(7)?
                .checked_add(self.days.get_or(0))?,
        ))
    }

    /// Collect the union of set units (as CalUnit indices)
    pub(crate) fn unit_set(self) -> UnitSet {
        let mut set = UnitSet::EMPTY;
        if self.years.is_set() {
            set.insert_cal(CalUnit::Years);
        }
        if self.months.is_set() {
            set.insert_cal(CalUnit::Months);
        }
        if self.weeks.is_set() {
            set.insert_cal(CalUnit::Weeks);
        }
        if self.days.is_set() {
            set.insert_cal(CalUnit::Days);
        }
        set
    }

    pub(crate) fn derived_sign(self) -> i8 {
        [self.years, self.months, self.weeks, self.days]
            .into_iter()
            .map(|c| c.sign())
            .find(|&s| s != 0)
            .unwrap_or(0)
    }

    fn len(self) -> usize {
        self.years.is_set() as usize
            + self.months.is_set() as usize
            + self.weeks.is_set() as usize
            + self.days.is_set() as usize
    }

    fn eq_semantic(self, other: Self) -> bool {
        self.years.get_or(0) == other.years.get_or(0)
            && self.months.get_or(0) == other.months.get_or(0)
            && self.weeks.get_or(0) == other.weeks.get_or(0)
            && self.days.get_or(0) == other.days.get_or(0)
    }

    pub(crate) fn negated(self) -> Self {
        Self {
            years: self.years.neg(),
            months: self.months.neg(),
            weeks: self.weeks.neg(),
            days: self.days.neg(),
        }
    }

    fn fmt_iso(self, lowercase: bool) -> String {
        let (y, m, w, d) = if lowercase {
            ('y', 'm', 'w', 'd')
        } else {
            ('Y', 'M', 'W', 'D')
        };
        let mut s = String::with_capacity(16);
        if self.derived_sign() == -1 {
            s.push('-');
        }
        s.push('P');
        if self.years.is_set() {
            s.push_str(&format!("{}{y}", self.years.unsigned_abs()));
        }
        if self.months.is_set() {
            s.push_str(&format!("{}{m}", self.months.unsigned_abs()));
        }
        if self.weeks.is_set() {
            s.push_str(&format!("{}{w}", self.weeks.unsigned_abs()));
        }
        if self.days.is_set() {
            s.push_str(&format!("{}{d}", self.days.unsigned_abs()));
        }
        s
    }

    fn find_field(self, key: PyObj, state: &State) -> Option<PyReturn> {
        find_interned(key, |key, eq| {
            if eq(key, state.str_years) {
                self.years.to_py_if_set()
            } else if eq(key, state.str_months) {
                self.months.to_py_if_set()
            } else if eq(key, state.str_weeks) {
                self.weeks.to_py_if_set()
            } else if eq(key, state.str_days) {
                self.days.to_py_if_set()
            } else {
                None
            }
        })
    }

    fn contains_field(self, key: PyObj, state: &State) -> bool {
        check_interned(key, |key, eq| {
            (eq(key, state.str_years) && self.years.is_set())
                || (eq(key, state.str_months) && self.months.is_set())
                || (eq(key, state.str_weeks) && self.weeks.is_set())
                || (eq(key, state.str_days) && self.days.is_set())
        })
    }

    pub(crate) fn round_by_days(
        &mut self,
        unit: CalUnit,
        target: Date,
        trunc: Date,
        expand: Date,
        mode: round::Mode,
        round_increment: i32,
        sign: i8,
    ) {
        let field = match unit {
            CalUnit::Years => &mut self.years,
            CalUnit::Months => &mut self.months,
            CalUnit::Weeks => &mut self.weeks,
            CalUnit::Days => &mut self.days,
        };
        // SAFETY: the rounded value is between trunc and expand,
        // which are both within range.
        field.replace_unchecked(round_by_days(
            field.unwrap(),
            target,
            trunc,
            expand,
            mode,
            round_increment,
            sign,
        ));
    }

    pub(crate) fn round_by_time(
        &mut self,
        unit: CalUnit,
        target: Instant,
        trunc: Instant,
        expand: Instant,
        mode: round::Mode,
        round_increment: i32,
        sign: i8,
    ) {
        let field = match unit {
            CalUnit::Years => &mut self.years,
            CalUnit::Months => &mut self.months,
            CalUnit::Weeks => &mut self.weeks,
            CalUnit::Days => &mut self.days,
        };
        // SAFETY: the rounded value is between trunc and expand,
        // which are both within range.
        field.replace_unchecked(round_by_time(
            field.unwrap(),
            target,
            trunc,
            expand,
            mode,
            round_increment,
            sign,
        ));
    }
}

// TODO: return ItemizedDateDelta?
/// Parse date components (Y/M/W/D) from an ISO duration string.
/// Stops at 'T' (time separator) or end of input.
/// Used by both ItemizedDateDelta and ItemizedDelta.
pub(crate) fn parse_date_fields(
    s: &mut &[u8],
    negated: bool,
    err: impl Fn() -> String,
) -> PyResult<ItemizedDateDelta> {
    let mut result = ItemizedDateDelta::UNSET;
    let mut prev: Option<Unit> = None;

    while !s.is_empty() && !s[0].eq_ignore_ascii_case(&b'T') {
        let (value, unit) = parse_component(s).ok_or_else_value_err(&err)?;
        if prev.is_some_and(|p| p >= unit) {
            raise_value_err(err())?;
        }
        // TODO: prevent need for u64
        let signed = DeltaField::new_checked(
            value as u64,
            negated,
            match unit {
                Unit::Years => MAX_YEARS,
                Unit::Months => MAX_MONTHS,
                Unit::Weeks => MAX_WEEKS,
                Unit::Days => MAX_DAYS,
            },
        )
        .ok_or_value_err("Delta out of range")?;
        match unit {
            Unit::Years => result.years = signed,
            Unit::Months => result.months = signed,
            Unit::Weeks => result.weeks = signed,
            Unit::Days => {
                result.days = signed;
                break; // D is the last date unit
            }
        }
        prev = Some(unit);
    }
    Ok(result)
}

impl PySimpleAlloc for ItemizedDateDelta {}

fn __new__(cls: HeapType<ItemizedDateDelta>, args: PyTuple, kwargs: Option<PyDict>) -> PyReturn {
    match args.len() {
        0 => {}
        1 if kwargs.map_or(0, |s| s.len()) == 0 => {
            return parse_iso(cls, args.iter().next().unwrap());
        }
        _ => {
            return raise_type_err(
                "ItemizedDateDelta() takes either 1 positional argument or only keyword arguments",
            );
        }
    }

    let state = cls.state();
    let Some(kwarg_dict) = kwargs else {
        return raise_value_err("At least one field must be set");
    };

    let mut sign: i8 = 0;
    let mut years = DeltaField::UNSET;
    let mut months = DeltaField::UNSET;
    let mut weeks = DeltaField::UNSET;
    let mut days = DeltaField::UNSET;

    handle_kwargs(
        "ItemizedDateDelta",
        kwarg_dict.iteritems(),
        |key, value, eq| {
            if eq(key, state.str_years) {
                years = DeltaField::parse(value, &mut sign, MAX_YEARS)?;
            } else if eq(key, state.str_months) {
                months = DeltaField::parse(value, &mut sign, MAX_MONTHS)?;
            } else if eq(key, state.str_weeks) {
                weeks = DeltaField::parse(value, &mut sign, MAX_WEEKS)?;
            } else if eq(key, state.str_days) {
                days = DeltaField::parse(value, &mut sign, MAX_DAYS)?;
            } else {
                return Ok(false);
            }
            Ok(true)
        },
    )?;

    if !years.is_set() && !months.is_set() && !weeks.is_set() && !days.is_set() {
        return raise_value_err("At least one field must be set");
    }

    ItemizedDateDelta {
        years,
        months,
        weeks,
        days,
    }
    .to_obj(cls)
}

fn sign(_: PyType, d: ItemizedDateDelta) -> PyReturn {
    (d.derived_sign() as i32).to_py()
}

fn format_iso(
    cls: HeapType<ItemizedDateDelta>,
    d: ItemizedDateDelta,
    args: &[PyObj],
    kwargs: &mut IterKwargs,
) -> PyReturn {
    if !args.is_empty() {
        raise_type_err("format_iso() takes no positional arguments")?;
    }
    let mut lowercase = false;
    handle_kwargs("format_iso", kwargs, |key, value, eq| {
        if eq(key, cls.state().str_lowercase_units) {
            lowercase = value.is_true();
            Ok(true)
        } else {
            Ok(false)
        }
    })?;
    d.fmt_iso(lowercase).to_py()
}

fn parse_iso(cls: HeapType<ItemizedDateDelta>, arg: PyObj) -> PyReturn {
    let py_str = arg
        .cast_allow_subclass::<PyStr>()
        .ok_or_type_err("When parsing from ISO format, the argument must be str")?;
    let s = &mut py_str.as_utf8()?;
    let err = || format!("Invalid format: {arg}");

    // Minimum: "P" + at least one component (e.g. "P0D") = 3 chars.
    // Since len >= 3, the loop below will always parse at least one component.
    if s.len() < 3 {
        raise_value_err(err())?;
    }

    let negated = parse_prefix(s).ok_or_else_value_err(err)?;
    let result = parse_date_fields(s, negated, err)?;

    if !s.is_empty() {
        raise_value_err(format!("Invalid format: {arg}"))?;
    }

    result.to_obj(cls)
}

fn __richcmp__(
    cls: HeapType<ItemizedDateDelta>,
    a: ItemizedDateDelta,
    b_obj: PyObj,
    op: c_int,
) -> PyReturn {
    match b_obj.extract(cls) {
        Some(b) => match op {
            pyo3_ffi::Py_EQ => a.eq_semantic(b),
            pyo3_ffi::Py_NE => !a.eq_semantic(b),
            _ => return not_implemented(),
        }
        .to_py(),
        None => not_implemented(),
    }
}

fn __neg__(cls: HeapType<ItemizedDateDelta>, slf: PyObj) -> PyReturn {
    let (_, d) = unsafe { slf.assume_heaptype::<ItemizedDateDelta>() };
    if d.derived_sign() == 0 {
        return Ok(slf.newref());
    }
    ItemizedDateDelta {
        years: d.years.neg(),
        months: d.months.neg(),
        weeks: d.weeks.neg(),
        days: d.days.neg(),
    }
    .to_obj(cls)
}

fn __abs__(cls: HeapType<ItemizedDateDelta>, slf: PyObj) -> PyReturn {
    let (_, d) = unsafe { slf.assume_heaptype::<ItemizedDateDelta>() };
    if d.derived_sign() >= 0 {
        Ok(slf.newref())
    } else {
        ItemizedDateDelta {
            years: d.years.neg(),
            months: d.months.neg(),
            weeks: d.weeks.neg(),
            days: d.days.neg(),
        }
        .to_obj(cls)
    }
}

fn __repr__(_: PyType, d: ItemizedDateDelta) -> PyReturn {
    format!("ItemizedDateDelta(\"{}\")", d.fmt_iso(true)).to_py()
}

fn __str__(_: PyType, d: ItemizedDateDelta) -> PyReturn {
    d.fmt_iso(false).to_py()
}

extern "C" fn __bool__(slf: PyObj) -> c_int {
    (!unsafe { slf.assume_heaptype::<ItemizedDateDelta>() }
        .1
        .is_zero())
    .into()
}

extern "C" fn __mp_length__(slf: PyObj) -> Py_ssize_t {
    unsafe { slf.assume_heaptype::<ItemizedDateDelta>() }
        .1
        .len() as Py_ssize_t
}

extern "C" fn __mp_subscript__(slf: PyObj, key: PyObj) -> *mut PyObject {
    let (cls, d) = unsafe { slf.assume_heaptype::<ItemizedDateDelta>() };
    _mp_subscript_inner(cls, d, key).to_py_owned_ptr()
}

fn _mp_subscript_inner(
    cls: HeapType<ItemizedDateDelta>,
    d: ItemizedDateDelta,
    key: PyObj,
) -> PyReturn {
    match d.find_field(key, cls.state()) {
        Some(result) => result,
        None => raise_key_err(key),
    }
}

extern "C" fn __tp_iter__(slf_ptr: *mut PyObject) -> *mut PyObject {
    let slf = unsafe { PyObj::from_ptr_unchecked(slf_ptr) };
    let (cls, d) = unsafe { slf.assume_heaptype::<ItemizedDateDelta>() };
    catch_panic!(_iter_inner(cls, d).to_py_owned_ptr())
}

fn _iter_inner(cls: HeapType<ItemizedDateDelta>, d: ItemizedDateDelta) -> PyReturn {
    let &State {
        str_years,
        str_months,
        str_weeks,
        str_days,
        ..
    } = cls.state();
    let tup = PyTuple::with_len(d.len() as _)?;
    let mut i: Py_ssize_t = 0;
    if d.years.is_set() {
        tup.init_item(i, str_years.newref());
        i += 1;
    }
    if d.months.is_set() {
        tup.init_item(i, str_months.newref());
        i += 1;
    }
    if d.weeks.is_set() {
        tup.init_item(i, str_weeks.newref());
        i += 1;
    }
    if d.days.is_set() {
        tup.init_item(i, str_days.newref());
    }
    tup.py_iter()
}

extern "C" fn __sq_contains__(slf: PyObj, key: PyObj) -> c_int {
    let (cls, d) = unsafe { slf.assume_heaptype::<ItemizedDateDelta>() };
    d.contains_field(key, cls.state()) as c_int
}

fn exact_eq(cls: HeapType<ItemizedDateDelta>, d: ItemizedDateDelta, arg: PyObj) -> PyReturn {
    match arg.extract(cls) {
        Some(other) => (d == other).to_py(),
        None => false.to_py(),
    }
}

fn replace(
    cls: HeapType<ItemizedDateDelta>,
    d: ItemizedDateDelta,
    args: &[PyObj],
    kwargs: &mut IterKwargs,
) -> PyReturn {
    if !args.is_empty() {
        raise_type_err("replace() takes no positional arguments")?;
    }
    let state = cls.state();

    let mut years = d.years;
    let mut months = d.months;
    let mut weeks = d.weeks;
    let mut days = d.days;

    handle_kwargs("replace", kwargs, |key, value, eq| {
        if eq(key, state.str_years) {
            years = DeltaField::parse_opt(value, MAX_YEARS)?;
        } else if eq(key, state.str_months) {
            months = DeltaField::parse_opt(value, MAX_MONTHS)?;
        } else if eq(key, state.str_weeks) {
            weeks = DeltaField::parse_opt(value, MAX_WEEKS)?;
        } else if eq(key, state.str_days) {
            days = DeltaField::parse_opt(value, MAX_DAYS)?;
        } else {
            return Ok(false);
        }
        Ok(true)
    })?;

    if !years.is_set() && !months.is_set() && !weeks.is_set() && !days.is_set() {
        return raise_value_err("At least one field must be set");
    }

    // Check sign consistency
    let mut sign: i8 = 0;
    for s in [years.sign(), months.sign(), weeks.sign(), days.sign()] {
        if s != 0 {
            if sign != 0 && sign != s {
                return raise_value_err("Mixed sign in delta");
            }
            sign = s;
        }
    }

    ItemizedDateDelta {
        years,
        months,
        weeks,
        days,
    }
    .to_obj(cls)
}

fn __reduce__(cls: HeapType<ItemizedDateDelta>, d: ItemizedDateDelta) -> PyResult<Owned<PyTuple>> {
    (
        cls.state().unpickle_itemized_date_delta.newref(),
        (
            d.years.to_py()?,
            d.months.to_py()?,
            d.weeks.to_py()?,
            d.days.to_py()?,
        )
            .into_pytuple()?,
    )
        .into_pytuple()
}

pub(crate) fn unpickle(state: &State, args: &[PyObj]) -> PyReturn {
    let &[years_obj, months_obj, weeks_obj, days_obj] = args else {
        return raise_type_err("Invalid pickle data");
    };
    ItemizedDateDelta {
        years: DeltaField::parse_opt(years_obj, MAX_YEARS)?,
        months: DeltaField::parse_opt(months_obj, MAX_MONTHS)?,
        weeks: DeltaField::parse_opt(weeks_obj, MAX_WEEKS)?,
        days: DeltaField::parse_opt(days_obj, MAX_DAYS)?,
    }
    .to_obj(state.itemized_date_delta_type)
}

// TODO NOW: imports at the top of the file right?
use crate::common::cal_diff::parse_rounding_kwargs;

/// Extract `relative_to` as a Date from a kwarg value.
fn extract_relative_to_date(state: &State, relative_to: Option<PyObj>) -> PyResult<Date> {
    relative_to
        .ok_or_type_err("missing required keyword argument: 'relative_to'")?
        .extract(state.date_type)
        .ok_or_type_err("relative_to must be a whenever.Date")
}

fn in_units(
    cls: HeapType<ItemizedDateDelta>,
    d: ItemizedDateDelta,
    args: &[PyObj],
    kwargs: &mut IterKwargs,
) -> PyReturn {
    let state = cls.state();
    let &[units_arg] = args else {
        raise_type_err("in_units() takes exactly 1 positional argument")?
    };

    let mut relative_to_obj: Option<PyObj> = None;
    let mut round_mode_obj: Option<PyObj> = None;
    let mut round_inc_obj: Option<PyObj> = None;

    handle_kwargs("in_units", kwargs, |key, value, eq| {
        if eq(key, state.str_relative_to) {
            relative_to_obj = Some(value);
        } else if eq(key, state.str_round_mode) {
            round_mode_obj = Some(value);
        } else if eq(key, state.str_round_increment) {
            round_inc_obj = Some(value);
        } else {
            return Ok(false);
        }
        Ok(true)
    })?;

    let relative_to = extract_relative_to_date(state, relative_to_obj)?;
    let (round_mode, round_increment) =
        parse_rounding_kwargs(state, round_mode_obj, round_inc_obj)?;
    let units = cal_diff::parse_cal_units_sequence(units_arg, state)?;

    // relative_to.add(self).since(relative_to, units=...)
    let (months, days) = d.to_months_days().ok_or_value_err("Delta out of range")?;
    let shifted = relative_to
        .shift(months, days)
        .ok_or_value_err("Resulting date out of range")?;

    date_since_iddelta(shifted, relative_to, units, round_mode, round_increment)?
        .to_obj(state.itemized_date_delta_type)
}

fn total(
    cls: HeapType<ItemizedDateDelta>,
    d: ItemizedDateDelta,
    args: &[PyObj],
    kwargs: &mut IterKwargs,
) -> PyReturn {
    let state = cls.state();
    let &[unit_arg] = args else {
        raise_type_err("total() takes exactly 1 positional argument")?
    };

    let mut relative_to_obj: Option<PyObj> = None;
    // TODO NOW: I must insist that you define a helper function for
    // matching single kwargs like this.
    handle_kwargs("total", kwargs, |key, value, eq| {
        if eq(key, state.str_relative_to) {
            relative_to_obj = Some(value);
        } else {
            return Ok(false);
        }
        Ok(true)
    })?;

    let relative_to = extract_relative_to_date(state, relative_to_obj)?;
    let cal_unit = CalUnit::from_py(unit_arg, state)?;

    let (months, days) = d.to_months_days().ok_or_value_err("Delta out of range")?;
    let shifted = relative_to
        .shift(months, days)
        .ok_or_value_err("Resulting date out of range")?;

    _total(shifted, relative_to, cal_unit)?.to_py()
}

fn _total(a: Date, b: Date, cal_unit: CalUnit) -> PyResult<f64> {
    let sign: i8 = if a >= b { 1 } else { -1 };

    let (trunc_amount, trunc, expand) = cal_diff::date_diff_single_unit(a, b, 1, cal_unit, sign)
        .ok_or_value_err("Resulting date out of range")?;

    let trunc_date = trunc.resolve().unix_days();
    let r = a.unix_days().diff(trunc_date).get() as f64;
    let e = expand.resolve().unix_days().diff(trunc_date).get() as f64;

    // FYI: expand is never the same as trunc, so this can be an assert
    Ok(trunc_amount as f64 + (r / e).copysign(e))
}

fn _add_sub(
    cls: HeapType<ItemizedDateDelta>,
    d: ItemizedDateDelta,
    args: &[PyObj],
    kwargs: &mut IterKwargs,
    negate: bool,
) -> PyReturn {
    let fname = if negate { "subtract" } else { "add" };
    let state = cls.state();

    // Parse the optional positional arg
    let pos_arg = match args {
        [] => None,
        [arg] => Some(*arg),
        _ => raise_type_err(format!("{fname}() takes at most 1 positional argument"))?,
    };

    // Parse kwargs
    let mut relative_to_obj: Option<PyObj> = None;
    let mut units_obj: Option<PyObj> = None;
    let mut round_mode_obj: Option<PyObj> = None;
    let mut round_inc_obj: Option<PyObj> = None;
    // Component kwargs (years, months, weeks, days)
    let mut comp_years: Option<PyObj> = None;
    let mut comp_months: Option<PyObj> = None;
    let mut comp_weeks: Option<PyObj> = None;
    let mut comp_days: Option<PyObj> = None;

    handle_kwargs(fname, kwargs, |key, value, eq| {
        if eq(key, state.str_relative_to) {
            relative_to_obj = Some(value);
        } else if eq(key, state.str_units) {
            units_obj = Some(value);
        } else if eq(key, state.str_round_mode) {
            round_mode_obj = Some(value);
        } else if eq(key, state.str_round_increment) {
            round_inc_obj = Some(value);
        } else if eq(key, state.str_years) {
            comp_years = Some(value);
        } else if eq(key, state.str_months) {
            comp_months = Some(value);
        } else if eq(key, state.str_weeks) {
            comp_weeks = Some(value);
        } else if eq(key, state.str_days) {
            comp_days = Some(value);
        } else {
            raise_value_err(format!("Invalid field: {key}"))?;
        }
        Ok(true)
    })?;

    let has_comp_kwargs = comp_years.is_some()
        || comp_months.is_some()
        || comp_weeks.is_some()
        || comp_days.is_some();

    let relative_to = extract_relative_to_date(state, relative_to_obj)?;
    let (round_mode, round_increment) =
        parse_rounding_kwargs(state, round_mode_obj, round_inc_obj)?;

    // Determine the "other" delta to add
    let (other_months, other_days) = match (pos_arg, has_comp_kwargs) {
        (Some(_), true) => raise_type_err("Cannot mix positional and keyword arguments")?,
        (Some(arg), false) => {
            // Must be an ItemizedDateDelta
            let other = arg
                .extract(state.itemized_date_delta_type)
                .ok_or_type_err(format!("{fname}() argument must be an ItemizedDateDelta"))?;
            let other = if negate { other.negated() } else { other };
            other
                .to_months_days()
                .ok_or_value_err("Delta out of range")?
        }
        (None, true) => {
            let sign: i64 = if negate { -1 } else { 1 };
            let mut total_months: i64 = 0;
            let mut total_days: i64 = 0;

            // TODO NOW: this unchecked arithmetic can overflow.
            // Add a test for this (e.g. years=1<<63 - 1) to prove me right or wrong
            if let Some(v) = comp_years {
                total_months = v
                    .cast_allow_subclass::<PyInt>()
                    .ok_or_type_err("years must be an integer")?
                    .to_long()? as i64
                    * 12
                    * sign;
            }
            if let Some(v) = comp_months {
                total_months += v
                    .cast_allow_subclass::<PyInt>()
                    .ok_or_type_err("months must be an integer")?
                    .to_long()? as i64
                    * sign;
            }
            if let Some(v) = comp_weeks {
                total_days = v
                    .cast_allow_subclass::<PyInt>()
                    .ok_or_type_err("weeks must be an integer")?
                    .to_long()? as i64
                    * 7
                    * sign;
            }
            if let Some(v) = comp_days {
                total_days += v
                    .cast_allow_subclass::<PyInt>()
                    .ok_or_type_err("days must be an integer")?
                    .to_long()? as i64
                    * sign;
            }

            (
                DeltaMonths::from_i64(total_months).ok_or_value_err("months out of range")?,
                DeltaDays::from_i64(total_days).ok_or_value_err("days out of range")?,
            )
        }
        (None, false) => {
            // No other arg: return self (as in_units)
            let units = match units_obj {
                Some(seq) => cal_diff::parse_cal_units_sequence(seq, state)?,
                None => d.unit_set(),
            };
            let (m, dy) = d.to_months_days().ok_or_value_err("Delta out of range")?;
            let shifted = relative_to
                .shift(m, dy)
                .ok_or_value_err("Resulting date out of range")?;
            return date_since_iddelta(shifted, relative_to, units, round_mode, round_increment)?
                .to_obj(state.itemized_date_delta_type);
        }
    };

    // Determine output units
    let units = match units_obj {
        Some(seq) => cal_diff::parse_cal_units_sequence(seq, state)?,
        None => {
            // Union of self's keys and the other's keys
            // For kwargs: union of self's keys and the provided component keys
            let mut set = d.unit_set();
            if let Some(other_arg) = pos_arg {
                set = set.union(
                    other_arg
                        .extract(state.itemized_date_delta_type)
                        .unwrap()
                        .unit_set(),
                );
            } else {
                if comp_years.is_some() {
                    set.insert_cal(CalUnit::Years);
                }
                if comp_months.is_some() {
                    set.insert_cal(CalUnit::Months);
                }
                if comp_weeks.is_some() {
                    set.insert_cal(CalUnit::Weeks);
                }
                if comp_days.is_some() {
                    set.insert_cal(CalUnit::Days);
                }
            }
            set
        }
    };

    // relative_to.add(self).add(other).since(relative_to, units=...)
    let (self_months, self_days) = d.to_months_days().ok_or_value_err("Delta out of range")?;
    let shifted = relative_to
        .shift(self_months, self_days)
        .and_then(|d| d.shift(other_months, other_days))
        .ok_or_value_err("Resulting date out of range")?;

    date_since_iddelta(shifted, relative_to, units, round_mode, round_increment)?
        .to_obj(state.itemized_date_delta_type)
}

fn add(
    cls: HeapType<ItemizedDateDelta>,
    d: ItemizedDateDelta,
    args: &[PyObj],
    kwargs: &mut IterKwargs,
) -> PyReturn {
    _add_sub(cls, d, args, kwargs, false)
}

fn subtract(
    cls: HeapType<ItemizedDateDelta>,
    d: ItemizedDateDelta,
    args: &[PyObj],
    kwargs: &mut IterKwargs,
) -> PyReturn {
    _add_sub(cls, d, args, kwargs, true)
}

/// Register with collections.abc.Mapping and copy mixin methods
pub(crate) fn register_as_mapping(type_obj: PyObj) -> PyResult<()> {
    let abc = import(c"collections.abc")?;
    let mapping_cls = abc.getattr(c"Mapping")?;
    mapping_cls.getattr(c"register")?.call1(type_obj)?;
    let type_dict =
        unsafe { PyDict::from_ptr_unchecked((*type_obj.as_ptr().cast::<PyTypeObject>()).tp_dict) };
    for name in &[c"keys", c"values", c"items", c"get"] {
        let method = mapping_cls.getattr(name)?;
        type_dict.set_item_str(name, method.borrow())?;
    }
    Ok(())
}

#[allow(static_mut_refs)]
static mut SLOTS: &[PyType_Slot] = &[
    slotmethod!(ItemizedDateDelta, Py_tp_new, __new__),
    slotmethod!(ItemizedDateDelta, Py_tp_richcompare, __richcmp__),
    slotmethod!(ItemizedDateDelta, Py_nb_negative, __neg__, 1),
    slotmethod!(ItemizedDateDelta, Py_tp_repr, __repr__, 1),
    slotmethod!(ItemizedDateDelta, Py_tp_str, __str__, 1),
    slotmethod!(ItemizedDateDelta, Py_nb_absolute, __abs__, 1),
    PyType_Slot {
        slot: Py_tp_doc,
        pfunc: doc::ITEMIZEDDATEDELTA.as_ptr() as *mut c_void,
    },
    PyType_Slot {
        slot: Py_tp_methods,
        pfunc: unsafe { METHODS.as_ptr() as *mut c_void },
    },
    PyType_Slot {
        slot: Py_tp_getset,
        pfunc: unsafe { GETSETTERS.as_ptr() as *mut c_void },
    },
    PyType_Slot {
        slot: Py_nb_bool,
        pfunc: __bool__ as *mut c_void,
    },
    PyType_Slot {
        slot: Py_mp_length,
        pfunc: __mp_length__ as *mut c_void,
    },
    PyType_Slot {
        slot: Py_mp_subscript,
        pfunc: __mp_subscript__ as *mut c_void,
    },
    PyType_Slot {
        slot: Py_sq_contains,
        pfunc: __sq_contains__ as *mut c_void,
    },
    PyType_Slot {
        slot: Py_tp_iter,
        pfunc: __tp_iter__ as *mut c_void,
    },
    PyType_Slot {
        slot: Py_tp_dealloc,
        pfunc: generic_dealloc as *mut c_void,
    },
    PyType_Slot {
        slot: 0,
        pfunc: NULL(),
    },
];

static mut GETSETTERS: &[PyGetSetDef] = &[
    getter!(
        ItemizedDateDelta,
        sign,
        "The sign of the delta: 1, 0, or -1"
    ),
    PyGetSetDef {
        name: NULL(),
        get: None,
        set: None,
        doc: NULL(),
        closure: NULL(),
    },
];

static mut METHODS: &[PyMethodDef] = &[
    method0!(ItemizedDateDelta, __copy__, c""),
    method1!(ItemizedDateDelta, __deepcopy__, c""),
    method_kwargs!(
        ItemizedDateDelta,
        format_iso,
        doc::ITEMIZEDDATEDELTA_FORMAT_ISO
    ),
    classmethod1!(
        ItemizedDateDelta,
        parse_iso,
        doc::ITEMIZEDDATEDELTA_PARSE_ISO
    ),
    method1!(ItemizedDateDelta, exact_eq, doc::ITEMIZEDDATEDELTA_EXACT_EQ),
    method_kwargs!(ItemizedDateDelta, replace, doc::ITEMIZEDDATEDELTA_REPLACE),
    method_kwargs!(ItemizedDateDelta, in_units, doc::ITEMIZEDDATEDELTA_IN_UNITS),
    method_kwargs!(ItemizedDateDelta, total, doc::ITEMIZEDDATEDELTA_TOTAL),
    method_kwargs!(ItemizedDateDelta, add, doc::ITEMIZEDDATEDELTA_ADD),
    method_kwargs!(ItemizedDateDelta, subtract, doc::ITEMIZEDDATEDELTA_SUBTRACT),
    method0!(ItemizedDateDelta, __reduce__, c""),
    classmethod_kwargs!(
        ItemizedDateDelta,
        __get_pydantic_core_schema__,
        doc::PYDANTIC_SCHEMA
    ),
    PyMethodDef::zeroed(),
];

pub(crate) static mut SPEC: PyType_Spec =
    type_spec::<ItemizedDateDelta>(c"whenever.ItemizedDateDelta", unsafe { SLOTS });
