"""This script ensures the Rust extension docstrings are identical to the
Python ones.

It does so by parsing the Python docstrings and generating a Rust file with the
same docstrings. This file is then included in the Rust extension.
"""

import enum
import inspect
import sys
from itertools import chain

from whenever import _pywhenever as W

assert sys.version_info >= (
    3,
    13,
), "This script requires Python 3.13 or later due to how docstrings are rendered."

classes = {
    cls
    for name, cls in W.__dict__.items()
    if (
        not name.startswith("_")
        and inspect.isclass(cls)
        and cls.__module__ == "whenever"
        and not issubclass(cls, enum.Enum)
    )
}
functions = {
    func
    for name, func in inspect.getmembers(W)
    if (
        not name.startswith("_")
        and inspect.isfunction(func)
        and func.__module__ == "whenever"
    )
}


methods = {
    getattr(cls, name)
    for cls in chain(
        classes,
        (
            # some methods are documented in their ABCs
            W._BasicConversions,
            W._LocalTime,
            W._ExactTime,
            W._ExactAndLocalTime,
        ),
    )
    for name, m in cls.__dict__.items()
    if (
        not name.startswith("_")
        and (
            inspect.isfunction(m)
            or
            # this catches classmethods
            inspect.ismethod(getattr(cls, name))
        )
    )
}

MAGIC_STRINGS = {
    (name, value)
    for name, value in W.__dict__.items()
    if isinstance(value, str) and name.isupper() and not name.startswith("_")
}

CSTR_TEMPLATE = 'pub(crate) const {varname}: &CStr = c"\\\n{doc}";'
STR_TEMPLATE = 'pub(crate) const {varname}: &str = "{value}";'
HEADER = """\
// Do not manually edit this file.
// It has been autogenerated by generate_docstrings.py
use std::ffi::CStr;
"""

PYDANTIC_DOCSTRING = 'pub(crate) const PYDANTIC_SCHEMA: &CStr = c"__get_pydantic_core_schema__(source_type, handler)\\n--\\n\\n";'

MANUALLY_DEFINED_SIGS: dict[object, str] = {
    W.ZonedDateTime.add: """\
($self, delta=None, /, *, years=0, months=0, weeks=0, days=0, hours=0, \
minutes=0, seconds=0, milliseconds=0, microseconds=0, nanoseconds=0, \
disambiguate=None)""",
    W.ZonedDateTime.replace: """\
($self, /, *, year=None, month=None, weeks=0, day=None, hour=None, \
minute=None, second=None, nanosecond=None, tz=None, disambiguate)""",
    W.OffsetDateTime.add: """\
($self, delta=None, /, *, years=0, months=0, weeks=0, days=0, \
hours=0, minutes=0, seconds=0, milliseconds=0, microseconds=0, nanoseconds=0, \
ignore_dst=False)""",
    W.OffsetDateTime.replace: """\
($self, /, *, year=None, month=None, weeks=0, day=None, hour=None, \
minute=None, second=None, nanosecond=None, offset=None, ignore_dst=False)""",
    W.PlainDateTime.add: """\
($self, delta=None, /, *, years=0, months=0, weeks=0, days=0, \
hours=0, minutes=0, seconds=0, milliseconds=0, microseconds=0, nanoseconds=0, \
ignore_dst=False)""",
    W.PlainDateTime.replace: """\
($self, /, *, year=None, month=None, day=None, hour=None, \
minute=None, second=None, nanosecond=None)""",
    W.Date.replace: "($self, /, *, year=None, month=None, day=None)",
    W.MonthDay.replace: "($self, /, *, month=None, day=None)",
    W.Time.replace: "($self, /, *, hour=None, minute=None, second=None, nanosecond=None)",
    W.YearMonth.replace: "($self, /, *, year=None, month=None)",
    W.Instant.add: """\
($self, delta=None, /, *, hours=0, minutes=0, seconds=0, \
milliseconds=0, microseconds=0, nanoseconds=0)""",
    W.Date.add: "($self, delta=None, /, *, years=0, months=0, weeks=0, days=0)",
}
MANUALLY_DEFINED_SIGS.update(
    {
        W.ZonedDateTime.subtract: MANUALLY_DEFINED_SIGS[W.ZonedDateTime.add],
        W.SystemDateTime.add: MANUALLY_DEFINED_SIGS[W.ZonedDateTime.add],
        W.SystemDateTime.subtract: MANUALLY_DEFINED_SIGS[W.ZonedDateTime.add],
        W.SystemDateTime.replace: MANUALLY_DEFINED_SIGS[
            W.ZonedDateTime.replace
        ],
        W.OffsetDateTime.subtract: MANUALLY_DEFINED_SIGS[W.OffsetDateTime.add],
        W.PlainDateTime.subtract: MANUALLY_DEFINED_SIGS[W.PlainDateTime.add],
        W.Instant.subtract: MANUALLY_DEFINED_SIGS[W.Instant.add],
        W.Date.subtract: MANUALLY_DEFINED_SIGS[W.Date.add],
    }
)
SKIP = {
    W._BasicConversions.format_common_iso,
    W._BasicConversions.from_py_datetime,
    W._BasicConversions.parse_common_iso,
    W._ExactTime.from_timestamp,
    W._ExactTime.from_timestamp_millis,
    W._ExactTime.from_timestamp_nanos,
    W._ExactTime.now,
    W._LocalTime.add,
    W._LocalTime.subtract,
    W._LocalTime.replace,
    W._LocalTime.replace_date,
    W._LocalTime.replace_time,
    W._LocalTime.round,
}


def method_doc(method):
    method.__annotations__.clear()
    try:
        sig = MANUALLY_DEFINED_SIGS[method]
    except KeyError:
        sig = (
            str(inspect.signature(method))
            # We use unicode escape of '(' to avoid messing up LSP in editors
            .replace("\u0028self", "\u0028$self").replace(
                "\u0028cls", "\u0028$type"
            )
        )
    doc = method.__doc__.replace('"', '\\"')
    sig_prefix = f"{method.__name__}{sig}\n--\n\n"
    return sig_prefix * _needs_text_signature(method) + doc


# In some basic cases, such as 0 or 1-argument functions, Python
# will automatically generate an adequate signature.
def _needs_text_signature(method):
    sig = inspect.signature(method)
    params = list(sig.parameters.values())
    if len(params) == 0:
        return False
    if params[0].name in {"self", "cls"}:
        params.pop(0)
    if len(params) > 1:
        return True
    elif len(params) == 0:
        return False
    else:
        return (
            params[0].kind != inspect.Parameter.POSITIONAL_ONLY
            or params[0].default is not inspect.Parameter.empty
        )


def print_everything():
    print(HEADER)
    print(PYDANTIC_DOCSTRING)
    for cls in sorted(classes, key=lambda x: x.__name__):
        assert cls.__doc__
        print(
            CSTR_TEMPLATE.format(
                varname=cls.__name__.upper(),
                doc=cls.__doc__.replace('"', '\\"'),
            )
        )

    for func in sorted(functions, key=lambda x: x.__name__):
        assert func.__doc__
        print(
            CSTR_TEMPLATE.format(
                varname=func.__name__.upper(),
                doc=func.__doc__.replace('"', '\\"'),
            )
        )

    for method in sorted(methods, key=lambda x: x.__qualname__):
        if method.__doc__ is None or method in SKIP:
            continue

        qualname = method.__qualname__
        if qualname.startswith("_"):
            qualname = qualname[1:]
        print(
            CSTR_TEMPLATE.format(
                varname=qualname.replace(".", "_").upper(),
                doc=method_doc(method),
            )
        )

    for name, value in sorted(MAGIC_STRINGS):
        print(STR_TEMPLATE.format(varname=name, value=value))


if __name__ == "__main__":
    print_everything()
