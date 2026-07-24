use super::{
    plain_datetime::PlainDateTime,
    scalar::{DeltaDays, DeltaMonths, EpochSecs, Month, UnixDays, Weekday, Year},
    shift::CalendarShift,
    time::Time,
};
use crate::common::{
    fmt::{self, Chunk},
    parse::{extract_2_digits, extract_digit},
};
use std::fmt::{Display, Formatter};

#[derive(Debug, Eq, PartialEq, Ord, PartialOrd, Copy, Clone)]
pub struct Date {
    pub(crate) year: Year,
    pub(crate) month: Month,
    pub(crate) day: u8,
}

impl Date {
    pub(crate) const MAX: Date = Date {
        year: Year::MAX,
        month: Month::December,
        day: 31,
    };
    pub(crate) const MIN: Date = Date {
        year: Year::MIN,
        month: Month::January,
        day: 1,
    };

    pub fn new(year: Year, month: Month, day: u8) -> Option<Self> {
        (day >= 1 && day <= year.days_in_month(month)).then_some(Date { year, month, day })
    }

    /// Like new(), but clamps the day (up to 31) to shorter months.
    pub fn new_clamp_days(year: Year, month: Month, day: u8) -> Self {
        debug_assert!(day <= 31);
        debug_assert!(day > 0);
        Date {
            year,
            month,
            day: day.min(year.days_in_month(month)),
        }
    }

    pub(crate) fn last_of_month(year: Year, month: Month) -> Self {
        Date {
            year,
            month,
            day: year.days_in_month(month),
        }
    }

    pub(crate) fn first_of_month(year: Year, month: Month) -> Self {
        Date {
            year,
            month,
            day: 1,
        }
    }

    /// Find the nth weekday in a month.
    pub(crate) fn nth_weekday_in_month(
        year: Year,
        month: Month,
        n: i32,
        target_dow: Weekday,
    ) -> Option<Date> {
        debug_assert!(n != 0);
        let target_dow = target_dow as i32;
        let day = if n > 0 {
            let first_dow = Date::first_of_month(year, month).day_of_week() as i32;
            let offset = (target_dow - first_dow).rem_euclid(7);
            1 + offset + (n - 1) * 7
        } else {
            let dim = year.days_in_month(month) as i32;
            let last_dow = Date::last_of_month(year, month).day_of_week() as i32;
            let offset = (last_dow - target_dow).rem_euclid(7);
            dim - offset + (n + 1) * 7
        };
        let dim = year.days_in_month(month) as i32;
        (day >= 1 && day <= dim).then_some(Date {
            year,
            month,
            day: day as u8,
        })
    }

    pub(crate) fn unix_days(self) -> UnixDays {
        // SAFETY: unix days and dates have the same range, so conversion is always valid.
        UnixDays::new_unchecked(
            self.year.days_before()
                + self.year.days_before_month(self.month) as i32
                + self.day as i32
                + UnixDays::MIN.get()
                - 1,
        )
    }

    pub(crate) fn epoch_at(self, time: Time) -> EpochSecs {
        self.unix_days().epoch_at(time)
    }

    pub(crate) fn shift(self, months: DeltaMonths, days: DeltaDays) -> Option<Date> {
        self.shift_months(months)
            .and_then(|date| date.shift_days(days))
    }

    pub(crate) fn shift_by(self, shift: CalendarShift) -> Option<Date> {
        self.shift(shift.months, shift.days)
    }

    pub(crate) fn shift_days(self, days: DeltaDays) -> Option<Date> {
        Some(self.unix_days().shift(days)?.date())
    }

    pub(crate) fn shift_months(self, months: DeltaMonths) -> Option<Date> {
        let (year, month) = self.month.shift(self.year, months)?;
        Some(Date::new_clamp_days(year, month, self.day))
    }

    pub(crate) fn end_of_week_mon(self) -> Option<Date> {
        let days_fwd = 7 - self.unix_days().day_of_week().iso() as i32;
        self.shift_days(DeltaDays::new(days_fwd).unwrap())
    }

    pub(crate) fn end_of_week_sun(self) -> Option<Date> {
        let dow = self.unix_days().day_of_week().iso() as i32;
        let days_fwd = (6 - dow).rem_euclid(7);
        self.shift_days(DeltaDays::new(days_fwd).unwrap())
    }

    /// Parse YYYY-MM-DD.
    pub(crate) fn parse_iso_extended(s: [u8; 10]) -> Option<Self> {
        (s[4] == b'-' && s[7] == b'-')
            .then(|| {
                Date::new(
                    extract_year(&s, 0)?,
                    extract_2_digits(&s, 5).and_then(Month::new)?,
                    extract_2_digits(&s, 8)?,
                )
            })
            .flatten()
    }

    /// Parse YYYYMMDD.
    pub(crate) fn parse_iso_basic(s: [u8; 8]) -> Option<Self> {
        Date::new(
            extract_year(&s, 0)?,
            extract_2_digits(&s, 4).and_then(Month::new)?,
            extract_2_digits(&s, 6)?,
        )
    }

    pub(crate) fn parse_iso(s: &[u8]) -> Option<Self> {
        match s.len() {
            8 => Self::parse_iso_basic(s.try_into().unwrap()),
            10 => Self::parse_iso_extended(s.try_into().unwrap()),
            _ => None,
        }
    }

    pub(crate) fn iso_format(self, basic: bool) -> IsoFormat {
        IsoFormat { date: self, basic }
    }

    pub fn tomorrow(self) -> Option<Self> {
        let Date {
            mut year,
            mut month,
            mut day,
        } = self;
        if day < year.days_in_month(month) {
            day += 1;
        } else if month < Month::December {
            day = 1;
            // SAFETY: this branch excludes December, so incrementing stays within 1..=12.
            month = unsafe { Month::new_unchecked(month.get() + 1) };
        } else {
            day = 1;
            month = Month::January;
            year = Year::new(year.get() + 1)?;
        }
        Some(Date { year, month, day })
    }

    pub(crate) fn yesterday(self) -> Option<Self> {
        let Date {
            mut year,
            mut month,
            mut day,
        } = self;
        if day > 1 {
            day -= 1;
        } else if month > Month::January {
            // SAFETY: this branch excludes January, so decrementing stays within 1..=12.
            month = unsafe { Month::new_unchecked(month.get() - 1) };
            day = year.days_in_month(month);
        } else {
            day = 31;
            month = Month::December;
            year = Year::new(year.get() - 1)?;
        }
        Some(Date { year, month, day })
    }

    pub(crate) fn day_of_week(self) -> Weekday {
        self.unix_days().day_of_week()
    }

    pub(crate) fn day_of_year(self) -> u16 {
        self.year.days_before_month(self.month) + self.day as u16
    }

    pub(crate) fn days_in_month(self) -> u8 {
        self.year.days_in_month(self.month)
    }

    pub(crate) fn days_in_year(self) -> u16 {
        if self.year.is_leap() { 366 } else { 365 }
    }

    pub(crate) fn is_in_leap_year(self) -> bool {
        self.year.is_leap()
    }

    pub(crate) fn iso_year_week(self) -> (i32, u8) {
        let day_of_year = self.day_of_year();
        let dow = self.day_of_week() as u8;
        let nearest_thursday_doy = day_of_year as i32 + (4 - dow as i32);
        let mut iso_year = self.year.get() as i32;

        if nearest_thursday_doy <= 0 {
            iso_year -= 1;
            // SAFETY: only dates after year 1 can belong to the preceding ISO year.
            let prev_year_days = if unsafe { Year::new_unchecked(iso_year as u16) }.is_leap() {
                366
            } else {
                365
            };
            let week = (nearest_thursday_doy + prev_year_days - 1) / 7 + 1;
            (iso_year, week as u8)
        } else {
            let year_days = if self.year.is_leap() { 366 } else { 365 };
            if nearest_thursday_doy > year_days {
                (iso_year + 1, 1)
            } else {
                let week = (nearest_thursday_doy - 1) / 7 + 1;
                (iso_year, week as u8)
            }
        }
    }

    fn start_of_week_mon(self) -> Option<Date> {
        let days_back = self.unix_days().day_of_week().iso() as i32 - 1;
        self.shift_days(DeltaDays::new_unchecked(-days_back))
    }

    fn start_of_week_sun(self) -> Option<Date> {
        let dow = self.unix_days().day_of_week().iso() % 7;
        self.shift_days(DeltaDays::new_unchecked(-(dow as i32)))
    }

    pub(crate) fn start_of(self, unit: DateBoundaryUnit) -> Option<Date> {
        match unit {
            DateBoundaryUnit::WeekMon => self.start_of_week_mon(),
            DateBoundaryUnit::WeekSun => self.start_of_week_sun(),
            DateBoundaryUnit::Month => Some(Date {
                year: self.year,
                month: self.month,
                day: 1,
            }),
            DateBoundaryUnit::Year => Some(Date {
                year: self.year,
                month: Month::January,
                day: 1,
            }),
        }
    }

    pub(crate) fn end_of(self, unit: DateBoundaryUnit) -> Option<Date> {
        match unit {
            DateBoundaryUnit::WeekMon => self.end_of_week_mon(),
            DateBoundaryUnit::WeekSun => self.end_of_week_sun(),
            DateBoundaryUnit::Month => Some(Date {
                day: self.year.days_in_month(self.month),
                ..self
            }),
            DateBoundaryUnit::Year => Some(Date {
                year: self.year,
                ..Date::MAX
            }),
        }
    }

    pub(crate) fn next_start_of(self, unit: DateBoundaryUnit) -> Option<Date> {
        self.end_of(unit)?.tomorrow()
    }

    pub(crate) const fn at(self, time: Time) -> PlainDateTime {
        PlainDateTime { date: self, time }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) enum DateBoundaryUnit {
    Year,
    Month,
    WeekMon,
    WeekSun,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) struct IsoFormat {
    date: Date,
    basic: bool,
}

impl fmt::Chunk for IsoFormat {
    fn len(&self) -> usize {
        if self.basic { 8 } else { 10 }
    }

    fn write(&self, buf: &mut impl fmt::Sink) {
        let Date { year, month, day } = self.date;
        buf.write(fmt::format_4_digits(year.get()).as_ref());
        if self.basic {
            buf.write(fmt::format_2_digits(month.get()).as_ref());
        } else {
            buf.write(b"-");
            buf.write(fmt::format_2_digits(month.get()).as_ref());
            buf.write(b"-");
        }
        buf.write(fmt::format_2_digits(day).as_ref());
    }
}

impl Display for Date {
    fn fmt(&self, f: &mut Formatter<'_>) -> std::fmt::Result {
        let mut s = fmt::ArrayWriter::<10>::new();
        self.iso_format(false).write(&mut s);
        f.write_str(s.finish())
    }
}

pub(crate) fn extract_year(s: &[u8], index: usize) -> Option<Year> {
    Some(
        extract_digit(s, index)? as u16 * 1000
            + extract_digit(s, index + 1)? as u16 * 100
            + extract_digit(s, index + 2)? as u16 * 10
            + extract_digit(s, index + 3)? as u16,
    )
    .filter(|&year| year > 0)
    // SAFETY: the filter excludes zero and four digits cannot exceed 9999.
    .map(|year| unsafe { Year::new_unchecked(year) })
}

#[cfg(test)]
mod tests {
    use super::*;

    fn date(year: u16, month: u8, day: u8) -> Date {
        Date::new(Year::new(year).unwrap(), Month::new(month).unwrap(), day).unwrap()
    }

    #[test]
    fn calendar_properties() {
        let leap_day = date(2024, 2, 29);
        assert_eq!(leap_day.day_of_year(), 60);
        assert_eq!(leap_day.days_in_month(), 29);
        assert_eq!(leap_day.days_in_year(), 366);
        assert!(leap_day.is_in_leap_year());

        let common = date(2023, 12, 31);
        assert_eq!(common.day_of_year(), 365);
        assert_eq!(common.days_in_month(), 31);
        assert_eq!(common.days_in_year(), 365);
        assert!(!common.is_in_leap_year());
    }
}
