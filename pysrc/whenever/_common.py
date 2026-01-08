from datetime import (
    datetime as _datetime,
    timedelta as _timedelta,
    timezone as _timezone,
)
from functools import lru_cache

UTC = _timezone.utc
DUMMY_LEAP_YEAR = 4
Nanos = int  # 0-999_999_999


# We cache fixed-offset tzinfo objects to avoid creating multiple identical ones.
# It's very common to only have whole-hour offsets, so this helps a lot.
@lru_cache
def mk_fixed_tzinfo(secs: int, /) -> _timezone:
    return _timezone(_timedelta(seconds=secs))


def check_utc_bounds(dt: _datetime) -> _datetime:
    try:
        dt.astimezone(UTC)
    except (OverflowError, ValueError):
        raise ValueError("Instant out of range")
    return dt
