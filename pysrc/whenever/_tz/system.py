import os
import os.path
import platform
from typing import Literal, Optional

ZONEINFO = "zoneinfo"
SYSTEM = platform.system()
LOCALTIME = "/etc/localtime"

# Getting the system timezone key and file depends on the platform.
# On unix-like systems it's relatively straightforward.
# On other platforms, we use the tzlocal package.
# This keeps dependencies minimal for linux.
if SYSTEM in ("Linux", "Darwin"):  # pragma: no cover

    def _key_or_file() -> tuple[Literal[0, 1], str]:
        tzif_path = os.path.realpath(LOCALTIME)
        if tzif_path == LOCALTIME:
            # If the file is not a symlink, we can't determine the tzid
            return (1, LOCALTIME)  # pragma: no cover

        if (tzid := _tzid_from_path(tzif_path)) is None:
            # If the file is not in a zoneinfo directory, we can't determine the tzid
            return (1, tzif_path)
        else:
            return (0, tzid)

else:  # pragma: no cover
    import tzlocal

    def _key_or_file() -> tuple[Literal[0, 1], str]:
        return (0, tzlocal.get_localzone_name())


def _tzid_from_path(path: str) -> Optional[str]:
    """Find the IANA timezone ID from a path to a zoneinfo file.
    Returns None if the path is not in a zoneinfo directory.
    """
    # Find the path segment containing 'zoneinfo',
    # e.g. `zoneinfo/` or `zoneinfo.default/`
    if (index := path.find("/", path.rfind("zoneinfo"))) == -1:
        return None
    return path[index + 1 :]


def get_tz() -> tuple[Literal[0, 1, 2], str]:
    """Get the system timezone. The timezone can be determined in different ways.
    The first item in the tuple is the type of the timezone:
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
            return (1, tz_env)
        # If there's a digit, it may be a posix TZ string. Theoretically
        # a zoneinfo key could contain a digit too.
        elif any(c.isdigit() for c in tz_env):
            return (2, tz_env)
        else:
            # no digit: it's certainly a zoneinfo key
            return (0, tz_env)
