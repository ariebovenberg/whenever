use core::ffi::{c_int, c_void};
use pyo3_ffi::*;
use std::ptr::null_mut as NULL;

use crate::{
    classes::{
        date::{Date, date_since_iddelta},
        date_delta::{parse_component, parse_prefix},
        instant::Instant,
    },
    common::{
        math::{self, CalUnit, CalUnitSet, DateRoundIncrement, round_by_days, round_by_time},
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

    pub(crate) fn is_unset(self) -> bool {
        !self.years.is_set() && !self.months.is_set() && !self.weeks.is_set() && !self.days.is_set()
    }

    pub(crate) fn has_sign_conflicts(self) -> bool {
        let mut sign: i8 = 0;
        for s in [
            self.years.sign(),
            self.months.sign(),
            self.weeks.sign(),
            self.days.sign(),
        ] {
            if s != 0 {
                if sign != 0 && sign != s {
                    return true;
                }
                sign = s;
            }
        }
        false
    }

    pub(crate) fn is_zero(self) -> bool {
        self.derived_sign() == 0
    }

    pub(crate) fn to_months_days(self) -> Option<(DeltaMonths, DeltaDays)> {
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

    pub(crate) fn round_by_days(
        &mut self,
        unit: CalUnit,
        target: Date,
        trunc: Date,
        expand: Date,
        mode: round::Mode,
        round_increment: DateRoundIncrement,
        sign: i8,
    ) {
        let field = unit.field(self);
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
        round_increment: DateRoundIncrement,
        sign: i8,
    ) {
        let field = unit.field(self);
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

/// Parse date components (Y/M/W/D) from an ISO duration string.
/// Stops at 'T' (time separator) or end of input.
/// Used by both ItemizedDateDelta and ItemizedDelta.
/// Note the result may have no fields set.
pub(crate) fn parse_date_fields(s: &mut &[u8], negated: bool) -> Option<ItemizedDateDelta> {
    let mut result = ItemizedDateDelta::UNSET;
    let mut prev: Option<CalUnit> = None;

    while !s.is_empty() && !s[0].eq_ignore_ascii_case(&b'T') {
        let (value, unit) = parse_component(s)?;
        if prev.is_some_and(|p| p >= unit) {
            return None;
        }
        unit.field(&mut result)
            .replace_unchecked(unit.validate(value as u32, negated)?);
        prev = Some(unit);
    }
    Some(result)
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

    let &State {
        str_years,
        str_months,
        str_weeks,
        str_days,
        ..
    } = cls.state();

    let kwarg_dict = match kwargs {
        Some(d) if d.len() > 0 => d,
        _ => raise_value_err("at least one field must be set")?,
    };

    let mut sign: i8 = 0;
    let mut slf = ItemizedDateDelta::UNSET;

    handle_kwargs(
        "ItemizedDateDelta",
        kwarg_dict.iteritems(),
        |key, value, eq| {
            if eq(key, str_years) {
                slf.years = DeltaField::parse(value, &mut sign, MAX_YEARS)?;
            } else if eq(key, str_months) {
                slf.months = DeltaField::parse(value, &mut sign, MAX_MONTHS)?;
            } else if eq(key, str_weeks) {
                slf.weeks = DeltaField::parse(value, &mut sign, MAX_WEEKS)?;
            } else if eq(key, str_days) {
                slf.days = DeltaField::parse(value, &mut sign, MAX_DAYS)?;
            } else {
                return Ok(false);
            }
            Ok(true)
        },
    )?;

    slf.to_obj(cls)
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
        .ok_or_type_err("when parsing from ISO format, the argument must be str")?;
    let s = &mut py_str.as_utf8()?;
    let err = || format!("Invalid format or out of range: {arg}");

    // Minimum: "P" + at least one component (e.g. "P0D") = 3 chars.
    if s.len() < 3 {
        raise_value_err(err())?;
    }

    let negated = parse_prefix(s).ok_or_else_value_err(err)?;
    let result = parse_date_fields(s, negated).ok_or_else_value_err(err)?;

    if !s.is_empty() {
        raise_value_err(err())?;
    }

    // NOTE: we don't need to check for unset components here,
    // because we checked earlier that the length is at least 3.
    // Thus we will always attempt to parse at least one field.
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
    mp_subscript_inner(cls, d, key).to_py_owned_ptr()
}

fn mp_subscript_inner(
    cls: HeapType<ItemizedDateDelta>,
    d: ItemizedDateDelta,
    key: PyObj,
) -> PyReturn {
    let &State {
        str_years,
        str_months,
        str_weeks,
        str_days,
        ..
    } = cls.state();
    let found = find_interned(key, |key, eq| {
        if eq(key, str_years) {
            d.years.to_py_if_set()
        } else if eq(key, str_months) {
            d.months.to_py_if_set()
        } else if eq(key, str_weeks) {
            d.weeks.to_py_if_set()
        } else if eq(key, str_days) {
            d.days.to_py_if_set()
        } else {
            None
        }
    });
    match found {
        Some(result) => result,
        None => raise_key_err(key),
    }
}

extern "C" fn __tp_iter__(slf_ptr: *mut PyObject) -> *mut PyObject {
    let slf = unsafe { PyObj::from_ptr_unchecked(slf_ptr) };
    let (cls, d) = unsafe { slf.assume_heaptype::<ItemizedDateDelta>() };
    catch_panic!(iter_inner(cls, d).to_py_owned_ptr())
}

fn iter_inner(cls: HeapType<ItemizedDateDelta>, d: ItemizedDateDelta) -> PyReturn {
    let &State {
        str_years,
        str_months,
        str_weeks,
        str_days,
        ..
    } = cls.state();
    let tup = PyTuple::with_len(d.len() as _)?;
    let mut i = 0;
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
    let &State {
        str_years,
        str_months,
        str_weeks,
        str_days,
        ..
    } = cls.state();
    check_interned(key, |key, eq| {
        (eq(key, str_years) && d.years.is_set())
            || (eq(key, str_months) && d.months.is_set())
            || (eq(key, str_weeks) && d.weeks.is_set())
            || (eq(key, str_days) && d.days.is_set())
    }) as c_int
}

fn exact_eq(cls: HeapType<ItemizedDateDelta>, d: ItemizedDateDelta, arg: PyObj) -> PyReturn {
    match arg.extract(cls) {
        Some(other) => (d == other).to_py(),
        None => false.to_py(),
    }
}

fn replace(
    cls: HeapType<ItemizedDateDelta>,
    mut d: ItemizedDateDelta,
    args: &[PyObj],
    kwargs: &mut IterKwargs,
) -> PyReturn {
    if !args.is_empty() {
        raise_type_err("replace() takes no positional arguments")?;
    }
    let &State {
        str_years,
        str_months,
        str_weeks,
        str_days,
        ..
    } = cls.state();

    handle_kwargs("replace", kwargs, |key, value, eq| {
        if eq(key, str_years) {
            d.years = DeltaField::parse_opt(value, MAX_YEARS)?;
        } else if eq(key, str_months) {
            d.months = DeltaField::parse_opt(value, MAX_MONTHS)?;
        } else if eq(key, str_weeks) {
            d.weeks = DeltaField::parse_opt(value, MAX_WEEKS)?;
        } else if eq(key, str_days) {
            d.days = DeltaField::parse_opt(value, MAX_DAYS)?;
        } else {
            return Ok(false);
        }
        Ok(true)
    })?;

    if d.is_unset() {
        return raise_value_err("at least one field must remain set");
    }
    if d.has_sign_conflicts() {
        return raise_value_err("mixed sign in delta");
    }

    d.to_obj(cls)
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
        return raise_type_err("invalid pickle data");
    };
    ItemizedDateDelta {
        years: DeltaField::parse_opt(years_obj, MAX_YEARS)?,
        months: DeltaField::parse_opt(months_obj, MAX_MONTHS)?,
        weeks: DeltaField::parse_opt(weeks_obj, MAX_WEEKS)?,
        days: DeltaField::parse_opt(days_obj, MAX_DAYS)?,
    }
    .to_obj(state.itemized_date_delta_type)
}

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
    let &State {
        str_relative_to,
        str_round_mode,
        str_round_increment,
        round_mode_strs,
        ..
    } = state;

    let units = CalUnitSet::from_py(handle_one_arg("in_units", args)?, state)?;

    let mut relative_to_arg = None;
    let mut round_mode = round::Mode::Trunc;
    let mut round_increment = DateRoundIncrement::MIN;

    handle_kwargs("in_units", kwargs, |key, value, eq| {
        if eq(key, str_relative_to) {
            relative_to_arg = Some(
                value
                    .extract(state.date_type)
                    .ok_or_type_err("relative_to must be a whenever.Date")?,
            )
        } else if eq(key, str_round_mode) {
            round_mode = round::Mode::from_py(value, round_mode_strs)?;
        } else if eq(key, str_round_increment) {
            round_increment = DateRoundIncrement::from_py(value)?;
        } else {
            return Ok(false);
        }
        Ok(true)
    })?;

    let Some(relative_to) = relative_to_arg else {
        return raise_type_err("missing required keyword argument: 'relative_to'");
    };

    let (months, days) = d.to_months_days().ok_or_range_err()?;
    let shifted = relative_to.shift(months, days).ok_or_range_err()?;

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
    let cal_unit = CalUnit::from_py(handle_one_arg("total", args)?, state)?;
    let relative_to = extract_relative_to_date(
        state,
        handle_one_kwarg("total", state.str_relative_to, kwargs)?,
    )?;
    let (months, days) = d.to_months_days().ok_or_range_err()?;
    let shifted = relative_to.shift(months, days).ok_or_range_err()?;
    total_inner(shifted, relative_to, cal_unit)
}

fn total_inner(a: Date, b: Date, cal_unit: CalUnit) -> PyReturn {
    let sign: i8 = if a >= b { 1 } else { -1 };

    let (trunc_amount, trunc, expand) =
        math::date_diff_single_unit(a, b, DateRoundIncrement::MIN, cal_unit, sign)
            .ok_or_range_err()?;

    let trunc_date = trunc.resolve().unix_days();
    let r = a.unix_days().diff(trunc_date).get() as f64;
    let e = expand.resolve().unix_days().diff(trunc_date).get() as f64;

    (trunc_amount as f64 + (r / e).copysign(e)).to_py()
}

pub(crate) fn handle_date_delta_unit_kwargs(
    key: PyObj,
    value: PyObj,
    months: &mut DeltaMonths,
    days: &mut DeltaDays,
    units: &mut CalUnitSet, // To track which units were set from kwargs
    state: &State,
    eq: impl Fn(PyObj, PyObj) -> bool,
) -> PyResult<bool> {
    let &State {
        str_years,
        str_months,
        str_weeks,
        str_days,
        ..
    } = state;

    if eq(key, str_years) {
        *months = DeltaMonths::from_i64_years(
            value
                .cast_allow_subclass::<PyInt>()
                .ok_or_type_err("years must be an integer")?
                .to_i64()?,
        )
        .ok_or_range_err()?
        .add(*months)
        .ok_or_range_err()?;
        units.insert(CalUnit::Years);
    } else if eq(key, str_months) {
        *months = DeltaMonths::from_i64(
            value
                .cast_allow_subclass::<PyInt>()
                .ok_or_type_err("months must be an integer")?
                .to_i64()?,
        )
        .ok_or_range_err()?
        .add(*months)
        .ok_or_range_err()?;
        units.insert(CalUnit::Months);
    } else if eq(key, str_weeks) {
        *days = DeltaDays::from_i64_weeks(
            value
                .cast_allow_subclass::<PyInt>()
                .ok_or_type_err("weeks must be an integer")?
                .to_i64()?,
        )
        .ok_or_range_err()?
        .add(*days)
        .ok_or_range_err()?;
        units.insert(CalUnit::Weeks);
    } else if eq(key, str_days) {
        *days = DeltaDays::from_i64(
            value
                .cast_allow_subclass::<PyInt>()
                .ok_or_type_err("days must be an integer")?
                .to_i64()?,
        )
        .ok_or_range_err()?
        .add(*days)
        .ok_or_range_err()?;
        units.insert(CalUnit::Days);
    } else {
        return Ok(false);
    }
    Ok(true)
}

fn add_sub(
    cls: HeapType<ItemizedDateDelta>,
    d: ItemizedDateDelta,
    args: &[PyObj],
    kwargs: &mut IterKwargs,
    negate: bool,
) -> PyReturn {
    let fname = if negate { "subtract" } else { "add" };
    let state = cls.state();
    let &State {
        str_relative_to,
        str_units,
        str_round_mode,
        round_mode_strs,
        str_round_increment,
        itemized_date_delta_type,
        ..
    } = state;

    let arg = handle_opt_arg(fname, args)?
        .map(|obj| {
            obj.extract(itemized_date_delta_type)
                .ok_or_type_err("argument must be an ItemizedDateDelta")
        })
        .transpose()?;

    let mut relative_to_arg = None;
    let mut units = CalUnitSet::EMPTY;
    let mut round_mode = round::Mode::Trunc;
    let mut round_increment = DateRoundIncrement::MIN;
    let mut months_from_kwargs = DeltaMonths::ZERO;
    let mut days_from_kwargs = DeltaDays::ZERO;
    let mut units_from_kwargs = CalUnitSet::EMPTY;

    handle_kwargs(fname, kwargs, |key, value, eq| {
        if eq(key, str_relative_to) {
            relative_to_arg = Some(
                value
                    .extract(state.date_type)
                    .ok_or_type_err("relative_to must be a whenever.Date")?,
            );
        } else if eq(key, str_units) {
            units = CalUnitSet::from_py(value, state)?;
        } else if eq(key, str_round_mode) {
            round_mode = round::Mode::from_py(value, round_mode_strs)?;
        } else if eq(key, str_round_increment) {
            round_increment = DateRoundIncrement::from_py(value)?;
        } else {
            return handle_date_delta_unit_kwargs(
                key,
                value,
                &mut months_from_kwargs,
                &mut days_from_kwargs,
                &mut units_from_kwargs,
                state,
                eq,
            );
        }
        Ok(true)
    })?;

    if units.is_empty() {
        raise_type_err("missing required keyword argument: 'units'")?;
    }

    let relative_to =
        relative_to_arg.ok_or_type_err("missing required keyword argument: 'relative_to'")?;

    let (mut months, mut days) = match (arg, units_from_kwargs.is_empty()) {
        (Some(_), false) => {
            raise_type_err("cannot mix positional argument and duration keywords arguments")?
        }
        (Some(other), true) => other.to_months_days().ok_or_range_err()?,
        _ => (months_from_kwargs, days_from_kwargs),
    };

    let (self_months, self_days) = d.to_months_days().ok_or_range_err()?;

    months = months.negate_if(negate);
    days = days.negate_if(negate);

    // TODO LATER: is this right...1 month creating feb 28 will add the next month to march 28?
    // Then shifted becomes 1 months 28 days?
    let shifted = relative_to
        .shift(self_months, self_days)
        .and_then(|d| d.shift(months, days))
        .ok_or_range_err()?;

    date_since_iddelta(shifted, relative_to, units, round_mode, round_increment)?
        .to_obj(itemized_date_delta_type)
}

fn add(
    cls: HeapType<ItemizedDateDelta>,
    d: ItemizedDateDelta,
    args: &[PyObj],
    kwargs: &mut IterKwargs,
) -> PyReturn {
    add_sub(cls, d, args, kwargs, false)
}

fn subtract(
    cls: HeapType<ItemizedDateDelta>,
    d: ItemizedDateDelta,
    args: &[PyObj],
    kwargs: &mut IterKwargs,
) -> PyReturn {
    add_sub(cls, d, args, kwargs, true)
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
