use crate::{
    classes::{date::Date, instant::Instant},
    common::{
        math::{CalUnit, DateRoundIncrement, round_by_days, round_by_time},
        round,
        scalar::{DeltaDays, DeltaField, DeltaMonths},
    },
    py::*,
    pymodule::State,
};

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

    #[allow(clippy::too_many_arguments)]
    pub(crate) fn round_by_days(
        &mut self,
        unit: CalUnit,
        target: Date,
        trunc: Date,
        expand: Date,
        mode: round::AbsMode,
        round_increment: DateRoundIncrement,
        neg: bool,
    ) {
        let field = unit.field(self);
        field.replace_unchecked(round_by_days(
            field.unwrap(),
            target,
            trunc,
            expand,
            mode,
            round_increment,
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
        round_increment: DateRoundIncrement,
        neg: bool,
    ) {
        let field = unit.field(self);
        field.replace_unchecked(round_by_time(
            field.unwrap(),
            target,
            trunc,
            expand,
            mode,
            round_increment,
            neg,
        ));
    }

    pub(crate) fn extract(obj: PyObj, state: &State) -> PyResult<Option<Self>> {
        if obj.type_().as_py_obj() != state.itemized_date_delta_type.get()? {
            return Ok(None);
        }
        let tup = obj.getattr(c"_to_tuple")?.call0()?.to_tuple()?;
        debug_assert!(tup.len() == 4);
        let mut iter = tup.iter();
        Ok(Some(Self {
            years: DeltaField::from_py_opt(iter.next().unwrap())?,
            months: DeltaField::from_py_opt(iter.next().unwrap())?,
            weeks: DeltaField::from_py_opt(iter.next().unwrap())?,
            days: DeltaField::from_py_opt(iter.next().unwrap())?,
        }))
    }

    pub(crate) fn to_obj(self, state: &State) -> PyReturn {
        state.unpickle_itemized_date_delta.get()?.call_args([
            *self.years.to_py()?,
            *self.months.to_py()?,
            *self.weeks.to_py()?,
            *self.days.to_py()?,
        ])
    }
}
