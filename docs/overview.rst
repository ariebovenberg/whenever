.. _overview:

🕗 Datetimes
============

This page gives an overview of **whenever**'s main features for working with datetimes.
For more details, see the :ref:`API reference <api>`.

Different types
---------------

.. epigraph::

   In API design, if you've got two things that are even subtly different,
   it's worth having them as separate types—because you're representing the
   meaning of your data more accurately.

   -- Jon Skeet

While the standard library has a single :class:`~datetime.datetime` type,
**whenever** provides five distinct types.
Each is designed to communicate intent, prevent mistakes, and optimize performance.
You probably won't need all of them simultaneously in your project.
Read on to find out which one is right for you.

.. code-block:: python

   from whenever import (
       UTCDateTime, OffsetDateTime, ZonedDateTime, LocalSystemDateTime, NaiveDateTime
   )

Here's a summary of how you can use them:

+-----------------------+-----+--------+-------+-------+-------+
| Feature               |         Aware                | Naive |
+                       +-----+--------+-------+-------+       +
|                       | UTC | Offset | Zoned | Local |       |
+=======================+=====+========+=======+=======+=======+
| comparison            | ✅  |  ✅    |  ✅   |  ✅   |  ✅   |
+-----------------------+-----+--------+-------+-------+-------+
| difference            | ✅  |  ✅    |  ✅   |  ✅   |  ✅   |
+-----------------------+-----+--------+-------+-------+-------+
| add/subtract delta    | ✅  |  ❌    |  ✅   |  ✅   |  ✅   |
+-----------------------+-----+--------+-------+-------+-------+
| unambiguous           | ✅  |  ✅    |  ❌   |  ❌   |  ✅   |
+-----------------------+-----+--------+-------+-------+-------+
| to/from timestamp     | ✅  |  ✅    |  ✅   |  ✅   |  ❌   |
+-----------------------+-----+--------+-------+-------+-------+
| now                   | ✅  |  ✅    |  ✅   |  ✅   |  ❌   |
+-----------------------+-----+--------+-------+-------+-------+
| to/from common ISO8601| ✅  |  ✅    |  ❌   |  ❌   |  ✅   |
+-----------------------+-----+--------+-------+-------+-------+
| to/from RFC3339/2822  | ✅  |  ✅    |  ❌   |  ❌   |  ❌   |
+-----------------------+-----+--------+-------+-------+-------+

:class:`~whenever.UTCDateTime`
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Always UTC: simple, fast, and unambiguous.
It's great if you're storing when something happened (or will happen)
regardless of location.

>>> py311_livestream = UTCDateTime(2022, 10, 24, hour=17)
UTCDateTime(2022-10-24 17:00:00Z)

In most cases, you should use this class over the others. The other
classes are most often useful at the boundaries of your application.

:class:`~whenever.OffsetDateTime`
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

A time with a fixed offset from UTC.
This is great if you're storing when something happened,
including the local time.

>>> # Pycon was in Salt Lake City that year
>>> pycon23_start = OffsetDateTime(2023, 4, 21, hour=9, offset=-6)
OffsetDateTime(2023-04-21 09:00:00-06:00)

It's less suitable for *future* events,
because local UTC offsets often change (e.g. due to daylight saving time).
For this reason, you cannot add or subtract time from an :class:`~whenever.OffsetDateTime`
— the offset may have changed!

.. seealso::

   - :ref:`Why does UTCDateTime exist if OffsetDateTime can do the same? <faq-why-utc>`
   - :ref:`Why doen't OffsetDateTime support arithmetic? <faq-offset-arithmetic>`

:class:`~whenever.ZonedDateTime`
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

This class accounts for the variable UTC offset of timezones,
and is great for representing localized times in the past and future.
Note that when the clock is set backwards, times occur twice.
Use ``disambiguate`` to resolve these situations.

>>> changing_the_guard = ZonedDateTime(2024, 12, 8, hour=11, tz="Europe/London")
ZonedDateTime(2024-12-08 11:00:00+00:00[Europe/London])
>>> ZonedDateTime(2023, 10, 29, 1, 15, tz="Europe/London", disambiguate="later")
ZonedDateTime(2023-10-29 01:15:00+00:00[Europe/London])

:class:`~whenever.LocalSystemDateTime`
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

This is a datetime in the system local timezone.
Unless you're building a system that specifically runs on the user's local
machine (such as a CLI), you should avoid using this type.

>>> # assuming system timezone is America/New_York
>>> backup_performed = LocalSystemDateTime(2023, 12, 28, hour=2)
LocalSystemDateTime(2023-12-28 02:00:00-05:00)

.. seealso::

   - :ref:`Why does LocalSystemDateTime exist? <faq-why-local>`
   - :ref:`Working with the local system timezone <localtime>`

:class:`~whenever.NaiveDateTime`
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

In dealing with real-world data, you'll often encounter datetimes
that don't have timezone information.
Use ``NaiveDateTime`` to represent these datetimes.

>>> invite_received = NaiveDateTime(2020, 3, 14, hour=15)
NaiveDateTime(2020-03-14 15:00:00)

.. seealso::

   :ref:`Why does NaiveDateTime exist? <faq-why-naive>`

Comparison and equality
-----------------------

All types support equality and comparison.
However, :class:`~whenever.NaiveDateTime` instances are
never equal or comparable to the aware types.

Aware types
~~~~~~~~~~~

For aware types (:class:`~whenever.UTCDateTime`, :class:`~whenever.OffsetDateTime`,
:class:`~whenever.ZonedDateTime`, and :class:`~whenever.LocalSystemDateTime`),
comparison and equality are based on whether they represent the same moment in
time. This means that two datetimes with different values can be equal:

>>> # different ways of representing the same moment in time
>>> as_utc = UTCDateTime(2023, 12, 28, 11, 30)
>>> as_5hr_offset = OffsetDateTime(2023, 12, 28, 16, 30, offset=hours(5))
>>> as_8hr_offset = OffsetDateTime(2023, 12, 28, 19, 30, offset=hours(8))
>>> as_zoned = ZonedDateTime(2023, 12, 28, 6, 30, tz="America/New_York")
>>> # all equal
>>> as_utc == as_5hr_offset == as_8hr_offset == as_zoned
True
>>> # comparison
>>> as_zoned > OffsetDateTime(2023, 12, 28, 11, 30, offset=hours(5))
True

.. note::

   Another way to think about this is that the equality operator compares
   the UTC equivalent of the datetimes.  ``a == b`` is always equivalent to
   ``a.as_utc() == b.as_utc()``, and ``a > b`` is always equivalent to
   ``a.as_utc() > b.as_utc()``, and so on.

Note that if you want to compare for exact equality on the values
(i.e. exactly the same year, month, day, hour, minute, etc.), you can use
the :meth:`~whenever._AwareDateTime.exact_eq` method.

>>> d = OffsetDateTime(2023, 12, 28, 11, 30, offset=5)
>>> same = OffsetDateTime(2023, 12, 28, 11, 30, offset=5)
>>> same_moment = OffsetDateTime(2023, 12, 28, 12, 30, offset=6)
>>> d == same_moment
True
>>> d.exact_eq(same_moment)
False
>>> d.exact_eq(same)
True

Naive types
~~~~~~~~~~~

For :class:`~whenever.NaiveDateTime`, equality is simply based on
whether the values are the same, since there is no concept of timezones or UTC offset:

>>> d = NaiveDateTime(2023, 12, 28, 11, 30)
>>> same = NaiveDateTime(2023, 12, 28, 11, 30)
>>> different = NaiveDateTime(2023, 12, 28, 11, 31)
>>> d == same
True
>>> d == different
False

.. seealso::

   See the documentation of :meth:`__eq__ (aware) <whenever._AwareDateTime.__eq__>`
   and :meth:`NaiveDateTime.__eq__ <whenever.NaiveDateTime.__eq__>` for more details.


Strict equality
~~~~~~~~~~~~~~~

Naive and aware types are never equal or comparable to each other.
However, to comply with the Python data model, the equality operator
won't prevent you from using ``==`` to compare them.
To prevent these mix-ups, use mypy's ``--strict-equality``
`flag <https://mypy.readthedocs.io/en/stable/command_line.html#cmdoption-mypy-strict-equality>`_.

>>> # These are never equal, but Python won't stop you from comparing them.
>>> # Mypy will catch this mix-up if you use enable --strict-equality flag.
>>> UTCDateTime(2023, 12, 28) == NaiveDateTime(2023, 12, 28)
False

.. admonition:: Why not raise a TypeError?

    It may *seem* like the equality operator should raise a :exc:`TypeError`
    in these cases, but this would result in
    `surprising behavior <https://stackoverflow.com/a/33417512>`_
    when using values as dictionary keys.

Unfortunately, mypy's ``--strict-equality`` is *very* strict,
forcing you to match aware types exactly.

.. code-block:: python

    d = UTCDateTime(2023, 12, 28, 10)

    # mypy: ✅
    d == UTCDateTime(2023, 12, 28, 10)

    # mypy: ❌ (too strict, this should be allowed)
    d == OffsetDateTime(2023, 12, 28, 11, offset=1)

To work around this, you can either convert explicitly:

.. code-block:: python

    d == OffsetDateTime(2023, 12, 28, 11, offset=1).as_utc()

Or annotate with a union:

.. code-block:: python

    d: OffsetDateTime | UTCDateTime == OffsetDateTime(2023, 12, 28, 11, offset=1)


Conversion
----------

Between aware types
~~~~~~~~~~~~~~~~~~~

You can convert between aware datetimes with the :meth:`~whenever._AwareDateTime.as_utc`,
:meth:`~whenever._AwareDateTime.as_offset`, :meth:`~whenever._AwareDateTime.as_zoned`,
and :meth:`~whenever._AwareDateTime.as_local` methods. These methods return a new
instance of the appropriate type, representing the same moment in time.
This means the results will always compare equal to the original datetime.

>>> d = ZonedDateTime(2023, 12, 28, 11, 30, tz="Europe/Amsterdam")
>>> d.as_utc()  # same moment in UTC
UTCDateTime(2023-12-28 10:30:00Z)
>>> d.as_offset(5)  # same moment with a +5:00 offset
OffsetDateTime(2023-12-28 15:30:00+05:00)
>>> d.as_zoned("America/New_York")  # same moment in New York
ZonedDateTime(2023-12-28 05:30:00-05:00[America/New_York])
>>> d.as_local()  # same moment in the system timezone (e.g. Europe/Paris)
LocalSystemDateTime(2023-12-28 11:30:00+01:00)
>>> d.as_offset(4) == d
True  # always the same moment in time

To and from naïve
~~~~~~~~~~~~~~~~~

Conversion to naïve types is always easy: calling
:meth:`~whenever._AwareDateTime.naive` simply strips
away any timezone information:

>>> d = ZonedDateTime(2023, 12, 28, 11, 30, tz="Europe/Amsterdam")
>>> n = d.naive()
NaiveDateTime(2023-12-28 11:30:00)

You can convert from naïve types with the :meth:`~whenever.NaiveDateTime.assume_utc`,
:meth:`~whenever.NaiveDateTime.assume_offset`, and
:meth:`~whenever.NaiveDateTime.assume_zoned`, and
:meth:`~whenever.NaiveDateTime.assume_local` methods.

>>> n = NaiveDateTime(2023, 12, 28, 11, 30)
>>> n.assume_utc()
UTCDateTime(2023-12-28 11:30:00Z)
>>> n.assume_zoned("Europe/Amsterdam")
ZonedDateTime(2023-12-28 11:30:00+01:00[Europe/Amsterdam])

.. note::

   The seemingly inconsistent naming of the ``assume_*`` methods is intentional. The ``assume_*`` methods
   emphasize that the conversion is not self-evident, but based on assumptions
   of the developer.


Arithmetic
----------

Datetimes support varous arithmetic operations with addition and subtraction.

Difference between times
~~~~~~~~~~~~~~~~~~~~~~~~

You can subtract two datetime instances to get a
:class:`~whenever.TimeDelta` representing the duration between them.
Aware types can be mixed with each other,
but naive types cannot be mixed with aware types:

>>> # difference between moments in time
>>> UTCDateTime(2023, 12, 28, 11, 30) - ZonedDateTime(2023, 12, 28, tz="Europe/Amsterdam")
TimeDelta(12:30:00)
>>> # difference between naive datetimes
>>> NaiveDateTime(2023, 12, 28, 11) - NaiveDateTime(2023, 12, 27, 11)
TimeDelta(24:00:00)

.. _add-subtract-time:

Adding and subtracting time
~~~~~~~~~~~~~~~~~~~~~~~~~~~

You can add or subtract various units of time from a datetime instance.

>>> d = ZonedDateTime(2023, 12, 28, 11, 30, tz="Europe/Amsterdam")
>>> d.add(hours=5, minutes=30)
ZonedDateTime(2023-12-28 17:00:00+01:00[Europe/Amsterdam])
>>> d.subtract(days=1)  # 1 day earlier
ZonedDateTime(2023-12-27 11:30:00+01:00[Europe/Amsterdam])

Adding/subtracting takes into account timezone changes (e.g. daylight saving time)
according to industry standard RFC 5545. This means:

- Units are added from largest (year) to smallest (microsecond),
  truncating and/or wrapping at each step.
- Precise time units (hours, minutes, and seconds) account for DST changes,
  but calendar units (days, months, years) do not.
  The expectation is that rescheduling a 10am appointment "a day later"
  will still be at 10am, even after DST changes.

.. seealso::

   Have a look at the documentation on :ref:`deltas <durations>` for more details
   on arithmetic operations, as well as more advanced features.

.. attention::

   :class:`~whenever.OffsetDateTime` instances do not support moving back and
   forwards in time, because offsets in real world timezones aren't always constant.
   That is, the offset may be different after moving backwards or forwards in time.
   If you need to shift an :class:`~whenever.OffsetDateTime` instance,
   either convert to UTC or a proper timezone first.

Ambiguity in timezones
----------------------

.. note::

   The API for handling ambiguitiy is inspired by that of
   `Temporal <https://tc39.es/proposal-temporal/docs/ambiguity.html>`_,
   the redesigned date and time API for JavaScript.

In real-world timezones, local clocks are often moved backwards and forwards
due to Daylight Saving Time (DST) or political decisions.
This creates two types of situations for the :class:`~whenever.ZonedDateTime`
and :class:`~whenever.LocalSystemDateTime` types:

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
|                  | raise :exc:`~whenever.AmbiguousTime`            |
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
    whenever.AmbiguousTime: 2023-10-29 02:30:00 is ambiguous in timezone Europe/Paris

    >>> # Ambiguous: explicitly choose the earlier option
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


Standardized representations
----------------------------

**Whenever** supports various standardized representations of datetimes.

ISO 8601
~~~~~~~~

The `ISO 8601 <https://en.wikipedia.org/wiki/ISO_8601>`_ standard
is probably the format you're most familiar with.
What you may not know is that it's a very complex standard with many options.
Like most libraries, **whenever** supports a subset of the standard 
which is the most commonly used:

.. code-block:: text

   YYYY-MM-DDTHH:MM:SS±HH:MM

For example: ``2023-12-28T11:30:00+05:00``

Where:

- Seconds may be fractional
- The offset may be replaced with a ``"Z"`` to indicate UTC
- Offset ``-00:00`` is not allowed

Use the methods :meth:`~whenever.OffsetDateTime.common_iso8601` and
:meth:`~whenever.OffsetDateTime.from_common_iso8601` to format and parse
to this format, respectively:

>>> d = OffsetDateTime(2023, 12, 28, 11, 30, offset=+5)
>>> d.common_iso8601()
'2023-12-28T11:30:00+05:00'
>>> OffsetDateTime.from_common_iso8601('2021-07-13T09:45:00-09:00')
OffsetDateTime(2021-07-13 09:45:00-09:00)

.. admonition:: Why not support the full ISO 8601 spec?

   The full ISO 8601 standard is not supported for several reasons:

   - It allows for a lot of rarely-used flexibility:
     e.g. fractional hours, omitting separators, week-based years, etc.
   - There are different versions of the standard with different rules
   - The full specification is not freely available

   This isn't a problem in practice since people referring to "ISO 8601"
   often mean the most common subset, which is what **whenever** supports.
   It's rare for libraries to support the full standard.
   The method name ``from_common_iso8601`` makes this assumption explicit.

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
- ``T`` may be replaced with a space (unlike ISO 8601)
- ``T`` and ``Z`` may be lowercase (unlike ISO 8601)

Use the methods :meth:`~whenever.OffsetDateTime.rfc3339` and
:meth:`~whenever.OffsetDateTime.from_rfc3339` to format and parse
to this format, respectively:

>>> d = OffsetDateTime(2023, 12, 28, 11, 30, offset=+5)
>>> d.rfc3339()
'2023-12-28T11:30:00+05:00'
>>> OffsetDateTime.from_rfc3339('2021-07-13 09:45:00Z')
OffsetDateTime(2021-07-13 09:45:00Z)

RFC 2822
~~~~~~~~

`RFC 2822 <https://datatracker.ietf.org/doc/html/rfc2822.html#section-3.3>`_ is another common format
for representing datetimes. It's used in email headers and HTTP headers.
The format is:

.. code-block:: text

   Weekday, DD Mon YYYY HH:MM:SS ±HHMM

For example: ``Tue, 13 Jul 2021 09:45:00 -0900``

Use the methods :meth:`~whenever.OffsetDateTime.rfc2822` and
:meth:`~whenever.OffsetDateTime.from_rfc2822` to format and parse
to this format, respectively:

>>> d = OffsetDateTime(2023, 12, 28, 11, 30, offset=+5)
>>> d.rfc2822()
'Thu, 28 Dec 2023 11:30:00 +0500'
>>> OffsetDateTime.from_rfc2822('Tue, 13 Jul 2021 09:45:00 -0900')
OffsetDateTime(2021-07-13 09:45:00-09:00)

To and from the standard library
--------------------------------

Each **whenever** datetime class can be converted to a standard
library :class:`~datetime.datetime`
with the :meth:`~whenever._DateTime.py_datetime` method.
Conversely, you can create a type from a standard library datetime with the
:meth:`~whenever._DateTime.from_py_datetime` classmethod.

>>> from datetime import datetime, UTC
>>> UTCDateTime.from_py_datetime(datetime(2023, 1, 1, tzinfo=UTC))
UTCDateTime(2023-01-01 00:00:00Z)
>>> ZonedDateTime(2023, 1, 1, tz="Europe/Amsterdam").py_datetime()
datetime(2023, 1, 1, 0, 0, tzinfo=ZoneInfo('Europe/Amsterdam'))

Parsing
-------

For now, basic parsing functionality is implemented in the ``strptime()`` methods
of :class:`~whenever.UTCDateTime`, :class:`~whenever.OffsetDateTime`,
and :class:`~whenever.NaiveDateTime`.
As the name suggests, these methods are thin wrappers around the standard library
:meth:`~datetime.datetime.strptime` function.
The same `formatting rules <https://docs.python.org/3/library/datetime.html#format-codes>`_ apply.

.. code-block:: python

   UTCDateTime.strptime("2023-01-01 12:30", "%Y-%m-%d %H:%M")  # 2023-01-01 12:30:00Z
   OffsetDateTime.strptime("2023-01-01+05:00", "%Y-%m-%d%z")  # 2023-01-01 00:00:00+05:00
   NaiveDateTime.strptime("2023-01-01 00:00", "%Y-%m-%d %H:%M")  # 2023-01-01 00:00:00

:class:`~whenever.ZonedDateTime` and :class:`~whenever.LocalSystemDateTime` do not (yet)
implement ``strptime()`` methods, because they require disambiguation.
If you'd like to parse into these types,
use :meth:`NaiveDateTime.strptime() <whenever.NaiveDateTime.strptime>`
to parse them, and then use the :meth:`~whenever.NaiveDateTime.assume_utc`,
:meth:`~whenever.NaiveDateTime.assume_offset`,
:meth:`~whenever.NaiveDateTime.assume_zoned`, or :meth:`~whenever.NaiveDateTime.assume_local`
methods to convert them.
This makes it explicit what information is being assumed.

.. code-block:: python

    NaiveDateTime.strptime("2023-01-01 12:00", "%Y-%m-%d %H:%M").assume_local()

    # handling ambiguity
    NaiveDateTime.strptime("2023-10-29 02:30:00", "%Y-%m-%d %H:%M:%S").assume_zoned(
        "Europe/Amsterdam",
        disambiguate="earlier",
    )

.. admonition:: Future plans

   Python's builtin ``strptime`` has its limitations, so a more full-featured
   parsing API may be added in the future.


Serialization
-------------

Canonical string format
~~~~~~~~~~~~~~~~~~~~~~~

Each type has a canonical textual format, which is used when converting to and
from strings. The canonical format is designed to be unambiguous, and to
preserve all information. This makes it ideal for storing datetimes in a
database, or inclusing in JSON.

Here are the canonical formats for each type:

+-----------------------------------------+---------------------------------------------------------------------+
| Type                                    | Canonical string format                                             |
+=========================================+=====================================================================+
| :class:`~whenever.UTCDateTime`          | ``YYYY-MM-DDTHH:MM:SS(.ffffff)Z``                                   |
+-----------------------------------------+---------------------------------------------------------------------+
| :class:`~whenever.OffsetDateTime`       | ``YYYY-MM-DDTHH:MM:SS(.ffffff)±HH:MM(:SS(.ffffff))``                |
+-----------------------------------------+---------------------------------------------------------------------+
| :class:`~whenever.ZonedDateTime`        | ``YYYY-MM-DDTHH:MM:SS(.ffffff)±HH:MM(:SS(.ffffff))[TIMEZONE ID]``   |
+-----------------------------------------+---------------------------------------------------------------------+
| :class:`~whenever.LocalSystemDateTime`  | ``YYYY-MM-DDTHH:MM:SS(.ffffff)±HH:MM(:SS(.ffffff))``                |
+-----------------------------------------+---------------------------------------------------------------------+
| :class:`~whenever.NaiveDateTime`        | ``YYYY-MM-DDTHH:MM:SS(.ffffff)``                                    |
+-----------------------------------------+---------------------------------------------------------------------+

.. code-block:: python

   >>> UTCDateTime(2023, 1, 1, 0, 0).canonical_format()
   '2023-01-01T00:00:00Z'
   >>> ZonedDateTime.from_canonical_format('2022-10-24T19:00:00+02:00[Europe/Paris]')
   ZonedDateTime(2022-10-24 19:00:00+02:00[Europe/Paris])

.. seealso::

   The methods :meth:`~whenever._DateTime.canonical_format` and
   :meth:`~whenever._DateTime.from_canonical_format` can be used to convert to and
   from the canonical string format.

.. note::

   The canonical format is similar to existing standards like ISO 8601 and RFC 3339.
   If parsing from these formats, it's recommended to use
   :meth:`~whenever.OffsetDateTime.from_common_iso8601` or 
   :meth:`~whenever.OffsetDateTime.from_rfc3339` over ``from_canonical_format()``. 
   These methods are more explicit and generally more lenient in what they accept.

Pickling
~~~~~~~~

All types are pickleable, so you can use them in a distributed system or
store them in a database that supports pickling.

.. code-block:: python

   import pickle

   d = UTCDateTime(2023, 1, 1, 0, 0)
   pickled = pickle.dumps(d)
   unpickled = pickle.loads(pickled)
   assert d == unpickled

.. note::

   From version 1.0 onwards, we aim to maintain backwards compatibility
   for unpickling.


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
NaiveDateTime(2023-01-01 12:30:00)
>>> UTCDateTime.now().date()
Date(2023-07-13)

See the :ref:`API reference <date-and-time-api>` for more details.

.. _localtime:

The local system timezone
-------------------------

The local timezone is the timezone of the system running the code.
It's important to be aware that the local timezone can change.
Instances of :class:`~whenever.LocalSystemDateTime` have the fixed offset
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
>>> d = LocalSystemDateTime(2020, 8, 15, hour=8)
LocalSystemDateTime(2020-08-15 08:00:00-04:00)
...
>>> # we change the system timezone to Amsterdam
>>> os.environ["TZ"] = "Europe/Amsterdam"
>>> time.tzset()
...
>>> d  # object remains unchanged
LocalSystemDateTime(2020-08-15 08:00:00-04:00)

If you'd like to preserve the moment in time
and calculate the new local time, simply call
:meth:`~whenever._AwareDateTime.as_local`.

>>> # same moment, but now with the clock time in Amsterdam
>>> d.as_local()
LocalSystemDateTime(2020-08-15 14:00:00+02:00)

On the other hand, if you'd like to preserve the local time on the clock
and calculate the corresponding moment in time:

>>> # take the wall clock time...
>>> wall_clock = d.naive()
NaiveDateTime(2020-08-15 08:00:00)
>>> # ...and assume the system timezone (Amsterdam)
>>> wall_clock.assume_local()
LocalSystemDateTime(2020-08-15 08:00:00+02:00)

.. note::

   Remember that :meth:`~whenever.NaiveDateTime.assume_local` may
   require disambiguation, if the wall clock time is ambiguous in
   the system timezone.

.. seealso::

   :ref:`Why does LocalSystemDateTime exist? <faq-why-local>`
