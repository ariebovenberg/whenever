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
        // SAFETY: the rounded value is between trunc and expand,
        // which are both within range.
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
        // SAFETY: the rounded value is between trunc and expand,
        // which are both within range.
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

    pub(crate) fn from_py_tuple(tup: PyObj) -> PyResult<Self> {
        let tup = tup.to_tuple()?;
        debug_assert!(tup.len() == 4);
        let mut iter = tup.iter();
        Ok(Self {
            years: DeltaField::from_py_opt(iter.next().unwrap())?,
            months: DeltaField::from_py_opt(iter.next().unwrap())?,
            weeks: DeltaField::from_py_opt(iter.next().unwrap())?,
            days: DeltaField::from_py_opt(iter.next().unwrap())?,
        })
    }
}

pub(crate) fn to_py(d: ItemizedDateDelta, state: &State) -> PyReturn {
    let args = PyTuple::with_len(4)?;
    args.init_item(0, d.years.to_py()?);
    args.init_item(1, d.months.to_py()?);
    args.init_item(2, d.weeks.to_py()?);
    args.init_item(3, d.days.to_py()?);
    state.unpickle_itemized_date_delta.call(args.borrow())
}
