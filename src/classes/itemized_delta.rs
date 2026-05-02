use crate::{
    classes::{itemized_date_delta::ItemizedDateDelta, time_delta::TimeDelta},
    common::{
        math::{DeltaUnit, DeltaUnitSet, ExactUnit},
        scalar::{DeltaDays, DeltaField, DeltaMonths, NS_PER_HOUR, NS_PER_MINUTE, NS_PER_SEC},
    },
    py::*,
    pymodule::State,
};

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
    pub(crate) const UNSET: Self = Self {
        years: DeltaField::UNSET,
        months: DeltaField::UNSET,
        weeks: DeltaField::UNSET,
        days: DeltaField::UNSET,
        hours: DeltaField::UNSET,
        minutes: DeltaField::UNSET,
        seconds: DeltaField::UNSET,
        nanos: DeltaField::UNSET,
    };

    // Low-level helper to fill in just the calendar fields from an ItemizedDateDelta
    pub(crate) fn fill_cal_units(&mut self, data: ItemizedDateDelta) {
        self.years = data.years;
        self.months = data.months;
        self.weeks = data.weeks;
        self.days = data.days;
    }

    pub(crate) fn to_components(self) -> Option<(DeltaMonths, DeltaDays, TimeDelta)> {
        // SAFETY: delta values have already been checked to be well within i64/i128 bounds
        let months = DeltaMonths::new(
            (self.years.get_or(0) as i64 * 12 + self.months.get_or(0) as i64) as i32,
        )?;
        let days =
            DeltaDays::new((self.weeks.get_or(0) as i64 * 7 + self.days.get_or(0) as i64) as i32)?;
        let nanos = self.hours.get_or(0) as i128 * NS_PER_HOUR as i128
            + self.minutes.get_or(0) as i128 * NS_PER_MINUTE as i128
            + self.seconds.get_or(0) as i128 * NS_PER_SEC as i128
            + self.nanos.get_or(0) as i128;
        (months, days, TimeDelta::from_nanos(nanos)?).into()
    }
}

impl ItemizedDelta {
    pub(crate) fn from_py_tuple(tup: PyObj) -> PyResult<Self> {
        let tup = tup.to_tuple()?;
        debug_assert!(tup.len() == 8);
        let mut iter = tup.iter();
        Ok(Self {
            years: DeltaField::from_py_opt(iter.next().unwrap())?,
            months: DeltaField::from_py_opt(iter.next().unwrap())?,
            weeks: DeltaField::from_py_opt(iter.next().unwrap())?,
            days: DeltaField::from_py_opt(iter.next().unwrap())?,
            hours: DeltaField::from_py_opt(iter.next().unwrap())?,
            minutes: DeltaField::from_py_opt(iter.next().unwrap())?,
            seconds: DeltaField::from_py_opt(iter.next().unwrap())?,
            nanos: DeltaField::from_py_opt(iter.next().unwrap())?,
        })
    }
}

pub(crate) fn to_py(d: ItemizedDelta, state: &State) -> PyReturn {
    let args = PyTuple::with_len(8)?;
    args.init_item(0, d.years.to_py()?);
    args.init_item(1, d.months.to_py()?);
    args.init_item(2, d.weeks.to_py()?);
    args.init_item(3, d.days.to_py()?);
    args.init_item(4, d.hours.to_py()?);
    args.init_item(5, d.minutes.to_py()?);
    args.init_item(6, d.seconds.to_py()?);
    args.init_item(7, d.nanos.to_py()?);
    state.unpickle_itemized_delta.call(args.borrow())
}

#[allow(clippy::too_many_arguments)]
pub(crate) fn handle_delta_unit_kwargs(
    key: PyObj,
    value: PyObj,
    months: &mut DeltaMonths,
    days: &mut DeltaDays,
    time: &mut TimeDelta,
    units: &mut DeltaUnitSet,
    eq: impl Fn(PyObj, PyObj) -> bool,
    str_years: PyObj,
    str_months: PyObj,
    str_weeks: PyObj,
    str_days: PyObj,
    str_hours: PyObj,
    str_minutes: PyObj,
    str_seconds: PyObj,
    str_milliseconds: Option<PyObj>,
    str_microseconds: Option<PyObj>,
    str_nanoseconds: PyObj,
) -> PyResult<bool> {
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
        units.insert(DeltaUnit::Years);
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
        units.insert(DeltaUnit::Months);
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
        units.insert(DeltaUnit::Weeks);
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
        units.insert(DeltaUnit::Days);
    } else if eq(key, str_hours) {
        *time = time
            .add(ExactUnit::Hours.parse_py_number(value)?)
            .ok_or_range_err()?;
        units.insert(DeltaUnit::Hours);
    } else if eq(key, str_minutes) {
        *time = time
            .add(ExactUnit::Minutes.parse_py_number(value)?)
            .ok_or_range_err()?;
        units.insert(DeltaUnit::Minutes);
    } else if eq(key, str_seconds) {
        *time = time
            .add(ExactUnit::Seconds.parse_py_number(value)?)
            .ok_or_range_err()?;
        units.insert(DeltaUnit::Seconds);
    } else if let Some(str_millis) = str_milliseconds
        && eq(key, str_millis)
    {
        *time = time
            .add(ExactUnit::Milliseconds.parse_py_number(value)?)
            .ok_or_range_err()?;
        units.insert(DeltaUnit::Nanoseconds);
    } else if let Some(str_micros) = str_microseconds
        && eq(key, str_micros)
    {
        *time = time
            .add(ExactUnit::Microseconds.parse_py_number(value)?)
            .ok_or_range_err()?;
        units.insert(DeltaUnit::Nanoseconds);
    } else if eq(key, str_nanoseconds) {
        *time = time
            .add(ExactUnit::Nanoseconds.parse_py_number(value)?)
            .ok_or_range_err()?;
        units.insert(DeltaUnit::Nanoseconds);
    } else {
        return Ok(false);
    }
    Ok(true)
}
