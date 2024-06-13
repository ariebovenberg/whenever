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
   :undoc-members: year, month, day, hour, minute, second, nanosecond
   :special-members: __str__
   :member-order: bysource

.. autoclass:: whenever._AwareDateTime
   :members:
   :special-members: __eq__, __lt__, __le__, __gt__, __ge__, __sub__
   :member-order: bysource

Concrete classes
~~~~~~~~~~~~~~~~

.. autoclass:: whenever.UTCDateTime
   :members:
     now,
     from_timestamp,
     from_timestamp_millis,
     from_timestamp_nanos,
     format_rfc3339,
     format_rfc2822,
     parse_rfc3339,
     parse_rfc2822,
     strptime,
     replace,
     replace_date,
     replace_time,
     add,
     subtract
   :special-members: __add__, __sub__
   :member-order: bysource

.. autoclass:: whenever.OffsetDateTime
   :members:
     now,
     from_timestamp,
     from_timestamp_millis,
     from_timestamp_nanos,
     format_rfc3339,
     format_rfc2822,
     parse_rfc3339,
     parse_rfc2822,
     strptime,
     replace,
     replace_date,
     replace_time,
   :member-order: bysource

.. autoclass:: whenever.ZonedDateTime
   :members:
     tz,
     is_ambiguous,
     now,
     from_timestamp,
     from_timestamp_millis,
     from_timestamp_nanos,
     replace,
     replace_date,
     replace_time,
     add,
     subtract
   :special-members: __add__, __sub__
   :member-order: bysource

.. autoclass:: whenever.LocalSystemDateTime
   :members:
     now,
     from_timestamp,
     from_timestamp_millis,
     from_timestamp_nanos,
     replace,
     replace_date,
     replace_time,
     add,
     subtract
   :special-members: __add__, __sub__
   :member-order: bysource

.. autoclass:: whenever.NaiveDateTime
   :members:
     assume_utc,
     assume_fixed_offset,
     assume_tz,
     assume_local_system,
     strptime,
     replace,
     replace_date,
     replace_time,
   :special-members: __add__, __sub__, __eq__
   :member-order: bysource


Deltas
------

.. autofunction:: whenever.years
.. autofunction:: whenever.months
.. autofunction:: whenever.weeks
.. autofunction:: whenever.days

.. autofunction:: whenever.hours
.. autofunction:: whenever.minutes
.. autofunction:: whenever.seconds
.. autofunction:: whenever.milliseconds
.. autofunction:: whenever.microseconds
.. autofunction:: whenever.nanoseconds

.. autoclass:: whenever.TimeDelta
   :members:
   :undoc-members: hours, minutes, seconds, microseconds
   :special-members: __eq__, __neg__, __add__, __sub__, __mul__, __truediv__, __bool__, __abs__, __gt__
   :member-order: bysource

.. autoclass:: whenever.DateDelta
   :members:
   :undoc-members: years, months, days
   :special-members: __eq__, __neg__, __abs__, __add__, __sub__, __mul__, __bool__
   :member-order: bysource

.. autoclass:: whenever.DateTimeDelta
   :members:
   :undoc-members: date_part, time_part
   :special-members: __eq__, __neg__, __abs__, __add__, __sub__, __bool__, __mul__
   :member-order: bysource

.. _date-and-time-api:

Date and time components
------------------------

.. autoclass:: whenever.Date
   :members:
   :special-members: __eq__, __lt__, __le__, __gt__, __ge__, __sub__, __add__

.. autoclass:: whenever.Time
   :members:
   :special-members: __eq__, __lt__, __le__, __gt__, __ge__

Miscellaneous
-------------

.. autoenum:: whenever.Weekday
   :members:
   :member-order: bysource

.. autoexception:: whenever.AmbiguousTime
.. autoexception:: whenever.SkippedTime
.. autoexception:: whenever.InvalidOffset
