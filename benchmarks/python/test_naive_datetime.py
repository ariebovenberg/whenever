from whenever import NaiveDateTime


def test_new(benchmark):
    benchmark(NaiveDateTime, 2020, 3, 20, 12, 30, 45, 450)


def test_parse_canonical(benchmark):
    benchmark(NaiveDateTime.from_canonical_format, "2023-09-03 23:01:00")
