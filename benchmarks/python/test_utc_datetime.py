from whenever import UTCDateTime


def test_now(benchmark):
    benchmark(UTCDateTime.now)


def test_change_tz(benchmark):
    dt = UTCDateTime(2020, 3, 20, 12, 30, 45, 450)
    benchmark(dt.to_tz, "America/New_York")


def test_add_date(benchmark):
    dt = UTCDateTime(2020, 3, 20, 12, 30, 45, 450)
    benchmark(dt.add, years=-4, months=59, weeks=-7, days=3)

def test_add_time(benchmark):
    dt = UTCDateTime(2020, 3, 20, 12, 30, 45, 450)
    benchmark(dt.add, hours=4, minutes=30)
