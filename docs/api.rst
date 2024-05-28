.. _api:

📖 API reference
================

All classes are immutable.

Datetimes
---------

Base classes
~~~~~~~~~~~~

The following base classes encapsulate common behavior.
They are not meant to be used directly.

.. autoclass:: whenever._DateTime
   :members:
   :undoc-members: year, month, day, hour, minute, second, microsecond, canonical_format
   :special-members: __str__

.. autoclass:: whenever._AwareDateTime
   :members:
   :special-members: __eq__, __lt__, __le__, __gt__, __ge__, __sub__, naive

Concrete classes
~~~~~~~~~~~~~~~~

.. autoclass:: whenever.UTCDateTime
   :members: now, from_timestamp, add, __add__, subtract, __sub__, strptime, rfc2822, from_rfc2822, rfc3339, from_rfc3339, common_iso8601, from_common_iso8601

.. autoclass:: whenever.OffsetDateTime
   :members: now, from_timestamp, strptime, rfc2822, from_rfc2822, rfc3339, from_rfc3339, common_iso8601, from_common_iso8601

.. autoclass:: whenever.ZonedDateTime
   :members: now, from_timestamp, tz, __add__, __sub__, is_ambiguous

.. autoclass:: whenever.LocalSystemDateTime
   :members: now, from_timestamp, tzname, __add__, __sub__

.. autoclass:: whenever.NaiveDateTime
   :members: __eq__, __add__, __sub__, assume_utc, assume_fixed_offset, assume_zoned, assume_in_local_system, strptime, common_iso8601, from_common_iso8601


Deltas
------

.. autofunction:: whenever.years
.. autofunction:: whenever.months
.. autofunction:: whenever.weeks
.. autofunction:: whenever.days

.. autofunction:: whenever.hours
.. autofunction:: whenever.minutes
.. autofunction:: whenever.seconds
.. autofunction:: whenever.microseconds

.. autoclass:: whenever.TimeDelta
   :members:
   :undoc-members: hours, minutes, seconds, microseconds
   :special-members: __eq__, __neg__, __add__, __sub__, __mul__, __truediv__, __bool__, __abs__, __gt__

.. autoclass:: whenever.DateDelta
   :members:
   :undoc-members: years, months, days
   :special-members: __eq__, __neg__, __abs__, __add__, __sub__, __mul__, __bool__

.. autoclass:: whenever.DateTimeDelta
   :members:
   :undoc-members: date_part, time_part
   :special-members: __eq__, __neg__, __abs__, __add__, __sub__, __bool__, __mul__

.. _date-and-time-api:

Date and time components
------------------------

.. autoclass:: whenever.Date
   :members:
   :special-members: __eq__, __lt__, __le__, __gt__, __ge__, __sub__, __add__

.. autoclass:: whenever.Time
   :members:
   :special-members: __eq__, __lt__, __le__, __gt__, __ge__

Exceptions
----------

.. autoexception:: whenever.AmbiguousTime
.. autoexception:: whenever.SkippedTime
.. autoexception:: whenever.InvalidOffsetForZone
