use super::{
    itemized_date_delta::ItemizedDateDelta,
    scalar::{DeltaField, NS_PER_HOUR, NS_PER_MINUTE, NS_PER_SEC},
    shift::DateTimeShift,
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

    pub(crate) fn fill_calendar_units(&mut self, data: ItemizedDateDelta) {
        self.years = data.years;
        self.months = data.months;
        self.weeks = data.weeks;
        self.days = data.days;
    }

    pub(crate) fn to_shift(self) -> Option<DateTimeShift> {
        let calendar = ItemizedDateDelta {
            years: self.years,
            months: self.months,
            weeks: self.weeks,
            days: self.days,
        }
        .to_calendar_shift()?;
        let nanos = self.hours.get_or(0) as i128 * NS_PER_HOUR as i128
            + self.minutes.get_or(0) as i128 * NS_PER_MINUTE as i128
            + self.seconds.get_or(0) as i128 * NS_PER_SEC as i128
            + self.nanos.get_or(0) as i128;
        Some(DateTimeShift {
            calendar,
            time: TimeDelta::from_nanos(nanos)?,
        })
    }
}
