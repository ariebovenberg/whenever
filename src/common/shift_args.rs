use crate::{
    classes::{
        itemized_date_delta::ItemizedDateDelta,
        itemized_delta::ItemizedDelta,
        time_delta::{TimeDelta, exact_unit_for_kwarg},
    },
    domain::{
        difference::ExactUnit,
        scalar::{DeltaDays, DeltaMonths},
        shift::{CalendarShift, DateTimeShift},
    },
    py::*,
    pymodule::State,
};

pub(crate) fn parse_calendar_shift_arg(
    fname: &str,
    obj: PyObj,
    state: &State,
) -> PyResult<CalendarShift> {
    if let Some(delta) = ItemizedDateDelta::extract(obj, state)? {
        delta.to_calendar_shift().ok_or_range_err()
    } else {
        raise_type_err(format!("{fname}() argument must be an ItemizedDateDelta"))
    }
}

pub(crate) fn parse_datetime_shift_arg(
    fname: &str,
    obj: PyObj,
    state: &State,
) -> PyResult<DateTimeShift> {
    if let Some(time) = obj.extract(*state.time_delta_type) {
        Ok(time.to_shift())
    } else if let Some(calendar) = ItemizedDateDelta::extract(obj, state)? {
        Ok(calendar.to_calendar_shift().ok_or_range_err()?.to_shift())
    } else if let Some(delta) = ItemizedDelta::extract(obj, state)? {
        delta.to_shift().ok_or_range_err()
    } else {
        raise_type_err(format!(
            "{fname}() argument must be a TimeDelta, ItemizedDelta, or ItemizedDateDelta"
        ))
    }
}

/// Keyword components summed before any range check, as pure Python does:
/// `months=-120000, years=10000` is no shift at all.
#[derive(Default)]
struct KwargSums {
    months: i64,
    days: i64,
    nanos: i128,
}

impl KwargSums {
    fn add_calendar(
        &mut self,
        key: PyObj,
        value: PyObj,
        eq: StrEqFn,
        state: &State,
    ) -> PyResult<bool> {
        let (name, factor, sum) = if eq(key, *state.strs.years) {
            ("years", 12, &mut self.months)
        } else if eq(key, *state.strs.months) {
            ("months", 1, &mut self.months)
        } else if eq(key, *state.strs.weeks) {
            ("weeks", 7, &mut self.days)
        } else if eq(key, *state.strs.days) {
            ("days", 1, &mut self.days)
        } else {
            return Ok(false);
        };
        *sum = value
            .expect_int(name)?
            .to_i64()?
            .checked_mul(factor)
            .and_then(|v| sum.checked_add(v))
            .ok_or_range_err()?;
        Ok(true)
    }

    fn add_exact(
        &mut self,
        key: PyObj,
        value: PyObj,
        eq: StrEqFn,
        state: &State,
    ) -> PyResult<bool> {
        let Some(unit) = exact_unit_for_kwarg(key, eq, state) else {
            return Ok(false);
        };
        debug_assert!(!matches!(unit, ExactUnit::Days | ExactUnit::Weeks));
        self.nanos = self
            .nanos
            .checked_add(unit.parse_py_nanos(value)?)
            .ok_or_range_err()?;
        Ok(true)
    }

    fn calendar(&self) -> PyResult<CalendarShift> {
        Ok(CalendarShift {
            months: DeltaMonths::from_i64(self.months).ok_or_range_err()?,
            days: DeltaDays::from_i64(self.days).ok_or_range_err()?,
        })
    }
}

pub(crate) fn parse_calendar_shift_kwargs<K>(
    fname: &str,
    kwargs: K,
    state: &State,
) -> PyResult<CalendarShift>
where
    K: IntoIterator<Item = (PyObj, PyObj)>,
{
    let mut sums = KwargSums::default();
    handle_kwargs(fname, kwargs, |k, v, eq| sums.add_calendar(k, v, eq, state))?;
    sums.calendar()
}

pub(crate) fn parse_datetime_shift_kwargs<K, F>(
    fname: &str,
    kwargs: K,
    state: &State,
    mut handle_extra: F,
) -> PyResult<DateTimeShift>
where
    K: IntoIterator<Item = (PyObj, PyObj)>,
    F: FnMut(PyObj, PyObj, StrEqFn) -> PyResult<bool>,
{
    let mut sums = KwargSums::default();
    handle_kwargs(fname, kwargs, |k, v, eq| {
        Ok(sums.add_calendar(k, v, eq, state)?
            || sums.add_exact(k, v, eq, state)?
            || handle_extra(k, v, eq)?)
    })?;
    Ok(DateTimeShift {
        calendar: sums.calendar()?,
        time: TimeDelta::from_nanos(sums.nanos).ok_or_range_err()?,
    })
}
