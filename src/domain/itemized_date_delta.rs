use super::{
    date::Date,
    instant::Instant,
    round,
    scalar::{DeltaDays, DeltaField, DeltaMonths},
};
use crate::common::math::{CalUnit, DateRoundIncrement, round_by_days, round_by_time};

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

    pub(crate) fn to_months_days(self) -> Option<(DeltaMonths, DeltaDays)> {
        DeltaMonths::new(
            self.years
                .get_or(0)
                .checked_mul(12)?
                .checked_add(self.months.get_or(0))?,
        )
        .zip(DeltaDays::new(
            self.weeks
                .get_or(0)
                .checked_mul(7)?
                .checked_add(self.days.get_or(0))?,
        ))
    }

    #[allow(clippy::too_many_arguments)]
    pub(crate) fn round_by_days(
        &mut self,
        unit: CalUnit,
        target: Date,
        trunc: Date,
        expand: Date,
        mode: round::AbsMode,
        increment: DateRoundIncrement,
        neg: bool,
    ) {
        let field = unit.field(self);
        field.replace_unchecked(round_by_days(
            field.unwrap(),
            target,
            trunc,
            expand,
            mode,
            increment,
            neg,
        ));
    }

    #[allow(clippy::too_many_arguments)]
    pub(crate) fn round_by_time(
        &mut self,
        unit: CalUnit,
        target: Instant,
        trunc: Instant,
        expand: Instant,
        mode: round::AbsMode,
        increment: DateRoundIncrement,
        neg: bool,
    ) {
        let field = unit.field(self);
        field.replace_unchecked(round_by_time(
            field.unwrap(),
            target,
            trunc,
            expand,
            mode,
            increment,
            neg,
        ));
    }
}
