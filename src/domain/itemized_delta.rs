use super::{
    itemized_date_delta::ItemizedDateDelta,
    scalar::{DeltaDays, DeltaField, DeltaMonths, NS_PER_HOUR, NS_PER_MINUTE, NS_PER_SEC},
    time_delta::TimeDelta,
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
        Some((months, days, TimeDelta::from_nanos(nanos)?))
    }
}
