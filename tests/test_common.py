from datetime import timedelta

from whenever import days, hours, minutes


def test_timedelta_aliases():
    assert days(1) == timedelta(days=1)
    assert hours(1) == timedelta(hours=1)
    assert minutes(1) == timedelta(minutes=1)
