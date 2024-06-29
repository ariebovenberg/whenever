from whenever import ZonedDateTime


def test_new(benchmark):
    benchmark(
        ZonedDateTime,
        2020,
        3,
        20,
        12,
        30,
        45,
        nanosecond=450,
        tz="Europe/Amsterdam",
    )


def test_change_tz(benchmark):
    dt = ZonedDateTime(
        2020, 3, 20, 12, 30, 45, nanosecond=450, tz="Europe/Amsterdam"
    )
    benchmark(dt.to_tz, "America/New_York")
