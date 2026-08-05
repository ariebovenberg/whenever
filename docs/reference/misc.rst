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

.. autoclass:: patch_current_time
.. autoclass:: TimePatch
   :members:


System timezone
---------------

.. data:: SYSTEM_TZ

   A public sentinel that requests the system timezone. Pass it where a named
   timezone is accepted to resolve the system timezone at call time, for
   example ``ZonedDateTime.now(SYSTEM_TZ)`` or
   ``plain.assume_tz(SYSTEM_TZ)``. The returned datetime stores the resolved
   timezone, not the sentinel itself.

   See :ref:`systemtime` for caching, reset behavior, and system timezones
   without an IANA ID.


Timezone data
-------------

.. autofunction:: get_tzpath
.. autofunction:: clear_tzcache
.. autofunction:: reset_tzpath
.. autofunction:: available_timezones
.. autofunction:: reset_system_tz
