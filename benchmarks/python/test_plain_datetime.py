from whenever import PlainDateTime


def test_new(benchmark):
    benchmark(PlainDateTime, 2020, 3, 20, 12, 30, 45, nanosecond=450)


def test_parse_canonical(benchmark):
    benchmark(PlainDateTime.parse_common_iso, "2023-09-03T23:01:00")
