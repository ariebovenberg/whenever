try:  # pragma: no cover
    from ._whenever import *
    from ._whenever import (
        _unpkl_date,
        _unpkl_ddelta,
        _unpkl_dtdelta,
        _unpkl_naive,
        _unpkl_offset,
        _unpkl_system,
        _unpkl_tdelta,
        _unpkl_time,
        _unpkl_utc,
        _unpkl_zoned,
    )

    _EXTENSION_LOADED = True

except ModuleNotFoundError as e:
    if e.name != "whenever._whenever":  # pragma: no cover
        raise e
    from ._pywhenever import *
    from ._pywhenever import (
        __all__,
        __version__,
        _unpkl_date,
        _unpkl_ddelta,
        _unpkl_dtdelta,
        _unpkl_naive,
        _unpkl_offset,
        _unpkl_system,
        _unpkl_tdelta,
        _unpkl_time,
        _unpkl_utc,
        _unpkl_zoned,
        # for docs
        _BasicConversions,
        _KnowsInstant,
        _KnowsInstantAndLocal,
        _KnowsLocal,
    )

    _EXTENSION_LOADED = False
