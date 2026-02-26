Miscellaneous
=============

.. currentmodule:: whenever

This section contains API documentation for miscellaneous functions and data

.. toctree::
    :maxdepth: 1

    other-types
    exceptions
    deprecated


Context managers
----------------

.. autoclass:: patch_current_time
.. autoclass:: ignore_timezone_unaware_arithmetic_warning
.. autoclass:: ignore_days_not_always_24h_warning
.. autoclass:: ignore_potentially_stale_offset_warning


Timezone data
-------------

.. data:: TZPATH
   :type: tuple[str, ...]

   The paths in which ``whenever`` will search for timezone data.
   By default, this is determined the same way as :data:`zoneinfo.TZPATH`,
   although you can override it using :func:`reset_tzpath` for ``whenever`` specifically.

.. autofunction:: clear_tzcache
.. autofunction:: reset_tzpath
.. autofunction:: available_timezones
.. autofunction:: reset_system_tz
