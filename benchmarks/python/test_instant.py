from whenever import Instant


def test_now(benchmark):
    benchmark(Instant.now)


def test_change_tz(benchmark):
    dt = Instant.from_utc(2020, 3, 20, 12, 30, 45, nanosecond=450)
    benchmark(dt.to_tz, "America/New_York")


def test_add_time(benchmark):
    dt = Instant.from_utc(2020, 3, 20, 12, 30, 45, nanosecond=450)
    benchmark(dt.add, hours=4, minutes=30)
