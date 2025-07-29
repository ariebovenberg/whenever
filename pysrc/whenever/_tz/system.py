import os.path
import platform
from typing import Optional

ZONEINFO = "zoneinfo"
SYSTEM = platform.system()
LOCALTIME = "/etc/localtime"

if SYSTEM in ("Linux", "Darwin"):

    def tz_file_and_key() -> tuple[Optional[str], Optional[str]]:
        if (
            tzif_path := os.path.realpath(LOCALTIME, strict=True)
        ) == LOCALTIME:
            # If the file is not a symlink, we can't determine the tzid
            return LOCALTIME, None
        try:
            tzid_start = tzif_path.rindex(ZONEINFO)
        except ValueError:
            # If the file is not in a zoneinfo directory, we can't determine the tzid
            return tzif_path, None
        return tzif_path, tzif_path[tzid_start + len(ZONEINFO) + 1 :]

else:
    import tzlocal

    def tz_file_and_key() -> tuple[Optional[str], Optional[str]]:
        return None, tzlocal.get_localzone_name()
