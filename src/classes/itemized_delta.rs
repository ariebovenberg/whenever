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

    pub(crate) fn fill_cal_units(&mut self, data: ItemizedDateDelta) {
        self.years = data.years;
        self.months = data.months;
        self.weeks = data.weeks;
        self.days = data.days;
    }

    pub(crate) fn to_components(self) -> Option<(DeltaMonths, DeltaDays, TimeDelta)> {
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

    pub(crate) fn extract(obj: PyObj, state: &State) -> PyResult<Option<Self>> {
        if obj.type_().as_py_obj() != state.itemized_delta_type.get()? {
            return Ok(None);
        }
        let tup = obj.getattr(c"_to_tuple")?.call0()?.to_tuple()?;
        debug_assert!(tup.len() == 8);
        let mut iter = tup.iter();
        Ok(Some(Self {
            years: DeltaField::from_py_opt(iter.next().unwrap())?,
            months: DeltaField::from_py_opt(iter.next().unwrap())?,
            weeks: DeltaField::from_py_opt(iter.next().unwrap())?,
            days: DeltaField::from_py_opt(iter.next().unwrap())?,
            hours: DeltaField::from_py_opt(iter.next().unwrap())?,
            minutes: DeltaField::from_py_opt(iter.next().unwrap())?,
            seconds: DeltaField::from_py_opt(iter.next().unwrap())?,
            nanos: DeltaField::from_py_opt(iter.next().unwrap())?,
        }))
    }

    pub(crate) fn to_obj(self, state: &State) -> PyReturn {
        state.unpickle_itemized_delta.get()?.call_args([
            *self.years.to_py()?,
            *self.months.to_py()?,
            *self.weeks.to_py()?,
            *self.days.to_py()?,
            *self.hours.to_py()?,
            *self.minutes.to_py()?,
            *self.seconds.to_py()?,
            *self.nanos.to_py()?,
        ])
    }
}

#[allow(clippy::too_many_arguments)]
pub(crate) fn handle_delta_unit_kwargs(
    key: PyObj,
    value: PyObj,
    months: &mut DeltaMonths,
    days: &mut DeltaDays,
    time: &mut TimeDelta,
    units: &mut DeltaUnitSet,
    eq: StrEqFn,
    allow_milliseconds: bool,
    allow_microseconds: bool,
    state: &State,
) -> PyResult<bool> {
    if eq(key, *state.str_years) {
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
    } else if eq(key, *state.str_months) {
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
    } else if eq(key, *state.str_weeks) {
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
    } else if eq(key, *state.str_days) {
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
    } else if eq(key, *state.str_hours) {
        *time = time
            .add(ExactUnit::Hours.parse_py_number(value)?)
            .ok_or_range_err()?;
        units.insert(DeltaUnit::Hours);
    } else if eq(key, *state.str_minutes) {
        *time = time
            .add(ExactUnit::Minutes.parse_py_number(value)?)
            .ok_or_range_err()?;
        units.insert(DeltaUnit::Minutes);
    } else if eq(key, *state.str_seconds) {
        *time = time
            .add(ExactUnit::Seconds.parse_py_number(value)?)
            .ok_or_range_err()?;
        units.insert(DeltaUnit::Seconds);
    } else if allow_milliseconds && eq(key, *state.str_milliseconds) {
        *time = time
            .add(ExactUnit::Milliseconds.parse_py_number(value)?)
            .ok_or_range_err()?;
        units.insert(DeltaUnit::Nanoseconds);
    } else if allow_microseconds && eq(key, *state.str_microseconds) {
        *time = time
            .add(ExactUnit::Microseconds.parse_py_number(value)?)
            .ok_or_range_err()?;
        units.insert(DeltaUnit::Nanoseconds);
    } else if eq(key, *state.str_nanoseconds) {
        *time = time
            .add(ExactUnit::Nanoseconds.parse_py_number(value)?)
            .ok_or_range_err()?;
        units.insert(DeltaUnit::Nanoseconds);
    } else {
        return Ok(false);
    }
    Ok(true)
}
