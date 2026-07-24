use super::{
    scalar::{DeltaDays, DeltaMonths, NegateIf},
    time_delta::TimeDelta,
};

#[derive(Debug, Copy, Clone, PartialEq, Eq)]
pub(crate) struct CalendarShift {
    pub(crate) months: DeltaMonths,
    pub(crate) days: DeltaDays,
}

impl CalendarShift {
    pub(crate) const ZERO: Self = Self {
        months: DeltaMonths::ZERO,
        days: DeltaDays::ZERO,
    };

    pub(crate) fn add(self, other: Self) -> Option<Self> {
        Some(Self {
            months: self.months.add(other.months)?,
            days: self.days.add(other.days)?,
        })
    }

    pub(crate) fn negate_if(self, negate: bool) -> Self {
        Self {
            months: self.months.negate_if(negate),
            days: self.days.negate_if(negate),
        }
    }

    pub(crate) fn is_zero(self) -> bool {
        self.months.is_zero() && self.days.is_zero()
    }

    pub(crate) const fn to_shift(self) -> DateTimeShift {
        DateTimeShift {
            calendar: self,
            time: TimeDelta::ZERO,
        }
    }
}

#[derive(Debug, Copy, Clone, PartialEq, Eq)]
pub(crate) struct DateTimeShift {
    pub(crate) calendar: CalendarShift,
    pub(crate) time: TimeDelta,
}

impl DateTimeShift {
    pub(crate) const ZERO: Self = Self {
        calendar: CalendarShift::ZERO,
        time: TimeDelta::ZERO,
    };

    pub(crate) fn add(self, other: Self) -> Option<Self> {
        Some(Self {
            calendar: self.calendar.add(other.calendar)?,
            time: self.time.add(other.time)?,
        })
    }

    pub(crate) fn negate_if(self, negate: bool) -> Self {
        Self {
            calendar: self.calendar.negate_if(negate),
            time: self.time.negate_if(negate),
        }
    }
}

impl TimeDelta {
    pub(crate) const fn to_shift(self) -> DateTimeShift {
        DateTimeShift {
            calendar: CalendarShift::ZERO,
            time: self,
        }
    }
}
