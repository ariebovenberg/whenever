import pickle
import sys

import pytest

from whenever import _EXTENSION_LOADED, Date


def test_hash(benchmark):
    d1 = Date(2020, 8, 24)
    benchmark(hash, d1)


def test_new(benchmark):
    benchmark(Date, 2020, 8, 24)


def test_format_common_iso(benchmark):
    d1 = Date(2020, 8, 24)
    benchmark(d1.format_common_iso)


def test_parse_common_iso(benchmark):
    benchmark(Date.parse_common_iso, "2020-08-24")


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


@pytest.mark.skipif(not _EXTENSION_LOADED, reason="extension not loaded")
def test_sizeof():
    assert sys.getsizeof(Date(2020, 8, 24)) == 24
