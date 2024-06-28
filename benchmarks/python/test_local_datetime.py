from whenever import LocalDateTime


def test_new(benchmark):
    benchmark(LocalDateTime, 2020, 3, 20, 12, 30, 45, nanosecond=450)


def test_parse_canonical(benchmark):
    benchmark(LocalDateTime.parse_common_iso, "2023-09-03T23:01:00")
