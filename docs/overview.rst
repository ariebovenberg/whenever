.. _overview:

⭐️ Main features
=================

This page gives an overview of **whenever**'s main features for working 
with date and time.
For more details, see the :ref:`API reference <api>`.

Different types
---------------

.. epigraph::

   In API design, if you've got two things that are even subtly different,
   it's worth having them as separate types—because you're representing the
   meaning of your data more accurately.

   -- Jon Skeet

While the standard library has a single :class:`~datetime.datetime` type
for all use cases,
**whenever** provides distinct types similar to other modern datetime libraries [2]_:

- :class:`~whenever.Instant`—the simplest way to represent a point on the timeline
- :class:`~whenever.LocalDateTime`—"wall clock time", how people typically think of time locally
- :class:`~whenever.ZonedDateTime`—a point on the timeline with a local time and timezone

Less commonly used types are:

- :class:`~whenever.OffsetDateTime`—a point on the timeline with a fixed offset from UTC
- :class:`~whenever.SystemDateTime`—a point on the timeline in the system timezone

Each is designed to communicate intent, prevent mistakes, and optimize performance.
You won't need all of them at the same time.
Read on to find out which one is right for your use case.

:class:`~whenever.Instant`
~~~~~~~~~~~~~~~~~~~~~~~~~~

This is the simplest way to represent a moment on the timeline,
independent of human complexities like timezones or calendars.
An ``Instant`` maps 1:1 to UTC or a UNIX timestamp.
It's great for storing when something happened (or will happen)
regardless of location.

>>> livestream_starts = Instant.from_utc(2022, 10, 24, hour=17)
Instant(2022-10-24 17:00:00Z)
>>> Instant.now() > livestream_starts
True
>>> livestream_starts.add(hours=3).timestamp()
1666641600

The value of this type is in its simplicity. It's straightforward to compare,
add, and subtract. It's always clear what moment in time
you're referring to—without having to worry about timezones,
daylight saving time, or the calendar.

.. seealso::

   :ref:`Why does Instant exist? <faq-why-instant>`

:class:`~whenever.LocalDateTime`
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Local datetimes represent date and time as humans typically interact with them,
for example: *January 23rd, 2023, 3:30pm*.
While this information makes sense to people within a certain context,
on its own it doesn't refer to a moment on the timeline.
This is because this date and time occur at different moments
depending on whether you're in Australia or Mexico, for example.

Another limitation is that local datetimes can't account for daylight saving time.
Therefore, it's not possible to add or subtract an exact time from a local datetime.
This is because—strictly speaking—you don't know what time it will be in 3 hours:
perhaps the clock will be moved forward or back due to daylight saving time.

>>> bus_departs = LocalDateTime(2020, 3, 14, hour=15)
LocalDateTime(2020-03-14 15:00:00)
# NOT possible:
>>> Instant.now() > bus_departs                 # comparison with exact moments
>>> bus_departs.add(hours=3)                    # adding an exact time
# IS possible:
>>> LocalDateTime(2020, 3, 15) > bus_departs    # comparison with other local datetimes
>>> bus_departs.add(hours=3, ignore_dst=True)   # explicitly ignore DST
>>> bus_departs.add(days=2)                     # calendar operations are OK

So how do you account for daylight saving time? Or place a local datetime on the timeline?
That's what the next type is for.

:class:`~whenever.ZonedDateTime`
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

This is a combination of an instant *and* a local time at a specific location.
It accounts for daylight saving time *and* supports calendar operations.

>>> pycon24_keynote = ZonedDateTime(2024, 5, 17, 9, 45, tz="America/New_York")
ZonedDateTime(2024-05-17 09:45:00-04:00[America/New_York])
>>> pycon24_keynote.subtract(months=3)
ZonedDateTime(2024-02-17 09:45:00-05:00[America/New_York])

A timezone determines a UTC offset and rules for daylight saving time.
As a result, any :class:`~whenever.Instant` can
be converted to a :class:`~whenever.ZonedDateTime`.
However, converting a :class:`~whenever.LocalDateTime` to a :class:`~whenever.ZonedDateTime`
is more complex, because local times can occur twice or not at all due to daylight saving time.
Read about ambiguity in more detail :ref:`here <ambiguity>`.

>>> # from Instant: always possible
>>> livestream_starts.to_tz("America/New_York")
ZonedDateTime(2022-10-24 13:00:00-04:00[America/New_York])
>>> # from LocalDateTime: maybe ambiguous
>>> bus_departs.assume_tz("America/New_York", disambiguate="earlier")
ZonedDateTime(2020-03-14 15:00:00-04:00[America/New_York])

:class:`~whenever.OffsetDateTime`
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Like :class:`~whenever.ZonedDateTime`, this type represents a moment on the timeline
with a local time. The difference is that :class:`~whenever.OffsetDateTime`
has a *fixed* offset from UTC rather than a timezone.
As a result, it doesn't know about daylight saving time or other timezone changes.

Then why use it? Firstly, most datetime formats (e.g. ISO 8601 and RFC 3339) only have fixed offsets,
making :class:`~whenever.OffsetDateTime` ideal for representing datetimes in these formats.
Second, a :class:`~whenever.OffsetDateTime` is simpler—so long as you
don't need to adjust it. This makes :class:`~whenever.OffsetDateTime`
an efficient and compatible choice for representing times in the past.

>>> flight_departure = OffsetDateTime(2023, 4, 21, hour=9, offset=-4)
>>> flight_arrival = OffsetDateTime(2023, 4, 21, hour=10, offset=-6)
>>> (flight_arrival - flight_departure).in_hours()
3
>>> # but you CAN'T do this:
>>> flight_arrival.add(hours=3)  # a DST-bug waiting to happen!
>>> # instead:
>>> flight_arrival.in_tz("America/New_York").add(hours=3)  # use the full timezone
>>> flight_arrival.add(hours=3, ignore_dst=True)  # explicitly ignore DST


.. seealso::

   - :ref:`Why doen't OffsetDateTime support arithmetic? <faq-offset-arithmetic>`

:class:`~whenever.SystemDateTime`
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

This is a datetime in the timezone of the system running the code.
Unless your code specifically runs on the user's
machine (such as a CLI), you shouldn't need to use this type.

>>> # assuming system timezone is America/New_York
>>> backup_performed = SystemDateTime(2023, 12, 28, hour=2)
SystemDateTime(2023-12-28 02:00:00-05:00)
>>> livestream_starts.to_system_tz()
SystemDateTime(2022-10-24 13:00:00-04:00)

.. seealso::

   - :ref:`Why does SystemDateTime exist? <faq-why-system-tz>`
   - :ref:`Working with the system timezone <systemtime>`

.. _summary:

Here's a summary of how you can use the types:

+-----------------------+---------+---------+-------+--------+---------+
| Feature               |             "Exact"                |         |
+                       +---------+---------+-------+--------+         +
|                       | Instant | OffsetDT|ZonedDT|SystemDT|LocalDT  |
+=======================+=========+=========+=======+========+=========+
| comparison            | .. centered:: ✅                   |  ✅     |
+-----------------------+---------+---------+-------+--------+---------+
| difference            | .. centered:: ✅                   |  ✅     |
+-----------------------+---------+---------+-------+--------+---------+
| add/subtract years,   | ❌      |  ✅     |  ✅   |  ✅    |  ✅     |
| months, days          |         |         |       |        |         |
+-----------------------+---------+---------+-------+--------+---------+
| add/subtract hours,   | ✅      | ⚠️ [3]_ |  ✅   |  ✅    |⚠️  [3]_ |
| minutes, seconds, ... |         |         |       |        |         |
+-----------------------+---------+---------+-------+--------+---------+
| no disambiguation     | ✅      |  ✅     |  ❌   |  ❌    |  ✅     |
| needed                |         |         |       |        |         |
+-----------------------+---------+---------+-------+--------+---------+
| to/from timestamp     | ✅      |  ✅     |  ✅   |  ✅    |  ❌     |
+-----------------------+---------+---------+-------+--------+---------+
| now                   | ✅      |  ✅     |  ✅   |  ✅    |  ❌     |
+-----------------------+---------+---------+-------+--------+---------+
| to/from RFC3339/2822  | ✅      |  ✅     |  ❌   |  ❌    |  ❌     |
+-----------------------+---------+---------+-------+--------+---------+

.. [3] Only possible with explicit ``ignore_dst=True``


Comparison and equality
-----------------------

All types support equality and comparison.
However, :class:`~whenever.LocalDateTime` instances are
never equal or comparable to the exact ("aware") types.

Exact types
~~~~~~~~~~~

For exact types (:class:`~whenever.Instant`, :class:`~whenever.OffsetDateTime`,
:class:`~whenever.ZonedDateTime`, and :class:`~whenever.SystemDateTime`),
comparison and equality are based on whether they represent the same moment in
time. This means that two objects with different values can be equal:

>>> # different ways of representing the same moment in time
>>> inst = Instant.from_utc(2023, 12, 28, 11, 30)
>>> as_5hr_offset = OffsetDateTime(2023, 12, 28, 16, 30, offset=5)
>>> as_8hr_offset = OffsetDateTime(2023, 12, 28, 19, 30, offset=8)
>>> in_nyc = ZonedDateTime(2023, 12, 28, 6, 30, tz="America/New_York")
>>> # all equal
>>> inst == as_5hr_offset == as_8hr_offset == in_nyc
True
>>> # comparison
>>> in_nyc > OffsetDateTime(2023, 12, 28, 11, 30, offset=5)
True

Note that if you want to compare for exact equality on the values
(i.e. exactly the same year, month, day, hour, minute, etc.), you can use
the :meth:`~whenever._KnowsInstant.exact_eq` method.

>>> d = OffsetDateTime(2023, 12, 28, 11, 30, offset=5)
>>> same = OffsetDateTime(2023, 12, 28, 11, 30, offset=5)
>>> same_moment = OffsetDateTime(2023, 12, 28, 12, 30, offset=6)
>>> d == same_moment
True
>>> d.exact_eq(same_moment)
False
>>> d.exact_eq(same)
True

Local datetimes
~~~~~~~~~~~~~~~

For :class:`~whenever.LocalDateTime`, equality is simply based on
whether the values are the same, since there is no concept of timezones or UTC offset:

>>> d = LocalDateTime(2023, 12, 28, 11, 30)
>>> same = LocalDateTime(2023, 12, 28, 11, 30)
>>> different = LocalDateTime(2023, 12, 28, 11, 31)
>>> d == same
True
>>> d == different
False

.. seealso::

   See the documentation of :meth:`__eq__ (exact) <whenever._KnowsInstant.__eq__>`
   and :meth:`LocalDateTime.__eq__ <whenever.LocalDateTime.__eq__>` for more details.


Strict equality
~~~~~~~~~~~~~~~

Local and exact types are never equal or comparable to each other.
However, to comply with the Python data model, the equality operator
won't prevent you from using ``==`` to compare them.
To prevent these mix-ups, use mypy's ``--strict-equality``
`flag <https://mypy.readthedocs.io/en/stable/command_line.html#cmdoption-mypy-strict-equality>`_.

>>> # These are never equal, but Python won't stop you from comparing them.
>>> # Mypy will catch this mix-up if you use enable --strict-equality flag.
>>> Instant.from_utc(2023, 12, 28) == LocalDateTime(2023, 12, 28)
False

.. admonition:: Why not raise a TypeError?

    It may *seem* like the equality operator should raise a :exc:`TypeError`
    in these cases, but this would result in
    `surprising behavior <https://stackoverflow.com/a/33417512>`_
    when using values as dictionary keys.

Unfortunately, mypy's ``--strict-equality`` is *very* strict,
forcing you to match exact types exactly.

.. code-block:: python

    x = Instant.from_utc(2023, 12, 28, 10)

    # mypy: ✅
    x == Instant.from_utc(2023, 12, 28, 10)

    # mypy: ❌ (too strict, this should be allowed)
    x == OffsetDateTime(2023, 12, 28, 11, offset=1)

To work around this, you can either convert explicitly:

.. code-block:: python

    x == OffsetDateTime(2023, 12, 28, 11, offset=1).instant()

Or annotate with a union:

.. code-block:: python

    x: OffsetDateTime | Instant == OffsetDateTime(2023, 12, 28, 11, offset=1)


Conversion
----------

Between exact types
~~~~~~~~~~~~~~~~~~~

You can convert between exact types with the :meth:`~whenever._KnowsInstantAndLocal.instant`,
:meth:`~whenever._KnowsInstant.to_fixed_offset`, :meth:`~whenever._KnowsInstant.to_tz`,
and :meth:`~whenever._KnowsInstant.to_system_tz` methods. These methods return a new
instance of the appropriate type, representing the same moment in time.
This means the results will always compare equal to the original datetime.

>>> d = ZonedDateTime(2023, 12, 28, 11, 30, tz="Europe/Amsterdam")
>>> d.instant()  # The underlying moment in time
Instant(2023-12-28 10:30:00Z)
>>> d.to_fixed_offset(5)  # same moment with a +5:00 offset
OffsetDateTime(2023-12-28 15:30:00+05:00)
>>> d.to_tz("America/New_York")  # same moment in New York
ZonedDateTime(2023-12-28 05:30:00-05:00[America/New_York])
>>> d.to_system_tz()  # same moment in the system timezone (e.g. Europe/Paris)
SystemDateTime(2023-12-28 11:30:00+01:00)
>>> d.to_fixed_offset(4) == d
True  # always the same moment in time

To and from local datetimes
~~~~~~~~~~~~~~~~~~~~~~~~~~~

Conversion to local date and time is easy: calling
:meth:`~whenever._KnowsInstantAndLocal.local` simply
retrieves the local date and time part of the datetime.

>>> d = ZonedDateTime(2023, 12, 28, 11, 30, tz="Europe/Amsterdam")
>>> n = d.local()
LocalDateTime(2023-12-28 11:30:00)

You can convert from local datetimes with the :meth:`~whenever.LocalDateTime.assume_utc`,
:meth:`~whenever.LocalDateTime.assume_fixed_offset`, and
:meth:`~whenever.LocalDateTime.assume_tz`, and
:meth:`~whenever.LocalDateTime.assume_system_tz` methods.

>>> n = LocalDateTime(2023, 12, 28, 11, 30)
>>> n.assume_utc()
Instant(2023-12-28 11:30:00Z)
>>> n.assume_tz("Europe/Amsterdam", disambiguate="compatible")
ZonedDateTime(2023-12-28 11:30:00+01:00[Europe/Amsterdam])

.. note::

   The seemingly inconsistent naming of the ``to_*`` and ``assume_*`` methods is intentional. The ``assume_*`` methods
   emphasize that the conversion is not self-evident, but based on assumptions
   of the developer.


.. _arithmetic:

Arithmetic
----------

Datetimes support varous arithmetic operations with addition and subtraction.

Difference between times
~~~~~~~~~~~~~~~~~~~~~~~~

You can subtract two datetime instances to get a
:class:`~whenever.TimeDelta` representing the duration between them.
Exact types can be mixed with each other,
but local datetimes cannot be mixed with exact types:

>>> # difference between moments in time
>>> Instant.from_utc(2023, 12, 28, 11, 30) - ZonedDateTime(2023, 12, 28, tz="Europe/Amsterdam")
TimeDelta(12:30:00)
>>> # difference between local datetimes
>>> LocalDateTime(2023, 12, 28, 11) - LocalDateTime(2023, 12, 27, 11)
TimeDelta(24:00:00)

.. _add-subtract-time:

Adding and subtracting time
~~~~~~~~~~~~~~~~~~~~~~~~~~~

You can add or subtract various units of time from a datetime instance.

>>> d = ZonedDateTime(2023, 12, 28, 11, 30, tz="Europe/Amsterdam")
>>> d.add(hours=5, minutes=30)
ZonedDateTime(2023-12-28 17:00:00+01:00[Europe/Amsterdam])
>>> d.subtract(days=1, disambiguate="compatible")  # 1 day earlier
ZonedDateTime(2023-12-27 11:30:00+01:00[Europe/Amsterdam])

Adding/subtracting takes into account timezone changes (e.g. daylight saving time)
according to industry standard RFC 5545 and other modern datetime libraries.
This means:

- Units are handled from largest (year) to smallest (nanosecond),
  truncating and/or wrapping at each step.
- Adding or subtracting calendar units (months, days) keeps the local
  time of day the same across DST changes.
  This is because you'd expect that rescheduling a 10am appointment "a day later"
  will still be at 10am, regardless of a DST change overnight.
  However, because the new time may be repeated or skipped,
  ``disambiguate`` is required for calendar units.
- Precise time units (hours, minutes, and seconds) account for DST changes.

.. seealso::

   Have a look at the documentation on :ref:`deltas <durations>` for more details
   on arithmetic operations, as well as more advanced features.

.. attention::

   :class:`~whenever.OffsetDateTime` instances do not support moving back and
   forwards in time, because offsets in real world timezones aren't always constant.
   That is, the offset may be different after moving backwards or forwards in time.
   If you need to shift an :class:`~whenever.OffsetDateTime` instance,
   either convert to UTC or a proper :class:`~whenever.ZonedDateTime` first.

.. _ambiguity:

Ambiguity in timezones
----------------------

.. note::

   The API for handling ambiguitiy is inspired by that of
   `Temporal <https://tc39.es/proposal-temporal/docs/ambiguity.html>`_,
   the redesigned date and time API for JavaScript.

In timezones, local clocks are often moved backwards and forwards
due to Daylight Saving Time (DST) or political decisions.
This creates two types of situations for the :class:`~whenever.ZonedDateTime`
and :class:`~whenever.SystemDateTime` types:

- When the clock moves backwards, there is a period of time that occurs twice.
  For example, Sunday October 29th 2:30am occured twice in Paris.
  When you specify this time, you need to specify whether you want the earlier
  or later occurrence.
- When the clock moves forwards, a period of time is skipped.
  For example, Sunday March 26th 2:30am didn't happen in Paris.
  When you specify this time, you need to specify how you want to handle this non-existent time.
  Common approaches are to extrapolate the time forward or backwards
  to 1:30am or 3:30am.

By default, **whenever** `refuses to guess <https://peps.python.org/pep-0020/>`_,
but it is possible to customize how to handle these situations.
You choose the disambiguation behavior you want with the ``disambiguate=`` argument:

+------------------+-------------------------------------------------+
| ``disambiguate`` | Behavior in case of ambiguity                   |
+==================+=================================================+
| ``"raise"``      | (default) Refuse to guess:                      |
|                  | raise :exc:`~whenever.RepeatedTime`             |
|                  | or :exc:`~whenever.SkippedTime` exception.      |
+------------------+-------------------------------------------------+
| ``"earlier"``    | Choose the earlier of the two options           |
+------------------+-------------------------------------------------+
| ``"later"``      | Choose the later of the two options             |
+------------------+-------------------------------------------------+
| ``"compatible"`` | Choose "earlier" for backward transitions and   |
|                  | "later" for forward transitions. This matches   |
|                  | the behavior of other established libraries,    |
|                  | and the industry standard RFC 5545.             |
|                  | It corresponds to setting ``fold=0`` in the     |
|                  | standard library.                               |
+------------------+-------------------------------------------------+

.. code-block:: python

    >>> paris = "Europe/Paris"

    >>> # Not ambiguous: everything is fine
    >>> ZonedDateTime(2023, 1, 1, tz=paris)
    ZonedDateTime(2023-01-01 00:00:00+01:00[Europe/Paris])

    >>> # Ambiguous: 1:30am occurs twice. Refuse to guess.
    >>> ZonedDateTime(2023, 10, 29, 2, 30, tz=paris)
    Traceback (most recent call last):
      ...
    whenever.RepeatedTime: 2023-10-29 02:30:00 is repeated in timezone Europe/Paris

    >>> # Repeated: explicitly choose the earlier option
    >>> ZonedDateTime(2023, 10, 29, 2, 30, tz=paris, disambiguate="earlier")
    ZoneDateTime(2023-10-29 02:30:00+01:00[Europe/Paris])

    >>> # Skipped: 2:30am doesn't exist.
    >>> ZonedDateTime(2023, 3, 26, 2, 30, tz=paris)
    Traceback (most recent call last):
      ...
    whenever.SkippedTime: 2023-03-26 02:30:00 is skipped in timezone Europe/Paris

    >>> # Non-existent: extrapolate to 3:30am
    >>> ZonedDateTime(2023, 3, 26, 2, 30, tz=paris, disambiguate="later")
    ZonedDateTime(2023-03-26 03:30:00+02:00[Europe/Paris])

Formatting and parsing
----------------------

**Whenever** supports formatting and parsing standardized formats

.. _iso8601:

ISO 8601
~~~~~~~~

The `ISO 8601 <https://en.wikipedia.org/wiki/ISO_8601>`_ standard
is probably the format you're most familiar with.
What you may not know is that it's a very complex standard with many options.
Like most libraries, **whenever** supports a only subset of the standard
which is the most commonly used.

Here are the ISO formats for each type:

+-----------------------------------------+------------------------------------------------+
| Type                                    | Canonical string format                        |
+=========================================+================================================+
| :class:`~whenever.Instant`              | ``YYYY-MM-DDTHH:MM:SSZ``                       |
+-----------------------------------------+------------------------------------------------+
| :class:`~whenever.LocalDateTime`        | ``YYYY-MM-DDTHH:MM:SS``                        |
+-----------------------------------------+------------------------------------------------+
| :class:`~whenever.ZonedDateTime`        | ``YYYY-MM-DDTHH:MM:SS±HH:MM[IANA TZ ID]`` [1]_ |
+-----------------------------------------+------------------------------------------------+
| :class:`~whenever.OffsetDateTime`       | ``YYYY-MM-DDTHH:MM:SS±HH:MM``                  |
+-----------------------------------------+------------------------------------------------+
| :class:`~whenever.SystemDateTime`       | ``YYYY-MM-DDTHH:MM:SS±HH:MM``                  |
+-----------------------------------------+------------------------------------------------+

Where:

- Seconds may be fractional
- Offsets may have second precision
- The offset may be replaced with a ``"Z"`` to indicate UTC

Use the methods :meth:`~whenever._BasicConversions.format_common_iso` and
:meth:`~whenever._BasicConversions.parse_common_iso` to format and parse
to this format, respectively:

>>> d = OffsetDateTime(2023, 12, 28, 11, 30, offset=+5)
>>> d.format_common_iso()
'2023-12-28T11:30:00+05:00'
>>> OffsetDateTime.parse_common_iso('2021-07-13T09:45:00-09:00')
OffsetDateTime(2021-07-13 09:45:00-09:00)

.. note::

   The ISO formats in **whenever** are designed so you can format and parse
   them without losing information.
   This makes it ideal for JSON serialization and other data interchange formats.

.. admonition:: Why not support the full ISO 8601 spec?

   The full ISO 8601 standard is not supported for several reasons:

   - It allows for a lot of rarely-used flexibility:
     e.g. fractional hours, omitting separators, week-based years, etc.
   - There are different versions of the standard with different rules
   - The full specification is not freely available

   This isn't a problem in practice since people referring to "ISO 8601"
   often mean the most common subset, which is what **whenever** supports.
   It's rare for libraries to support the full standard.
   The method name ``parse_common_iso`` makes this assumption explicit.

   If you do need to parse the full spectrum of ISO 8601, you can use
   a specialized library such as `dateutil.parser <https://dateutil.readthedocs.io/en/stable/parser.html>`_.
   If possible, it's recommend to use the :ref:`RFC 3339 <rfc3339>` format instead.

.. _rfc3339:

RFC 3339
~~~~~~~~

`RFC 3339 <https://tools.ietf.org/html/rfc3339>`_ is a subset of ISO 8601
with a few deviations. The format is:

.. code-block:: text

   YYYY-MM-DDTHH:MM:SS±HH:MM

For example: ``2023-12-28T11:30:00+05:00``

Where:

- Seconds may be fractional
- The offset may be replaced with a ``"Z"`` to indicate UTC
- ``T`` may be replaced with a space or ``_`` (unlike ISO 8601)
- ``T`` and ``Z`` may be lowercase (unlike ISO 8601)
- The offset is limited to whole minutes (unlike ISO 8601)

Use the methods :meth:`~whenever.OffsetDateTime.format_rfc3339` and
:meth:`~whenever.OffsetDateTime.parse_rfc3339` to format and parse
to this format, respectively:

>>> d = OffsetDateTime(2023, 12, 28, 11, 30, offset=+5)
>>> d.format_rfc3339()
'2023-12-28T11:30:00+05:00'
>>> OffsetDateTime.parse_rfc3339('2021-07-13 09:45:00Z')
OffsetDateTime(2021-07-13 09:45:00Z)

RFC 2822
~~~~~~~~

`RFC 2822 <https://datatracker.ietf.org/doc/html/rfc2822.html#section-3.3>`_ is another common format
for representing datetimes. It's used in email headers and HTTP headers.
The format is:

.. code-block:: text

   Weekday, DD Mon YYYY HH:MM:SS ±HHMM

For example: ``Tue, 13 Jul 2021 09:45:00 -0900``

Use the methods :meth:`~whenever.OffsetDateTime.format_rfc2822` and
:meth:`~whenever.OffsetDateTime.parse_rfc2822` to format and parse
to this format, respectively:

>>> d = OffsetDateTime(2023, 12, 28, 11, 30, offset=+5)
>>> d.format_rfc2822()
'Thu, 28 Dec 2023 11:30:00 +0500'
>>> OffsetDateTime.parse_rfc2822('Tue, 13 Jul 2021 09:45:00 -0900')
OffsetDateTime(2021-07-13 09:45:00-09:00)

Custom formats
~~~~~~~~~~~~~~

For now, basic customized parsing functionality is implemented in the ``strptime()`` methods
of :class:`~whenever.OffsetDateTime` and :class:`~whenever.LocalDateTime`.
As the name suggests, these methods are thin wrappers around the standard library
:meth:`~datetime.datetime.strptime` function.
The same `formatting rules <https://docs.python.org/3/library/datetime.html#format-codes>`_ apply.

>>> OffsetDateTime.strptime("2023-01-01+05:00", "%Y-%m-%d%z")
OffsetDateTime(2023-01-01 00:00:00+05:00)
>>> LocalDateTime.strptime("2023-01-01 15:00", "%Y-%m-%d %H:%M")
LocalDateTime(2023-01-01 15:00:00)

:class:`~whenever.ZonedDateTime` and :class:`~whenever.SystemDateTime` do not (yet)
implement ``strptime()`` methods, because they require disambiguation.
If you'd like to parse into these types,
use :meth:`LocalDateTime.strptime() <whenever.LocalDateTime.strptime>`
to parse them, and then use the :meth:`~whenever.LocalDateTime.assume_utc`,
:meth:`~whenever.LocalDateTime.assume_fixed_offset`,
:meth:`~whenever.LocalDateTime.assume_tz`,
or :meth:`~whenever.LocalDateTime.assume_system_tz`
methods to convert them.
This makes it explicit what information is being assumed.

>>> d = LocalDateTime.strptime("2023-10-29 02:30:00", "%Y-%m-%d %H:%M:%S")
>>> # handling ambiguity
>>> d.assume_tz("Europe/Amsterdam", disambiguate="earlier")
ZonedDateTime(2023-10-29 02:30:00+02:00[Europe/Amsterdam])

.. admonition:: Future plans

   Python's builtin ``strptime`` has its limitations, so a more full-featured
   parsing API may be added in the future.

To and from the standard library
--------------------------------

Each **whenever** datetime class can be converted to a standard
library :class:`~datetime.datetime`
with the :meth:`~whenever._BasicConversions.py_datetime` method.
Conversely, you can create a type from a standard library datetime with the
:meth:`~whenever._BasicConversions.from_py_datetime` classmethod.

>>> from datetime import datetime, UTC
>>> Instant.from_py_datetime(datetime(2023, 1, 1, tzinfo=UTC))
Instant(2023-01-01 00:00:00Z)
>>> ZonedDateTime(2023, 1, 1, tz="Europe/Amsterdam").py_datetime()
datetime(2023, 1, 1, 0, 0, tzinfo=ZoneInfo('Europe/Amsterdam'))

.. note::

   ``from_py_datetime`` also works for subclasses, so you can also ingest types
   from ``pendulum`` and ``arrow`` libraries.


Date and time components
------------------------

Aside from the datetimes themselves, **whenever** also provides
:class:`~whenever.Date` for calendar dates and :class:`~whenever.Time` for
representing times of day.

>>> from whenever import Date, Time
>>> Date(2023, 1, 1)
Date(2023-01-01)
>>> Time(12, 30)
Time(12:30:00)

These types can be converted to datetimes and vice versa:

>>> Date(2023, 1, 1).at(Time(12, 30))
LocalDateTime(2023-01-01 12:30:00)
>>> ZonedDateTime.now("Asia/Tokyo").date()
Date(2023-07-13)

Dates support arithmetic with months and years,
with similar semantics to modern datetime libraries:

>>> d = Date(2023, 1, 31)
>>> d.add(months=1)
Date(2023-02-28)
>>> d - Date(2022, 10, 15)
DateDelta(P3M16D)

See the :ref:`API reference <date-and-time-api>` for more details.

.. _systemtime:

The system timezone
-------------------

The system running the code also has a timezone configured.
It's important to be aware that the system timezone can change.
Instances of :class:`~whenever.SystemDateTime` have the fixed offset
of the system timezone at the time of initialization.
The system timezone may change afterwards,
but instances of this type will not reflect that change.
This is because:

- There are several ways to deal with such a change:
  should the moment in time be preserved, or the local time on the clock?
- Automatically reflecting that change would mean that the object could
  change at any time, depending on some global mutable state.
  This would make it harder to reason about and use.

>>> # initialization where the system timezone is America/New_York
>>> d = SystemDateTime(2020, 8, 15, hour=8)
SystemDateTime(2020-08-15 08:00:00-04:00)
...
>>> # we change the system timezone to Amsterdam
>>> os.environ["TZ"] = "Europe/Amsterdam"
>>> time.tzset()
...
>>> d  # object remains unchanged
SystemDateTime(2020-08-15 08:00:00-04:00)

If you'd like to preserve the moment in time
and calculate the new local time, simply call
:meth:`~whenever._KnowsInstant.to_system_tz`.

>>> # same moment, but now with the clock time in Amsterdam
>>> d.to_system_tz()
DateTime(2020-08-15 14:00:00+02:00)

On the other hand, if you'd like to preserve the local time on the clock
and calculate the corresponding moment in time:

>>> # take the wall clock time and assume the (new) system timezone (Amsterdam)
>>> d.local().assume_system_tz()
SystemDateTime(2020-08-15 08:00:00+02:00)

.. note::

   Remember that :meth:`~whenever.LocalDateTime.assume_system_tz` may
   require disambiguation, if the wall clock time is ambiguous in
   the system timezone.

.. seealso::

   :ref:`Why does SystemDateTime exist? <faq-why-system-tz>`

.. [2] java.time, Noda Time (C#), and partly Temporal (JavaScript)
   all use a similar datamodel.
   `Here is an excellent video on the topic <https://www.youtube.com/watch?v=saeKBuPewcU>`_.


.. [1] The timezone ID is not part of the core ISO 8601 standard,
   but is part of the RFC 9557 extension.
   This format is commonly used by datetime libraries in other languages as well.

