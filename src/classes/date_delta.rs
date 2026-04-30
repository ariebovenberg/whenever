use core::ffi::c_long;

use crate::{
    common::{math::CalUnit, scalar::*},
    py::*,
};

pub(crate) fn handle_init_kwargs<T>(
    fname: &str,
    kwargs: T,
    str_years: PyObj,
    str_months: PyObj,
    str_days: PyObj,
    str_weeks: PyObj,
) -> PyResult<(DeltaMonths, DeltaDays)>
where
    T: IntoIterator<Item = (PyObj, PyObj)>,
{
    let mut days: c_long = 0;
    let mut months: c_long = 0;
    handle_kwargs(fname, kwargs, |key, value, eq| {
        if eq(key, str_days) {
            days = value
                .cast_allow_subclass::<PyInt>()
                .ok_or_type_err("days must be an integer")?
                .to_long()?
                .checked_add(days)
                .ok_or_range_err()?;
        } else if eq(key, str_months) {
            months = value
                .cast_allow_subclass::<PyInt>()
                .ok_or_type_err("months must be an integer")?
                .to_long()?
                .checked_add(months)
                .ok_or_range_err()?;
        } else if eq(key, str_years) {
            months = value
                .cast_allow_subclass::<PyInt>()
                .ok_or_type_err("years must be an integer")?
                .to_long()?
                .checked_mul(12)
                .and_then(|m| m.checked_add(months))
                .ok_or_range_err()?;
        } else if eq(key, str_weeks) {
            days = value
                .cast_allow_subclass::<PyInt>()
                .ok_or_type_err("weeks must be an integer")?
                .to_long()?
                .checked_mul(7)
                .and_then(|d| d.checked_add(days))
                .ok_or_range_err()?;
        } else {
            return Ok(false);
        }
        Ok(true)
    })?;
    Ok((
        DeltaMonths::from_long(months).ok_or_range_err()?,
        DeltaDays::from_long(days).ok_or_range_err()?,
    ))
}

// parse the prefix of an ISO8601 duration, e.g. `P`, `-P`, `+P`,
pub(crate) fn parse_prefix(s: &mut &[u8]) -> Option<bool> {
    debug_assert!(s.len() >= 2);
    match s[0] {
        b'P' | b'p' => {
            let result = Some(false);
            *s = &s[1..];
            result
        }
        b'-' if s[1].eq_ignore_ascii_case(&b'P') => {
            let result = Some(true);
            *s = &s[2..];
            result
        }
        b'+' if s[1].eq_ignore_ascii_case(&b'P') => {
            let result = Some(false);
            *s = &s[2..];
            result
        }
        _ => None,
    }
}

fn finish_parsing_component(s: &mut &[u8], mut value: i32) -> Option<(i32, CalUnit)> {
    // We limit parsing to a number of digits to prevent overflow
    for i in 1..s.len().min(9) {
        match s[i] {
            c if c.is_ascii_digit() => value = value * 10 + i32::from(c - b'0'),
            b'D' | b'd' => {
                *s = &s[i + 1..];
                return Some((value, CalUnit::Days));
            }
            b'W' | b'w' => {
                *s = &s[i + 1..];
                return Some((value, CalUnit::Weeks));
            }
            b'M' | b'm' => {
                *s = &s[i + 1..];
                return Some((value, CalUnit::Months));
            }
            b'Y' | b'y' => {
                *s = &s[i + 1..];
                return Some((value, CalUnit::Years));
            }
            _ => {
                return None;
            }
        }
    }
    None
}

// parse a component of a ISO8601 duration, e.g. `6Y`, `56M`, `2W`, `0D`
pub(crate) fn parse_component(s: &mut &[u8]) -> Option<(i32, CalUnit)> {
    if s.len() >= 2 && s[0].is_ascii_digit() {
        finish_parsing_component(s, (s[0] - b'0').into())
    } else {
        None
    }
}
