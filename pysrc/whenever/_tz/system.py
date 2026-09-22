import os
import os.path
import platform
from typing import Literal

ZONEINFO = "zoneinfo"
SYSTEM = platform.system()
LOCALTIME = "/etc/localtime"
# The plain-text name of the zone /etc/localtime was copied from, on
# Debian-style systems. Some leave it stale, so it counts only when the
# database file it names is the same as /etc/localtime.
TIMEZONE_FILE = "/etc/timezone"
ZONEINFO_DIR = "/usr/share/zoneinfo"


def _localtime_key_or_file() -> tuple[Literal[0, 1], str]:
    """Resolve /etc/localtime: its zone ID when the symlink target or
    /etc/timezone reveals one, else the file itself."""
    if not os.path.exists(LOCALTIME):
        # No file is UTC, as the C library reads it (like an empty TZ)
        return (0, "")
    tzif_path = os.path.realpath(LOCALTIME)
    tzid = _tzid_from_path(tzif_path) or _tzid_from_timezone_file(tzif_path)
    return (0, tzid) if tzid else (1, tzif_path)


def _tzlocal_key_or_file() -> tuple[Literal[0, 1], str]:
    import tzlocal  # a dependency only on the platforms that use it

    # tzlocal caches the name for the life of the process; reloading is
    # what makes reset_system_tz() see a changed configuration.
    try:
        tzlocal.reload_localzone()
        tzid = tzlocal.get_localzone_name()
    except LookupError as e:  # includes zoneinfo.ZoneInfoNotFoundError
        from whenever import TimeZoneNotFoundError  # circular at import

        raise TimeZoneNotFoundError(
            f"cannot determine the system time zone: {e.args[0]}"
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


def _tzid_from_path(path: str) -> str | None:
    """Find the time zone ID from a path to a zoneinfo file.
    Returns None if the path is not in a zoneinfo directory.
    """
    # Find the path segment containing 'zoneinfo',
    # e.g. `zoneinfo/` or `zoneinfo.default/`
    if (index := path.find("/", path.rfind("zoneinfo"))) == -1:
        return None
    return path[index + 1 :]


def _tzid_from_timezone_file(tzif_path: str) -> str | None:
    """The zone ID named by /etc/timezone, if the database file it names
    has the same contents as the file at ``tzif_path``."""
    try:
        with open(TIMEZONE_FILE, encoding="ascii") as f:
            tzid = f.read().strip()
        with open(os.path.join(ZONEINFO_DIR, tzid), "rb") as f:
            named = f.read()
        with open(tzif_path, "rb") as f:
            return tzid if f.read() == named else None
    except (OSError, UnicodeDecodeError):
        # missing, unreadable, binary, or naming no database file
        return None


def get_tz() -> tuple[Literal[0, 1, 2], str]:
    """Get the system time zone. The time zone can be determined in different ways.
    The first item in the tuple is the type of the time zone:
        - 0: zoneinfo key
        - 1: file path to a zoneinfo file (key unknown)
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
            # A path into a zoneinfo directory names the zone as well
            if os.path.exists(tz_env) and (
                tzid := _tzid_from_path(os.path.realpath(tz_env))
            ):
                return (0, tzid)
            return (1, tz_env)
        # If there's a digit, it may be a posix TZ string. Theoretically
        # a zoneinfo key could contain a digit too.
        elif any(c.isdigit() for c in tz_env):
            return (2, tz_env)
        else:
            # no digit: it's certainly a zoneinfo key
            return (0, tz_env)
