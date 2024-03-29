import sys

from whenever.whenever import AmbiguousTime, Interval, TimeDelta, sum_as_string


def test_module_method():
    assert sum_as_string(3, 4) == "7"


def test_magic_methods():
    assert TimeDelta() == TimeDelta()


def test_instance_methods():
    assert TimeDelta().in_hours() == 0


def test_exception():
    try:
        raise AmbiguousTime()
    except AmbiguousTime:
        pass


def test_generic():
    alias = Interval[int]
    if sys.version_info >= (3, 9):
        from types import GenericAlias

        assert isinstance(alias, GenericAlias)
        assert alias.__args__ == (int,)
    else:
        assert alias is Interval


def test_raise_exception():
    pass  # TODO


def test_property():
    pass  # TODO
