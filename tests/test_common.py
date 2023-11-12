import pytest

from whenever import Nothing, Option, Some


class TestSome:
    def test_unwrap(self):
        assert Some(42).unwrap() == 42
        assert Some(42).value == 42

    def test_equality(self):
        x: Option[int] = Some(42)
        same: Option[int] = Some(42)
        different: Option[int] = Some(43)
        nothing: Option[int] = Nothing()

        assert x == same
        assert not x == different
        assert not x == nothing
        assert not x == 42  # type: ignore[comparison-overlap]

        assert x != different
        assert not x != same
        assert x != 42  # type: ignore[comparison-overlap]
        assert x != nothing

        assert hash(x) == hash(same)
        assert hash(x) != hash(different)

    def test_match(self):
        s = Some(42)
        match s:
            case Some(v):
                assert v == 42
            case Nothing():
                assert False
            case _:
                assert False

    def test_generic(self):
        s = Some[int](42)
        assert s == Some(42)

    def test_inheritance(self):
        s = Some(42)
        assert isinstance(s, Some)
        assert isinstance(s, Option)
        assert not isinstance(s, Nothing)

    def test_bool(self):
        assert bool(Some(42))
        assert bool(Some(0))


class TestNothing:
    def test_unwrap(self):
        with pytest.raises(ValueError):
            Nothing().unwrap()

    def test_equality(self):
        x: Option[int] = Nothing()
        same: Option[int] = Nothing()

        assert x == same
        assert not x == 42  # type: ignore[comparison-overlap]

        assert x != 42  # type: ignore[comparison-overlap]
        assert not x != same

        assert hash(x) == hash(same)
        assert hash(x) != hash(42)

    def test_inheritance(self):
        n = Nothing[int]()
        assert isinstance(n, Nothing)
        assert isinstance(n, Option)
        assert not isinstance(n, Some)

    def test_repr(self):
        assert repr(Nothing()) == "whenever.Nothing()"

    def test_bool(self):
        assert not bool(Nothing())

    def test_match(self):
        n = Nothing[str]()
        match n:
            case Some(_):
                assert False
            case Nothing():
                assert True
            case _:
                assert False

    def test_generic(self):
        n = Nothing[int]()
        assert n == Nothing()

    def test_no_other_attributes(self):
        n = Nothing[int]()
        with pytest.raises(AttributeError):
            n.foo = 4  # type: ignore[attr-defined]
