"""What the package exports, and how it imports."""

import ast
import inspect
import json
import subprocess
import sys
import warnings
from pathlib import Path

import pytest
from whenever import (
    _EXTENSION_LOADED,
    AnyDelta,
    ItemizedDateDelta,
    ItemizedDelta,
    TimeDelta,
    WheneverDeprecationWarning,
    get_tzpath,
)

from .common import SAMPLE_VALUES


@pytest.mark.skipif(
    sys.version_info < (3, 13),
    reason="feature not supported until Python 3.13",
)
def test_multiple_interpreters():
    import _interpreters as interpreters

    for _ in range(10):
        interp_id = interpreters.create()
        interpreters.run_string(
            interp_id,
            "from whenever import Instant; Instant.now()",
        )
        interpreters.destroy(interp_id)


def test_any_delta_runtime_value():

    assert AnyDelta == TimeDelta | ItemizedDelta | ItemizedDateDelta


def test_type_aliases():
    from whenever import AnyDelta  # noqa
    from whenever import DateDeltaUnitStr  # noqa
    from whenever import DeltaTotalUnitStr  # noqa
    from whenever import DeltaUnitStr  # noqa
    from whenever import DisambiguateStr  # noqa
    from whenever import DisambiguationStr  # noqa
    from whenever import ExactDeltaUnitStr  # noqa
    from whenever import OffsetMismatchStr  # noqa
    from whenever import RoundModeStr  # noqa
    from whenever import TimestampUnitStr  # noqa


def test_version():
    from whenever import __version__

    assert isinstance(__version__, str)


def test_stub_exports_match_runtime():
    """The stub's ``__all__`` and the runtime's are meant to be one document."""
    import whenever

    stub = Path(whenever.__file__).parent / "__init__.pyi"
    tree = ast.parse(stub.read_text())
    (value,) = [
        node.value
        for node in tree.body
        if isinstance(node, ast.Assign)
        and isinstance(node.targets[0], ast.Name)
        and node.targets[0].id == "__all__"
    ]
    assert isinstance(value, ast.Tuple)
    names = [ast.literal_eval(element) for element in value.elts]
    assert names == list(whenever.__all__)


def test_dir_includes_public_names():
    import whenever

    expected = {
        *whenever.__all__,
        "TZPATH",
        "__version__",
        "_EXTENSION_LOADED",
        "RoundModeStr",
    }
    assert expected <= set(dir(whenever))

    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; import whenever; "
            f"expected = {expected!r}; "
            "assert expected <= set(dir(whenever)); "
            "assert 'whenever._core' not in sys.modules; "
            "assert 'whenever._utils' not in sys.modules; "
            "assert 'whenever._typing' not in sys.modules",
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


def test_star_import_includes_utilities():
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "namespace = {}; exec('from whenever import *', namespace); "
            "expected = {'patch_current_time', 'reset_tzpath', "
            "'clear_tzcache', 'available_timezones'}; "
            "assert expected <= namespace.keys()",
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


def test_itemized_runtime_annotations_resolve_from_lazy_import():
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; from typing import get_type_hints; "
            "import whenever; "
            "ItemizedDelta = whenever.ItemizedDelta; "
            "ItemizedDateDelta = whenever.ItemizedDateDelta; "
            "assert 'whenever._core' not in sys.modules; "
            "assert whenever.ZonedDateTime in "
            "get_type_hints(ItemizedDelta.add)['relative_to'].__args__; "
            "get_type_hints(ItemizedDelta.date_and_time_parts); "
            "get_type_hints(ItemizedDateDelta.__add__); "
            "assert whenever.Date in "
            "get_type_hints(ItemizedDateDelta.total)['relative_to'].__args__",
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


def test_no_attr_on_module():
    with pytest.raises((AttributeError, ImportError), match="DoesntExist"):
        from whenever import DoesntExist  # type: ignore[attr-defined] # noqa


@pytest.mark.skipif(
    not _EXTENSION_LOADED, reason="only relevant when extension is active"
)
def test_extension_doesnt_import_tz_modules():
    # When the Rust extension is active, the Python time zone subsystem
    # (_tz, calendar, platform) and _shared must not be imported just by doing
    # `import whenever`. Violations here mean slow startup for all users.
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import whenever, json, sys; "
            "print(json.dumps([k for k in sys.modules "
            "if k == 'whenever._tz' or k.startswith('whenever._tz.')  "
            "or k == 'whenever._shared' "
            "or k == 'whenever._typing' "
            "or k == 'whenever._utils' "
            "or k in ('calendar', 'platform')]))",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    imported = json.loads(result.stdout)
    assert imported == [], (
        f"unexpected modules imported on 'import whenever': {imported}"
    )


@pytest.mark.skipif(
    not _EXTENSION_LOADED, reason="only relevant when extension is active"
)
def test_module_cleanup_runs():
    # Verify module_free is called on interpreter shutdown (debug builds only).
    # This ensures Python objects held by module state are properly released.
    result = subprocess.run(
        [sys.executable, "-c", "import whenever"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    if "[whenever] module_exec (debug)" not in result.stderr:
        pytest.skip("extension not built with debug_assertions")
    # In debug builds, module_free MUST be called during shutdown
    assert "[whenever] module_free called" in result.stderr


def test_import_does_not_load_typing_extensions():
    subprocess.run(
        [
            sys.executable,
            "-I",
            "-c",
            "import sys, whenever; from whenever import *; "
            "assert 'typing_extensions' not in sys.modules",
        ],
        check=True,
    )


def test_get_tzpath_is_the_public_name():
    # registered under its public name on both backends
    from whenever._tz import store

    assert get_tzpath.__name__ == "get_tzpath"
    assert inspect.getdoc(get_tzpath) == inspect.getdoc(store.get_tzpath)


def test_runtime_mixins_are_not_exported():
    """The exact and local mixins are typing scaffolding: the stub marks them
    ``@type_check_only`` and nothing may ``isinstance`` against them."""
    import whenever

    for name in ("_LocalTime", "_ExactTime", "_ExactAndLocalTime"):
        assert not hasattr(whenever, name)


def test_public_members_have_docstrings():
    # help() is identical on both backends, bound methods included
    import whenever

    def public(cls: type) -> list[str]:
        # what whenever defines, not what BaseException or Enum inherit
        return [
            n
            for n in dir(cls)
            if not n.startswith("_")
            and next(
                b for b in cls.__mro__ if n in vars(b)
            ).__module__.startswith("whenever")
        ]

    for name in whenever.__all__:
        cls = getattr(whenever, name)
        if not isinstance(cls, type):
            continue
        for attr in public(cls):
            assert getattr(cls, attr).__doc__, f"{name}.{attr}"
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", WheneverDeprecationWarning)
        for value in SAMPLE_VALUES:
            for attr in public(type(value)):
                assert getattr(value, attr).__doc__, f"{value!r}.{attr}"


def test_functions_report_the_public_module():
    import whenever

    # Both backends, so help() and pickling agree
    for name in ("get_tzpath", "reset_system_tz", "hours", "_unpkl_date"):
        assert getattr(whenever, name).__module__ == "whenever"
