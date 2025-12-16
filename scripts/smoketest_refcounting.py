"""
Stress tests for refcounting in the timezone cache (Rust implementation).

This test can surface refcounting issues when many timezones are loaded and unloaded.
"""

import os

from whenever import PlainDateTime, reset_system_tz

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
    f.assume_system_tz()
    f.assume_system_tz()
    f.assume_system_tz()
    f.assume_tz("Europe/Amsterdam")
    f.assume_tz("Europe/Amsterdam")
    f.assume_tz("Europe/Amsterdam")

    reset_system_tz()
    f.assume_system_tz()
    os.environ["TZ"] = "America/New_York"
    f.assume_system_tz()
    f.assume_tz("Europe/Amsterdam")

    # A posix timezone
    os.environ["TZ"] = "IST-5:30"
    f.assume_system_tz()

    # A path timezone
    path = os.environ["TZ"] = "/usr/share/zoneinfo/Asia/Tokyo"
    if os.path.exists(path):
        reset_system_tz()
    else:
        print("Path timezone not found, skipping that part of the test")


if __name__ == "__main__":
    main()
