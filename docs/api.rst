.. _api:

📖 API reference
================

Unless otherwise noted, all classes are immutable.

Base classes
------------

.. autoclass:: whenever.DateTime
   :members:
   :undoc-members: year, month, day, hour, minute, second, microsecond, canonical_str
   :special-members: __str__

.. autoclass:: whenever.AwareDateTime
   :members:
   :special-members: __eq__, __lt__, __le__, __gt__, __ge__, __sub__, naive

Concrete classes
----------------

.. autoclass:: whenever.UTCDateTime
   :members: now, from_timestamp, __add__, __sub__, strptime, rfc2822, from_rfc2822, rfc3339, from_rfc3339

.. autoclass:: whenever.OffsetDateTime
   :members: now, from_timestamp, strptime, rfc2822, from_rfc2822, rfc3339, from_rfc3339

.. autoclass:: whenever.ZonedDateTime
   :members: now, from_timestamp, tz, __add__, __sub__, disambiguated

.. autoclass:: whenever.LocalDateTime
   :members: now, from_timestamp, tzname, __add__, __sub__

.. autoclass:: whenever.NaiveDateTime
   :members: __eq__, __add__, __sub__, assume_utc, assume_offset, assume_zoned, strptime, rfc2822, from_rfc2822

Helpers
-------

.. autofunction:: whenever.days
.. autofunction:: whenever.hours
.. autofunction:: whenever.minutes

Exceptions
----------

.. autoexception:: whenever.Ambiguous
.. autoexception:: whenever.DoesntExistInZone
.. autoexception:: whenever.InvalidOffsetForZone
.. autoexception:: whenever.InvalidFormat
