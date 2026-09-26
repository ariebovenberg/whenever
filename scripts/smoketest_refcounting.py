"""
Stress tests for refcounting in the time zone cache (Rust implementation).

This test can surface refcounting issues when many time zones are loaded and unloaded.
"""

import os

from whenever import (
    SYSTEM_TZ,
    PlainDateTime,
    hours,
    minutes,
    reset_system_tz,
)

f = PlainDateTime(2023, 10, 1, 12, 0, 0)


def main():
    f.assume_tz("Iceland")
    f.assume_tz("Iceland")
    f.assume_tz("Iceland")
    f.assume_tz("Europe/London")
    f.assume_tz("Europe/London")
    d = f.assume_tz("Europe/London")  # noqa
    f.assume_tz("Europe/London")
    f.assume_tz("Asia/Tokyo")
    f.assume_tz("Asia/Tokyo")
    f.assume_tz("America/New_York")
    f.assume_tz("America/Los_Angeles")
    f.assume_tz("America/Chicago")
    f.assume_tz("America/Denver")
    f.assume_tz("America/Argentina/Buenos_Aires")
    f.assume_tz("America/Sao_Paulo")
    f.assume_tz("Asia/Kolkata")
    f.assume_tz("Asia/Shanghai")
    f.assume_tz("Australia/Sydney")
    f.assume_tz(SYSTEM_TZ)
    f.assume_tz(SYSTEM_TZ)
    f.assume_tz(SYSTEM_TZ)
    f.assume_tz("Europe/Amsterdam")
    f.assume_tz("Europe/Amsterdam")
    f.assume_tz("Europe/Amsterdam")

    reset_system_tz()
    f.assume_tz(SYSTEM_TZ)
    os.environ["TZ"] = "America/New_York"
    reset_system_tz()
    assert f.assume_tz(SYSTEM_TZ).offset == hours(-4)
    f.assume_tz("Europe/Amsterdam")

    # A posix time zone
    os.environ["TZ"] = "IST-5:30"
    reset_system_tz()
    assert f.assume_tz(SYSTEM_TZ).offset == hours(5) + minutes(30)

    # A path time zone
    path = os.environ["TZ"] = "/usr/share/zoneinfo/Asia/Tokyo"
    if os.path.exists(path):
        reset_system_tz()
        assert f.assume_tz(SYSTEM_TZ).offset == hours(9)
    else:
        print("Path time zone not found, skipping that part of the test")


if __name__ == "__main__":
    main()
