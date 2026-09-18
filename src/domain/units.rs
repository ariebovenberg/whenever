//! The fixed factors between units, and the day counts the calendar
//! algorithms measure from.

pub(crate) const S_PER_MINUTE: i32 = 60;
pub(crate) const S_PER_HOUR: i32 = 60 * S_PER_MINUTE;
pub(crate) const S_PER_DAY: i32 = 24 * S_PER_HOUR;
pub(crate) const DAYS_PER_WEEK: i32 = 7;
pub(crate) const S_PER_WEEK: i32 = DAYS_PER_WEEK * S_PER_DAY;

pub(crate) const NS_PER_MICROSECOND: u32 = 1_000;
pub(crate) const NS_PER_MILLISECOND: u32 = 1_000 * NS_PER_MICROSECOND;
pub(crate) const NS_PER_SECOND: u32 = 1_000 * NS_PER_MILLISECOND;
pub(crate) const NS_PER_MINUTE: u64 = S_PER_MINUTE as u64 * NS_PER_SECOND as u64;
pub(crate) const NS_PER_HOUR: u64 = S_PER_HOUR as u64 * NS_PER_SECOND as u64;
pub(crate) const NS_PER_DAY: u64 = S_PER_DAY as u64 * NS_PER_SECOND as u64;
pub(crate) const NS_PER_WEEK: u64 = S_PER_WEEK as u64 * NS_PER_SECOND as u64;

/// Days from 0001-01-01 to 1970-01-01, counting from zero. The pure-Python
/// backend spans the same days through `datetime.date.toordinal()`, which
/// counts from one, so its offset is one larger.
pub(crate) const DAYS_BEFORE_EPOCH: i32 = 719_162;

/// The years after which the Gregorian calendar repeats, and the days they
/// hold.
pub(crate) const YEARS_PER_GREGORIAN_CYCLE: u32 = 400;
pub(crate) const DAYS_PER_GREGORIAN_CYCLE: u32 = 146_097;

/// Days from 0000-03-01, the March-based epoch the civil-from-days algorithm
/// counts from, to 1970-01-01.
pub(crate) const DAYS_FROM_MARCH_EPOCH_TO_EPOCH: u32 = 719_468;
