.. meta::
   :description: Reference for miscellaneous API: patch_current_time and TimePatch, the SYSTEM_TZ sentinel, get_tzpath(), clear_tzcache(), reset_tzpath(), available_timezones(), and reset_system_tz().

Miscellaneous
=============

.. currentmodule:: whenever

This section contains API documentation for miscellaneous functions and data

.. toctree::
    :maxdepth: 1

    other-types
    exceptions


Context managers
----------------

.. autofunction:: patch_current_time

.. autoclass:: TimePatch
   :members:


System time zone
----------------

.. data:: SYSTEM_TZ

   A public sentinel that requests the system time zone. Pass it where a named
   time zone is accepted to resolve the system time zone at call time, for
   example ``ZonedDateTime.now(SYSTEM_TZ)`` or
   ``plain.assume_tz(SYSTEM_TZ)``. The returned datetime stores the resolved
   time zone, not the sentinel itself.

   See :ref:`systemtime` for caching, reset behavior, and system time zones
   without a time zone ID.


Time zone data
--------------

.. autofunction:: get_tzpath

.. data:: TZPATH

   Deprecated: use :func:`get_tzpath`. Removed in 1.0.

.. autofunction:: clear_tzcache
.. autofunction:: reset_tzpath
.. autofunction:: available_timezones
.. autofunction:: reset_system_tz
