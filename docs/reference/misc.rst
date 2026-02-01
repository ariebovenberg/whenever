Miscellaneous
=============

This section contains API documentation for miscellaneous functions and data

.. toctree::
    :maxdepth: 1

    exceptions
    deprecated

.. autoclass:: whenever.patch_current_time

.. data:: whenever.TZPATH
   :type: tuple[str, ...]

   The paths in which ``whenever`` will search for timezone data.
   By default, this is determined the same way as :data:`zoneinfo.TZPATH`,
   although you can override it using :func:`whenever.reset_tzpath` for ``whenever`` specifically.

.. autofunction:: whenever.clear_tzcache
.. autofunction:: whenever.reset_tzpath
.. autofunction:: whenever.available_timezones
.. autofunction:: whenever.reset_system_tz
