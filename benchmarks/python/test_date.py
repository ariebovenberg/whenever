import pickle
import sys

from whenever import Date


def test_hash(benchmark):
    d1 = Date(2020, 8, 24)
    benchmark(hash, d1)


def test_new(benchmark):
    benchmark(Date, 2020, 8, 24)


def test_canonical_format(benchmark):
    d1 = Date(2020, 8, 24)
    benchmark(d1.canonical_format)


def test_from_canonical_format(benchmark):
    benchmark(Date.from_common_iso8601, "2020-08-24")


def test_add(benchmark):
    d1 = Date(2020, 8, 24)
    benchmark(d1.add, years=-4, months=59, weeks=-7, days=3)


def test_diff(benchmark):
    d1 = Date(2020, 2, 29)
    d2 = Date(2025, 2, 28)
    benchmark(lambda: d1 - d2)


def test_attributes(benchmark):
    d1 = Date(2020, 8, 24)
    benchmark(lambda: d1.year)


def test_pickle(benchmark):
    d1 = Date(2020, 8, 24)
    benchmark(pickle.dumps, d1)


def test_parse(benchmark):
    benchmark(Date.from_canonical_format, "2020-08-24")


def test_sizeof():
    assert sys.getsizeof(Date(2020, 8, 24)) == 24
