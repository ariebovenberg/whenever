from typing import IO, Optional
from zoneinfo import ZoneInfo


class IanaTz:
    def __init__(self, f: IO[bytes], key: Optional[str] = None) -> None:
        self._zoneinfo = ZoneInfo.from_file(f, key)

    def display(self) -> str:
        return self._zoneinfo.key


class FileTz:
    def __init__(self, path: str) -> None:
        # TODO: symlink traversal?
        with open(path, "rb") as f:
            self._zoneinfo = ZoneInfo.from_file(f)
        self._path = path

    def display(self) -> str:
        return f"File({self._path})"
