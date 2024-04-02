try:
    from ._whenever import *
    from ._whenever import (
        _unpkl_date,
        _unpkl_ddelta,
        _unpkl_naive,
        _unpkl_tdelta,
        _unpkl_time,
        _unpkl_zoned,
    )

except ModuleNotFoundError as e:
    if e.name != "whenever._whenever":
        raise e
    from ._pywhenever import *
    from ._pywhenever import (
        __all__,
        __version__,
        _AwareDateTime,
        _DateTime,
        _unpkl_date,
        _unpkl_ddelta,
        _unpkl_dtdelta,
        _unpkl_local,
        _unpkl_naive,
        _unpkl_offset,
        _unpkl_tdelta,
        _unpkl_time,
        _unpkl_utc,
        _unpkl_zoned,
    )
