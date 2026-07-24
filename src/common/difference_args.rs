//! Python argument parsing for difference operations.

use crate::{
    domain::{
        difference::{
            CalendarIncrement, CalendarUnit, CalendarUnitSet, DifferenceIncrement, DifferenceSpec,
            DifferenceUnit, DifferenceUnitSet, ExactUnit, TotalUnit,
        },
        round,
        time_delta::TimeDelta,
    },
    py::*,
    pymodule::State,
};

impl CalendarUnit {
    pub(crate) fn from_py(v: PyObj, state: &State) -> PyResult<Self> {
        find_interned(v, |v, eq| {
            Some(if eq(v, *state.str_years) {
                Self::Years
            } else if eq(v, *state.str_months) {
                Self::Months
            } else if eq(v, *state.str_weeks) {
                Self::Weeks
            } else if eq(v, *state.str_days) {
                Self::Days
            } else {
                None?
            })
        })
        .ok_or_else_value_err(|| {
            format!("Invalid unit {v}. Unit must be one of 'years', 'months', 'weeks', 'days'")
        })
    }
}

impl CalendarUnitSet {
    pub(crate) fn from_py(v: PyObj, state: &State) -> PyResult<Self> {
        let mut units = Self::EMPTY;
        let mut prev = None;
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
}

impl DifferenceUnit {
    pub(crate) fn from_py(v: PyObj, state: &State) -> PyResult<Self> {
        find_interned(v, |v, eq| {
            Some(if eq(v, *state.str_years) {
                Self::Years
            } else if eq(v, *state.str_months) {
                Self::Months
            } else if eq(v, *state.str_weeks) {
                Self::Weeks
            } else if eq(v, *state.str_days) {
                Self::Days
            } else if eq(v, *state.str_hours) {
                Self::Hours
            } else if eq(v, *state.str_minutes) {
                Self::Minutes
            } else if eq(v, *state.str_seconds) {
                Self::Seconds
            } else if eq(v, *state.str_nanoseconds) {
                Self::Nanoseconds
            } else {
                None?
            })
        })
        .ok_or_else_value_err(|| format!(
            "Invalid unit {v}. Unit must be one of 'years', 'months', 'weeks', 'days', 'hours', 'minutes', 'seconds', 'nanoseconds'"
        ))
    }
}

impl ExactUnit {
    pub(crate) fn parse_py_number(self, v: PyObj) -> PyResult<TimeDelta> {
        if let Some(i) = v.cast_allow_subclass::<PyInt>() {
            self.parse_py_int(i)
        } else if let Some(f) = v.cast_allow_subclass::<PyFloat>() {
            if self == Self::Nanoseconds {
                raise_value_err("nanoseconds must be an integer, not a float")?;
            }
            self.parse_py_float(f)
        } else {
            raise_value_err(format!("{} must be an integer or float", self.name()))
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

impl DifferenceUnitSet {
    pub(crate) fn from_py(v: PyObj, state: &State) -> PyResult<Self> {
        let mut units = Self::EMPTY;
        let mut prev = None;
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
}

impl TotalUnit {
    pub(crate) fn from_py(v: PyObj, state: &State) -> PyResult<Self> {
        find_interned(v, |v, eq| {
            Some(if eq(v, *state.str_years) {
                Self::Years
            } else if eq(v, *state.str_months) {
                Self::Months
            } else if eq(v, *state.str_weeks) {
                Self::Weeks
            } else if eq(v, *state.str_days) {
                Self::Days
            } else if eq(v, *state.str_hours) {
                Self::Hours
            } else if eq(v, *state.str_minutes) {
                Self::Minutes
            } else if eq(v, *state.str_seconds) {
                Self::Seconds
            } else if eq(v, *state.str_milliseconds) {
                Self::Milliseconds
            } else if eq(v, *state.str_microseconds) {
                Self::Microseconds
            } else if eq(v, *state.str_nanoseconds) {
                Self::Nanoseconds
            } else {
                None?
            })
        })
        .ok_or_else_value_err(|| format!(
            "Invalid unit {v}. Unit must be one of 'years', 'months', 'weeks', 'days', 'hours', 'minutes', 'seconds', 'milliseconds', 'microseconds', 'nanoseconds'"
        ))
    }
}

#[derive(Copy, Clone)]
enum Units {
    One(DifferenceUnit),
    Many(DifferenceUnitSet),
}

impl DifferenceSpec {
    pub(crate) fn parse(fname: &str, kwargs: &mut IterKwargs, state: &State) -> PyResult<Self> {
        Self::parse_with(fname, kwargs, state, |_, _, _| Ok(false))
    }

    pub(crate) fn parse_with<F>(
        fname: &str,
        kwargs: &mut IterKwargs,
        state: &State,
        mut extra: F,
    ) -> PyResult<Self>
    where
        F: FnMut(PyObj, PyObj, StrEqFn) -> PyResult<bool>,
    {
        let mut mode = round::Mode::Trunc;
        let mut increment = DifferenceIncrement::MIN;
        let mut units = None;
        let mut got_rounding = false;
        handle_kwargs(fname, kwargs, |k, v, eq| {
            if eq(k, *state.str_total) {
                if units.is_some() {
                    raise_type_err("cannot specify both 'total' and 'in_units'")?;
                }
                units = Some(Units::One(DifferenceUnit::from_py(v, state)?));
            } else if eq(k, *state.str_in_units) {
                if units.is_some() {
                    raise_type_err("cannot specify both 'total' and 'in_units'")?;
                }
                units = Some(Units::Many(DifferenceUnitSet::from_py(v, state)?));
            } else if eq(k, *state.str_round_mode) {
                mode = round::Mode::from_py_named("round_mode", v, &state.round_mode_strs)?;
                got_rounding = true;
            } else if eq(k, *state.str_round_increment) {
                increment = DifferenceIncrement::from_py(v)?;
                got_rounding = true;
            } else {
                return extra(k, v, eq);
            }
            Ok(true)
        })?;
        match units.ok_or_type_err("must specify either 'total' or 'in_units'")? {
            Units::One(unit) => {
                if got_rounding {
                    raise_type_err(
                        "'round_mode' and 'round_increment' cannot be used with 'total'",
                    )?;
                }
                Ok(Self::Total(unit))
            }
            Units::Many(units) => Ok(Self::InUnits {
                units,
                mode,
                increment,
            }),
        }
    }
}

impl CalendarIncrement {
    pub(crate) fn from_py(v: PyObj) -> PyResult<Self> {
        Self::from_i64(v.expect_int("round_increment")?.to_i64()?)
            .ok_or_value_err("round_increment must be a positive integer in range")
    }
}

impl DifferenceIncrement {
    pub(crate) fn from_py(v: PyObj) -> PyResult<Self> {
        Self::new(v.expect_int("round_increment")?.to_i128()?)
            .ok_or_value_err("round_increment must be a positive integer in range")
    }
}
