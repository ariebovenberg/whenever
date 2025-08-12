import os
import os.path
import platform
from typing import Literal

ZONEINFO = "zoneinfo"
SYSTEM = platform.system()
LOCALTIME = "/etc/localtime"

# Getting the system timezone key and file depends on the platform.
# On unix-like systems it's relatively straightforward.
# On other platforms, we use the tzlocal package.
# This keeps dependencies minimal for linux.
if SYSTEM in ("Linux", "Darwin"):

    def _key_or_file() -> tuple[Literal[0, 1], str]:
        if (tzif_path := os.path.realpath(LOCALTIME)) == LOCALTIME:
            # If the file is not a symlink, we can't determine the tzid
            return (1, LOCALTIME)
        try:
            tzid_start = tzif_path.rindex(ZONEINFO)
        except ValueError:
            # If the file is not in a zoneinfo directory, we can't determine the tzid
            return (1, tzif_path)
        return (0, tzif_path[tzid_start + len(ZONEINFO) + 1 :])

else:
    import tzlocal

    def _key_or_file() -> tuple[Literal[0, 1], str]:
        return (0, tzlocal.get_localzone_name())


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
    except KeyError:
        return _key_or_file()
    else:
        if tz_env.startswith(":"):
            tz_env = tz_env[1:]  # strip leading colon

        # Unless it's an absolute path, there's no way to strictly determine
        # if this is a zoneinfo key or a posix TZ string.
        if os.path.isabs(tz_env):
            return (1, tz_env)
        else:
            return (2, tz_env)
