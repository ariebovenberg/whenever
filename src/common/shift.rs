use crate::{
    classes::{itemized_date_delta::ItemizedDateDelta, itemized_delta::ItemizedDelta},
    common::{
        math::ExactUnit,
        scalar::{DeltaDays, DeltaMonths},
    },
    domain::shift::{CalendarShift, DateTimeShift},
    py::*,
    pymodule::State,
};

pub(crate) fn parse_calendar_shift_arg(
    fname: &str,
    obj: PyObj,
    state: &State,
) -> PyResult<CalendarShift> {
    if let Some(delta) = obj.extract(*state.date_delta_type) {
        Ok(CalendarShift {
            months: delta.months,
            days: delta.days,
        })
    } else if let Some(delta) = ItemizedDateDelta::extract(obj, state)? {
        delta.to_calendar_shift().ok_or_range_err()
    } else {
        raise_type_err(format!(
            "{fname}() argument must be a DateDelta or ItemizedDateDelta"
        ))
    }
}

pub(crate) fn parse_datetime_shift_arg(
    fname: &str,
    obj: PyObj,
    state: &State,
) -> PyResult<DateTimeShift> {
    if let Some(time) = obj.extract(*state.time_delta_type) {
        Ok(time.to_shift())
    } else if let Some(calendar) = obj.extract(*state.date_delta_type) {
        Ok(CalendarShift {
            months: calendar.months,
            days: calendar.days,
        }
        .to_shift())
    } else if let Some(delta) = obj.extract(*state.datetime_delta_type) {
        Ok(DateTimeShift {
            calendar: CalendarShift {
                months: delta.ddelta.months,
                days: delta.ddelta.days,
            },
            time: delta.tdelta,
        })
    } else if let Some(calendar) = ItemizedDateDelta::extract(obj, state)? {
        Ok(calendar.to_calendar_shift().ok_or_range_err()?.to_shift())
    } else if let Some(delta) = ItemizedDelta::extract(obj, state)? {
        delta.to_shift().ok_or_range_err()
    } else {
        raise_type_err(format!("{fname}() argument must be a delta"))
    }
}

fn parse_calendar_shift_unit(
    key: PyObj,
    value: PyObj,
    eq: StrEqFn,
    state: &State,
) -> PyResult<Option<CalendarShift>> {
    Ok(Some(if eq(key, *state.str_years) {
        CalendarShift {
            months: DeltaMonths::from_i64_years(value.expect_int("years")?.to_i64()?)
                .ok_or_range_err()?,
            days: DeltaDays::ZERO,
        }
    } else if eq(key, *state.str_months) {
        CalendarShift {
            months: DeltaMonths::from_i64(value.expect_int("months")?.to_i64()?)
                .ok_or_range_err()?,
            days: DeltaDays::ZERO,
        }
    } else if eq(key, *state.str_weeks) {
        CalendarShift {
            months: DeltaMonths::ZERO,
            days: DeltaDays::from_i64_weeks(value.expect_int("weeks")?.to_i64()?)
                .ok_or_range_err()?,
        }
    } else if eq(key, *state.str_days) {
        CalendarShift {
            months: DeltaMonths::ZERO,
            days: DeltaDays::from_i64(value.expect_int("days")?.to_i64()?).ok_or_range_err()?,
        }
    } else {
        return Ok(None);
    }))
}

fn parse_datetime_shift_unit(
    key: PyObj,
    value: PyObj,
    eq: StrEqFn,
    state: &State,
) -> PyResult<Option<DateTimeShift>> {
    if let Some(calendar) = parse_calendar_shift_unit(key, value, eq, state)? {
        return Ok(Some(calendar.to_shift()));
    }
    Ok(Some(if eq(key, *state.str_hours) {
        ExactUnit::Hours.parse_py_number(value)?.to_shift()
    } else if eq(key, *state.str_minutes) {
        ExactUnit::Minutes.parse_py_number(value)?.to_shift()
    } else if eq(key, *state.str_seconds) {
        ExactUnit::Seconds.parse_py_number(value)?.to_shift()
    } else if eq(key, *state.str_milliseconds) {
        ExactUnit::Milliseconds.parse_py_number(value)?.to_shift()
    } else if eq(key, *state.str_microseconds) {
        ExactUnit::Microseconds.parse_py_number(value)?.to_shift()
    } else if eq(key, *state.str_nanoseconds) {
        ExactUnit::Nanoseconds.parse_py_number(value)?.to_shift()
    } else {
        return Ok(None);
    }))
}

pub(crate) fn parse_calendar_shift_kwargs<K>(
    fname: &str,
    kwargs: K,
    state: &State,
) -> PyResult<CalendarShift>
where
    K: IntoIterator<Item = (PyObj, PyObj)>,
{
    let mut shift = CalendarShift::ZERO;
    handle_kwargs(fname, kwargs, |k, v, eq| {
        let Some(unit) = parse_calendar_shift_unit(k, v, eq, state)? else {
            return Ok(false);
        };
        shift = shift.add(unit).ok_or_range_err()?;
        Ok(true)
    })?;
    Ok(shift)
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
    let mut shift = DateTimeShift::ZERO;
    handle_kwargs(fname, kwargs, |k, v, eq| {
        if let Some(unit) = parse_datetime_shift_unit(k, v, eq, state)? {
            shift = shift.add(unit).ok_or_range_err()?;
            Ok(true)
        } else {
            handle_extra(k, v, eq)
        }
    })?;
    Ok(shift)
}
