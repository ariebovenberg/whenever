import os
import os.path
import platform
from typing import Literal

ZONEINFO = "zoneinfo"
SYSTEM = platform.system()
LOCALTIME = "/etc/localtime"
# The plain-text name of the zone /etc/localtime was copied from, on
# Debian-style systems.
TIMEZONE_FILE = "/etc/timezone"

# The result of get_tz(): the kind of source, and its value. A file comes
# with the zone ID its path or /etc/timezone suggests, or "". The store
# keeps that ID only when the database has the same rules for it, since a
# stale /etc/timezone or a custom `zoneinfo` directory can name a zone
# whose rules differ from the file's.
SystemTz = (
    tuple[Literal[0], str]  # a zone ID
    | tuple[Literal[1], str, str]  # a file path, and a suggested zone ID
    | tuple[Literal[2], str]  # a zone ID or a POSIX TZ string
)


def _localtime_key_or_file() -> SystemTz:
    """Resolve /etc/localtime: the file, with the zone ID its symlink
    target or /etc/timezone suggests."""
    if not os.path.exists(LOCALTIME):
        # No file is UTC, as the C library reads it (like an empty TZ)
        return (0, "")
    tzif_path = os.path.realpath(LOCALTIME)
    return (
        1,
        tzif_path,
        _tzid_from_path(tzif_path) or _tzid_from_timezone_file(),
    )


def _tzlocal_key_or_file() -> SystemTz:
    import tzlocal  # a dependency only on the platforms that use it

    # tzlocal caches the name for the life of the process; reloading is
    # what makes reset_system_tz() see a changed configuration.
    try:
        tzlocal.reload_localzone()
        tzid = tzlocal.get_localzone_name()
    except LookupError as e:  # includes zoneinfo.ZoneInfoNotFoundError
        from whenever import TimeZoneNotFoundError  # circular at import

        reason = f": {e.args[0]}" if e.args else ""
        raise TimeZoneNotFoundError(
            f"cannot determine the system time zone{reason}"
        ) from None
    # tzlocal's unix backend finds no name on a system without config files
    return (0, tzid) if tzid else _localtime_key_or_file()


# Unix-like systems are resolved here, to keep dependencies minimal where
# it matters (servers). Other platforms use the tzlocal package.
_key_or_file = (
    _localtime_key_or_file
    if SYSTEM in ("Linux", "Darwin")
    else _tzlocal_key_or_file
)


def _tzid_from_path(path: str) -> str:
    """The zone ID a path into a zoneinfo directory suggests, or "" if the
    path is not in one."""
    # Find the path segment containing 'zoneinfo',
    # e.g. `zoneinfo/` or `zoneinfo.default/`
    if (index := path.find("/", path.rfind("zoneinfo"))) == -1:
        return ""
    return path[index + 1 :]


def _tzid_from_timezone_file() -> str:
    """The zone ID /etc/timezone names, or "" if it names none."""
    try:
        with open(TIMEZONE_FILE, encoding="ascii") as f:
            return f.read().strip()
    except (OSError, UnicodeDecodeError):
        # missing, unreadable, or binary
        return ""


def get_tz() -> SystemTz:
    """Get the system time zone. The first item in the tuple is the type of
    the time zone:
        - 0: zoneinfo key
        - 1: file path to a zoneinfo file, and the key it suggests or ""
        - 2: zoneinfo key or posix TZ string (unknown which)

    (This somewhat awkward API is used so this function can be used easily
     from Rust code)

    """
    try:
        tz_env = os.environ["TZ"]
    except KeyError:  # pragma: no cover
        return _key_or_file()
    else:
        if tz_env.startswith(":"):
            tz_env = tz_env[1:]  # strip leading colon

        # Unless it's an absolute path, there's no way to strictly determine
        # if this is a zoneinfo key or a posix TZ string.
        if os.path.isabs(tz_env):
            return (1, tz_env, _tzid_from_path(os.path.realpath(tz_env)))
        # If there's a digit, it may be a posix TZ string. Theoretically
        # a zoneinfo key could contain a digit too.
        elif any(c.isdigit() for c in tz_env):
            return (2, tz_env)
        else:
            # no digit: it's certainly a zoneinfo key
            return (0, tz_env)
