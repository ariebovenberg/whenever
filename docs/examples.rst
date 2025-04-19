🎯 Examples
===========

This page contains small, practical examples of using ``whenever``.


Get the current time in UTC
---------------------------

.. code-block:: python

   >>> from whenever import Instant
   >>> Instant.now()
   Instant(2025-04-19 19:02:56.39569Z)

Convert a date to datetime
--------------------------

.. code-block:: python

   >>> from whenever import Date, Time
   >>> date = Date(2023, 10, 1)
   >>> date.at(Time(12, 30))
   PlainDateTime(2023-10-01 12:30:00)

Integrate with the standard library
-----------------------------------

.. code-block:: python

   >>> import datetime
   >>> py_dt = datetime.datetime.now(datetime.UTC)
   >>> from whenever import Instant
   >>> i = Instant.from_py_datetime(py_dt)
   Instant(2025-04-19 19:02:56.39569Z)
   >>> # create a ZonedDateTime for the sake of the example
   >>> zdt = i.to_tz("America/New_York")
   ZonedDateTime(2025-04-19 15:02:56.39569-04:00[America/New_York])
   >>> # convert back to the standard library
   >>> zdt.py_datetime()
   datetime.datetime(2025, 4, 19, 15, 2, 56, 395690, tzinfo=ZoneInfo('America/New_York'))


Place a datetime with a timezone
--------------------------------

.. code-block:: python

   >>> from whenever import PlainDateTime
   >>> datetime = PlainDateTime(2023, 10, 1, 12, 30)
   >>> datetime.assume_tz("America/New_York")
   ZonedDateTime(2023-10-01 12:30:00-04:00[America/New_York])

Parse an ISO8601 datetime string
--------------------------------

.. code-block:: python

   >>> from whenever import Instant
   >>> Instant.parse_common_iso("2025-04-19T19:02+04:00")
   Instant(2025-04-19 15:02:00Z)

Or, if you want to keep the offset value:

   >>> from whenever import OffsetDateTime
   >>> OffsetDateTime.parse_common_iso("2025-04-19T19:02+04:00")
   OffsetDateTime(2025-04-19 19:02:00+04:00)

Determine the start of the hour
-------------------------------

.. code-block:: python

   >>> d = ZonedDateTime.now("America/New_York")
   ZonedDateTime(2025-04-19 15:46:41-04:00[America/New_York])
   >>> d.round("hour", mode="floor")
   ZonedDateTime(2025-04-19 15:00:00-04:00[America/New_York])

The :meth:`~whenever._LocalTime.round` method can be used for so much more!
See its documentation for more details.

Get the current unix timestamp
------------------------------

.. code-block:: python

   >>> from whenever import Instant
   >>> i = Instant.now()
   >>> i.timestamp()
   1745090505

Note that this is always in whole seconds.
If you need additional precision:

   >>> i.timestamp_millis()
   1745090505629
   >>> i.timestamp_nanos()
   1745090505629346833

Move a date by six months
-------------------------

.. code-block:: python

   >>> from whenever import Date
   >>> date = Date(2023, 10, 31)
   >>> date.add(months=6)
   Date(2024-04-30)

Discard fractional seconds
--------------------------

.. code-block:: python

   >>> from whenever import Instant
   >>> i = Instant.now()
   Instant(2025-04-19 19:02:56.39569Z)
   >>> i.round()
   Instant(2025-04-19 19:02:56Z)

Use the arguments of :meth:`~whenever.Instant.round` to customize the rounding behavior.




TODO:
- parsing arbitrary strings
