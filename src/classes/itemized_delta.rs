use core::ffi::{c_int, c_void};
use pyo3_ffi::*;
use std::ptr::null_mut as NULL;

use crate::{
    classes::{
        date_delta::parse_prefix,
        itemized_date_delta::{
            parse_date_fields, ItemizedDateDelta, MAX_DAYS, MAX_MONTHS, MAX_WEEKS, MAX_YEARS,
        },
        time_delta::{parse_time_component, TimeUnit, TimeDelta},
    },
    common::{
        cal_diff::{DeltaUnit, UnitSet},
        scalar::{DeltaField, DeltaSeconds, SubSecNanos},
    },
    docstrings as doc,
    py::*,
    pymodule::State,
};

const MAX_HOURS: u64 = 9999 * 366 * 24;
const MAX_MINUTES: u64 = 9999 * 366 * 24 * 60;
const MAX_SECONDS: u64 = 9999 * 366 * 24 * 60 * 60;
const MAX_NANOS: u64 = 999_999_999;

#[derive(Debug, Copy, Clone, PartialEq, Eq)]
pub(crate) struct ItemizedDelta {
    pub(crate) years: DeltaField<i32>,
    pub(crate) months: DeltaField<i32>,
    pub(crate) weeks: DeltaField<i32>,
    pub(crate) days: DeltaField<i32>,
    pub(crate) hours: DeltaField<i32>,
    pub(crate) minutes: DeltaField<i64>,
    pub(crate) seconds: DeltaField<i64>,
    pub(crate) nanos: DeltaField<i32>,
}

impl ItemizedDelta {
    /// Build from absolute results array and sign.
    /// Only fields whose unit is in `requested` are set; others are UNSET.
    pub(crate) fn from_results(results: &[i64; 8], requested: UnitSet, sign: i8) -> Self {
        let s = sign as i64;
        let field_i32 = |u: DeltaUnit| -> DeltaField<i32> {
            if requested.contains(u) {
                DeltaField::new_unchecked(results[u as usize] as i32 * sign as i32)
            } else {
                DeltaField::UNSET
            }
        };
        let field_i64 = |u: DeltaUnit| -> DeltaField<i64> {
            if requested.contains(u) {
                DeltaField::new_unchecked(results[u as usize] * s)
            } else {
                DeltaField::UNSET
            }
        };
        Self {
            years: field_i32(DeltaUnit::Years),
            months: field_i32(DeltaUnit::Months),
            weeks: field_i32(DeltaUnit::Weeks),
            days: field_i32(DeltaUnit::Days),
            hours: field_i32(DeltaUnit::Hours),
            minutes: field_i64(DeltaUnit::Minutes),
            seconds: field_i64(DeltaUnit::Seconds),
            nanos: field_i32(DeltaUnit::Nanoseconds),
        }
    }

    pub(crate) fn is_zero(self) -> bool {
        self.derived_sign() == 0
    }

    pub(crate) fn derived_sign(self) -> i8 {
        for s in [
            self.years.sign(),
            self.months.sign(),
            self.weeks.sign(),
            self.days.sign(),
            self.hours.sign(),
            self.minutes.sign(),
            self.seconds.sign(),
            self.nanos.sign(),
        ] {
            if s != 0 {
                return s;
            }
        }
        0
    }

    fn len(self) -> usize {
        self.years.is_set() as usize
            + self.months.is_set() as usize
            + self.weeks.is_set() as usize
            + self.days.is_set() as usize
            + self.hours.is_set() as usize
            + self.minutes.is_set() as usize
            + self.seconds.is_set() as usize
            + self.nanos.is_set() as usize
    }

    fn eq_semantic(self, other: Self) -> bool {
        self.years.get_or(0) == other.years.get_or(0)
            && self.months.get_or(0) == other.months.get_or(0)
            && self.weeks.get_or(0) == other.weeks.get_or(0)
            && self.days.get_or(0) == other.days.get_or(0)
            && self.hours.get_or(0) == other.hours.get_or(0)
            && self.minutes.get_or(0) == other.minutes.get_or(0)
            && self.seconds.get_or(0) == other.seconds.get_or(0)
            && self.nanos.get_or(0) == other.nanos.get_or(0)
    }

    fn has_time(self) -> bool {
        self.hours.is_set() || self.minutes.is_set()
            || self.seconds.is_set() || self.nanos.is_set()
    }

    fn fmt_iso(self, lowercase: bool) -> String {
        let (y, m, w, d, h, s) = if lowercase {
            ('y', 'm', 'w', 'd', 'h', 's')
        } else {
            ('Y', 'M', 'W', 'D', 'H', 'S')
        };
        let m_time = if lowercase { 'm' } else { 'M' };
        let mut out = String::with_capacity(32);
        if self.derived_sign() == -1 {
            out.push('-');
        }
        out.push('P');

        if self.years.is_set() {
            out.push_str(&format!("{}{y}", self.years.unsigned_abs()));
        }
        if self.months.is_set() {
            out.push_str(&format!("{}{m}", self.months.unsigned_abs()));
        }
        if self.weeks.is_set() {
            out.push_str(&format!("{}{w}", self.weeks.unsigned_abs()));
        }
        if self.days.is_set() {
            out.push_str(&format!("{}{d}", self.days.unsigned_abs()));
        }

        if !self.has_time() {
            return out;
        }

        out.push('T');

        if self.hours.is_set() {
            out.push_str(&format!("{}{h}", self.hours.unsigned_abs()));
        }
        if self.minutes.is_set() {
            out.push_str(&format!("{}{m_time}", self.minutes.unsigned_abs()));
        }
        if self.seconds.is_set() {
            let sec_abs = self.seconds.unsigned_abs();
            if self.nanos.is_set() {
                let nanos_abs = self.nanos.get().unsigned_abs() as i32;
                if nanos_abs != 0 {
                    let (buf, len) = SubSecNanos::new_unchecked(nanos_abs).format_iso();
                    out.push_str(&format!("{sec_abs}"));
                    out.push_str(core::str::from_utf8(&buf[..len]).unwrap());
                    out.push(s);
                } else {
                    out.push_str(&format!("{sec_abs}.0{s}"));
                }
            } else {
                out.push_str(&format!("{sec_abs}{s}"));
            }
        }

        out
    }

    /// Look up a field by its interned string key.
    /// Returns the value as PyReturn if found and set.
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
            } else if eq(key, state.str_hours) {
                self.hours.to_py_if_set()
            } else if eq(key, state.str_minutes) {
                self.minutes.to_py_if_set()
            } else if eq(key, state.str_seconds) {
                self.seconds.to_py_if_set()
            } else if eq(key, state.str_nanoseconds) {
                self.nanos.to_py_if_set()
            } else {
                None
            }
        })
    }

    /// Check if a field key is present (for __contains__).
    fn contains_field(self, key: PyObj, state: &State) -> bool {
        check_interned(key, |key, eq| {
            (eq(key, state.str_years) && self.years.is_set())
                || (eq(key, state.str_months) && self.months.is_set())
                || (eq(key, state.str_weeks) && self.weeks.is_set())
                || (eq(key, state.str_days) && self.days.is_set())
                || (eq(key, state.str_hours) && self.hours.is_set())
                || (eq(key, state.str_minutes) && self.minutes.is_set())
                || (eq(key, state.str_seconds) && self.seconds.is_set())
                || (eq(key, state.str_nanoseconds) && self.nanos.is_set())
        })
    }
}

impl PySimpleAlloc for ItemizedDelta {}

fn __new__(
    cls: HeapType<ItemizedDelta>,
    args: PyTuple,
    kwargs: Option<PyDict>,
) -> PyReturn {
    match args.len() {
        0 => {}
        1 if kwargs.map_or(0, |s| s.len()) == 0 => {
            return parse_iso(cls, args.iter().next().unwrap());
        }
        _ => {
            return raise_type_err(
                "ItemizedDelta() takes either 1 positional argument or only keyword arguments",
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
    let mut hours = DeltaField::UNSET;
    let mut minutes = DeltaField::UNSET;
    let mut seconds = DeltaField::UNSET;
    let mut nanos = DeltaField::UNSET;

    handle_kwargs("ItemizedDelta", kwarg_dict.iteritems(), |key, value, eq| {
        if eq(key, state.str_years) {
            years = DeltaField::parse(value, &mut sign, MAX_YEARS)?;
        } else if eq(key, state.str_months) {
            months = DeltaField::parse(value, &mut sign, MAX_MONTHS)?;
        } else if eq(key, state.str_weeks) {
            weeks = DeltaField::parse(value, &mut sign, MAX_WEEKS)?;
        } else if eq(key, state.str_days) {
            days = DeltaField::parse(value, &mut sign, MAX_DAYS)?;
        } else if eq(key, state.str_hours) {
            hours = DeltaField::parse(value, &mut sign, MAX_HOURS)?;
        } else if eq(key, state.str_minutes) {
            minutes = DeltaField::parse(value, &mut sign, MAX_MINUTES)?;
        } else if eq(key, state.str_seconds) {
            seconds = DeltaField::parse(value, &mut sign, MAX_SECONDS)?;
        } else if eq(key, state.str_nanoseconds) {
            nanos = DeltaField::parse(value, &mut sign, MAX_NANOS)?;
        } else {
            return Ok(false);
        }
        Ok(true)
    })?;

    // nanoseconds implies seconds
    if nanos.is_set() && !seconds.is_set() {
        seconds = DeltaField::new_unchecked(0);
    }

    if !years.is_set()
        && !months.is_set()
        && !weeks.is_set()
        && !days.is_set()
        && !hours.is_set()
        && !minutes.is_set()
        && !seconds.is_set()
        && !nanos.is_set()
    {
        return raise_value_err("At least one field must be set");
    }

    ItemizedDelta {
        years,
        months,
        weeks,
        days,
        hours,
        minutes,
        seconds,
        nanos,
    }
    .to_obj(cls)
}

fn sign(_: PyType, d: ItemizedDelta) -> PyReturn {
    (d.derived_sign() as i32).to_py()
}

fn format_iso(
    cls: HeapType<ItemizedDelta>,
    d: ItemizedDelta,
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

fn parse_iso(cls: HeapType<ItemizedDelta>, arg: PyObj) -> PyReturn {
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

    // Reject strings ending in 'T'
    if s.last().unwrap().eq_ignore_ascii_case(&b'T') {
        raise_value_err(err())?;
    }

    let negated = parse_prefix(s).ok_or_else_value_err(err)?;
    let (years, months, weeks, days) = parse_date_fields(s, negated, &err)?;

    let mut hours = DeltaField::UNSET;
    let mut minutes = DeltaField::UNSET;
    let mut seconds = DeltaField::UNSET;
    let mut nanos = DeltaField::UNSET;

    // Parse optional 'T' and time components
    if !s.is_empty() {
        if !s[0].eq_ignore_ascii_case(&b'T') {
            raise_value_err(err())?;
        }
        *s = &s[1..];

        let mut prev_time: Option<TimeUnit> = None;
        while !s.is_empty() {
            let (value, unit) = parse_time_component(s).ok_or_else_value_err(err)?;
            if prev_time.is_some_and(|p| p >= unit) {
                raise_value_err(err())?;
            }
            match unit {
                TimeUnit::Hours => {
                    hours = DeltaField::<i32>::new_checked(
                        value as u64, negated, MAX_HOURS,
                    )
                    .ok_or_else_value_err(|| "Delta out of range")?;
                }
                TimeUnit::Minutes => {
                    minutes = DeltaField::<i64>::new_checked(
                        value as u64, negated, MAX_MINUTES,
                    )
                    .ok_or_else_value_err(|| "Delta out of range")?;
                }
                TimeUnit::Nanos { has_fraction } => {
                    let sec_val = (value / 1_000_000_000) as u64;
                    seconds = DeltaField::<i64>::new_checked(
                        sec_val, negated, MAX_SECONDS,
                    )
                    .ok_or_else_value_err(|| "Delta out of range")?;

                    if has_fraction {
                        let nano_val = (value % 1_000_000_000) as u64;
                        nanos = DeltaField::<i32>::new_checked(
                            nano_val, negated, MAX_NANOS,
                        )
                        .ok_or_else_value_err(|| "Delta out of range")?;
                    }

                    if !s.is_empty() {
                        raise_value_err(err())?;
                    }
                    break;
                }
            }
            prev_time = Some(unit);
        }
    }

    ItemizedDelta {
        years,
        months,
        weeks,
        days,
        hours,
        minutes,
        seconds,
        nanos,
    }
    .to_obj(cls)
}

fn __richcmp__(
    cls: HeapType<ItemizedDelta>,
    a: ItemizedDelta,
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

fn __neg__(cls: HeapType<ItemizedDelta>, slf: PyObj) -> PyReturn {
    let (_, d) = unsafe { slf.assume_heaptype::<ItemizedDelta>() };
    if d.derived_sign() == 0 {
        return Ok(slf.newref());
    }
    ItemizedDelta {
        years: d.years.neg(),
        months: d.months.neg(),
        weeks: d.weeks.neg(),
        days: d.days.neg(),
        hours: d.hours.neg(),
        minutes: d.minutes.neg(),
        seconds: d.seconds.neg(),
        nanos: d.nanos.neg(),
    }
    .to_obj(cls)
}

fn __abs__(cls: HeapType<ItemizedDelta>, slf: PyObj) -> PyReturn {
    let (_, d) = unsafe { slf.assume_heaptype::<ItemizedDelta>() };
    if d.derived_sign() >= 0 {
        Ok(slf.newref())
    } else {
        ItemizedDelta {
            years: d.years.neg(),
            months: d.months.neg(),
            weeks: d.weeks.neg(),
            days: d.days.neg(),
            hours: d.hours.neg(),
            minutes: d.minutes.neg(),
            seconds: d.seconds.neg(),
            nanos: d.nanos.neg(),
        }
        .to_obj(cls)
    }
}

fn __repr__(_: PyType, d: ItemizedDelta) -> PyReturn {
    format!("ItemizedDelta(\"{}\")", d.fmt_iso(true)).to_py()
}

fn __str__(_: PyType, d: ItemizedDelta) -> PyReturn {
    d.fmt_iso(false).to_py()
}

extern "C" fn __bool__(slf: PyObj) -> c_int {
    (!unsafe { slf.assume_heaptype::<ItemizedDelta>() }.1.is_zero()).into()
}

extern "C" fn __mp_length__(slf: PyObj) -> Py_ssize_t {
    unsafe { slf.assume_heaptype::<ItemizedDelta>() }.1.len() as Py_ssize_t
}

extern "C" fn __mp_subscript__(slf: PyObj, key: PyObj) -> *mut PyObject {
    let (cls, d) = unsafe { slf.assume_heaptype::<ItemizedDelta>() };
    _mp_subscript_inner(cls, d, key).to_py_owned_ptr()
}

fn _mp_subscript_inner(
    cls: HeapType<ItemizedDelta>,
    d: ItemizedDelta,
    key: PyObj,
) -> PyReturn {
    match d.find_field(key, cls.state()) {
        Some(result) => result,
        None => raise_key_err(key),
    }
}

extern "C" fn __tp_iter__(slf_ptr: *mut PyObject) -> *mut PyObject {
    let slf = unsafe { PyObj::from_ptr_unchecked(slf_ptr) };
    let (cls, d) = unsafe { slf.assume_heaptype::<ItemizedDelta>() };
    catch_panic!(_iter_inner(cls, d).to_py_owned_ptr())
}

fn _iter_inner(cls: HeapType<ItemizedDelta>, d: ItemizedDelta) -> PyReturn {
    let &State {
        str_years,
        str_months,
        str_weeks,
        str_days,
        str_hours,
        str_minutes,
        str_seconds,
        str_nanoseconds,
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
        i += 1;
    }
    if d.hours.is_set() {
        tup.init_item(i, str_hours.newref());
        i += 1;
    }
    if d.minutes.is_set() {
        tup.init_item(i, str_minutes.newref());
        i += 1;
    }
    if d.seconds.is_set() {
        tup.init_item(i, str_seconds.newref());
        i += 1;
    }
    if d.nanos.is_set() {
        tup.init_item(i, str_nanoseconds.newref());
    }

    tup.py_iter()
}

extern "C" fn __sq_contains__(slf: PyObj, key: PyObj) -> c_int {
    let (cls, d) = unsafe { slf.assume_heaptype::<ItemizedDelta>() };
    d.contains_field(key, cls.state()) as c_int
}

fn exact_eq(cls: HeapType<ItemizedDelta>, d: ItemizedDelta, arg: PyObj) -> PyReturn {
    match arg.extract(cls) {
        Some(other) => (d == other).to_py(),
        None => false.to_py(),
    }
}

fn replace(
    cls: HeapType<ItemizedDelta>,
    d: ItemizedDelta,
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
    let mut hours = d.hours;
    let mut minutes = d.minutes;
    let mut seconds = d.seconds;
    let mut nanos = d.nanos;

    handle_kwargs("replace", kwargs, |key, value, eq| {
        if eq(key, state.str_years) {
            years = DeltaField::parse_opt(value, MAX_YEARS)?;
        } else if eq(key, state.str_months) {
            months = DeltaField::parse_opt(value, MAX_MONTHS)?;
        } else if eq(key, state.str_weeks) {
            weeks = DeltaField::parse_opt(value, MAX_WEEKS)?;
        } else if eq(key, state.str_days) {
            days = DeltaField::parse_opt(value, MAX_DAYS)?;
        } else if eq(key, state.str_hours) {
            hours = DeltaField::parse_opt(value, MAX_HOURS)?;
        } else if eq(key, state.str_minutes) {
            minutes = DeltaField::parse_opt(value, MAX_MINUTES)?;
        } else if eq(key, state.str_seconds) {
            seconds = DeltaField::parse_opt(value, MAX_SECONDS)?;
        } else if eq(key, state.str_nanoseconds) {
            nanos = DeltaField::parse_opt(value, MAX_NANOS)?;
        } else {
            return Ok(false);
        }
        Ok(true)
    })?;

    if !years.is_set()
        && !months.is_set()
        && !weeks.is_set()
        && !days.is_set()
        && !hours.is_set()
        && !minutes.is_set()
        && !seconds.is_set()
        && !nanos.is_set()
    {
        return raise_value_err("At least one field must be set");
    }

    // Check sign consistency
    let mut sign: i8 = 0;
    for s in [
        years.sign(),
        months.sign(),
        weeks.sign(),
        days.sign(),
        hours.sign(),
        minutes.sign(),
        seconds.sign(),
        nanos.sign(),
    ] {
        if s != 0 {
            if sign != 0 && sign != s {
                return raise_value_err("Mixed sign in delta");
            }
            sign = s;
        }
    }

    ItemizedDelta {
        years,
        months,
        weeks,
        days,
        hours,
        minutes,
        seconds,
        nanos,
    }
    .to_obj(cls)
}

fn parts(cls: HeapType<ItemizedDelta>, d: ItemizedDelta) -> PyResult<Owned<PyTuple>> {
    let state = cls.state();

    // Date part
    let has_date =
        d.years.is_set() || d.months.is_set() || d.weeks.is_set() || d.days.is_set();
    let date_part = if has_date {
        ItemizedDateDelta {
            years: d.years,
            months: d.months,
            weeks: d.weeks,
            days: d.days,
        }
        .to_obj(state.itemized_date_delta_type)
    } else {
        Ok(none())
    };

    // Time part: construct TimeDelta from hours/minutes/seconds/nanos
    let time_part: PyReturn = if d.has_time() {
        let total_secs: i64 = (d.hours.get_or(0) as i64) * 3600
            + d.minutes.get_or(0) * 60
            + d.seconds.get_or(0);
        // Nanos are capped at 999_999_999, but can be negative.
        // Negative nanos need adjustment since SubSecNanos is always non-negative.
        let nanos_val = d.nanos.get_or(0);
        let (adj_secs, adj_nanos) = if nanos_val >= 0 {
            (total_secs, nanos_val)
        } else {
            (total_secs - 1, 1_000_000_000 + nanos_val)
        };
        TimeDelta {
            secs: DeltaSeconds::new_unchecked(adj_secs),
            subsec: SubSecNanos::new_unchecked(adj_nanos),
        }
        .to_obj(state.time_delta_type)
    } else {
        Ok(none())
    };

    (date_part?, time_part?).into_pytuple()
}

fn __reduce__(
    cls: HeapType<ItemizedDelta>,
    d: ItemizedDelta,
) -> PyResult<Owned<PyTuple>> {
    let state = cls.state();
    let tup = PyTuple::with_len(8)?;
    tup.init_item(0, d.years.to_py()?);
    tup.init_item(1, d.months.to_py()?);
    tup.init_item(2, d.weeks.to_py()?);
    tup.init_item(3, d.days.to_py()?);
    tup.init_item(4, d.hours.to_py()?);
    tup.init_item(5, d.minutes.to_py()?);
    tup.init_item(6, d.seconds.to_py()?);
    tup.init_item(7, d.nanos.to_py()?);

    (state.unpickle_itemized_delta.newref(), tup).into_pytuple()
}

pub(crate) fn unpickle(state: &State, args: &[PyObj]) -> PyReturn {
    let &[years_obj, months_obj, weeks_obj, days_obj, hours_obj, minutes_obj, seconds_obj, nanos_obj] =
        args
    else {
        return raise_type_err("Invalid pickle data");
    };
    ItemizedDelta {
        years: DeltaField::parse_opt(years_obj, MAX_YEARS)?,
        months: DeltaField::parse_opt(months_obj, MAX_MONTHS)?,
        weeks: DeltaField::parse_opt(weeks_obj, MAX_WEEKS)?,
        days: DeltaField::parse_opt(days_obj, MAX_DAYS)?,
        hours: DeltaField::parse_opt(hours_obj, MAX_HOURS)?,
        minutes: DeltaField::parse_opt(minutes_obj, MAX_MINUTES)?,
        seconds: DeltaField::parse_opt(seconds_obj, MAX_SECONDS)?,
        nanos: DeltaField::parse_opt(nanos_obj, MAX_NANOS)?,
    }
    .to_obj(state.itemized_delta_type)
}

#[allow(static_mut_refs)]
static mut SLOTS: &[PyType_Slot] = &[
    slotmethod!(ItemizedDelta, Py_tp_new, __new__),
    slotmethod!(ItemizedDelta, Py_tp_richcompare, __richcmp__),
    slotmethod!(ItemizedDelta, Py_nb_negative, __neg__, 1),
    slotmethod!(ItemizedDelta, Py_tp_repr, __repr__, 1),
    slotmethod!(ItemizedDelta, Py_tp_str, __str__, 1),
    slotmethod!(ItemizedDelta, Py_nb_absolute, __abs__, 1),
    PyType_Slot {
        slot: Py_tp_doc,
        pfunc: doc::ITEMIZEDDELTA.as_ptr() as *mut c_void,
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
        ItemizedDelta,
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
    method0!(ItemizedDelta, __copy__, c""),
    method1!(ItemizedDelta, __deepcopy__, c""),
    method_kwargs!(
        ItemizedDelta,
        format_iso,
        doc::ITEMIZEDDELTA_FORMAT_ISO
    ),
    classmethod1!(
        ItemizedDelta,
        parse_iso,
        doc::ITEMIZEDDELTA_PARSE_ISO
    ),
    method1!(
        ItemizedDelta,
        exact_eq,
        doc::ITEMIZEDDELTA_EXACT_EQ
    ),
    method_kwargs!(
        ItemizedDelta,
        replace,
        doc::ITEMIZEDDELTA_REPLACE
    ),
    method0!(ItemizedDelta, parts, doc::ITEMIZEDDELTA_PARTS),
    method0!(ItemizedDelta, __reduce__, c""),
    classmethod_kwargs!(
        ItemizedDelta,
        __get_pydantic_core_schema__,
        doc::PYDANTIC_SCHEMA
    ),
    PyMethodDef::zeroed(),
];

pub(crate) static mut SPEC: PyType_Spec =
    type_spec::<ItemizedDelta>(c"whenever.ItemizedDelta", unsafe { SLOTS });
