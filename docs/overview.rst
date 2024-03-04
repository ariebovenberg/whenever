.. _overview:

🧭 Overview
===========

This page gives a high-level overview of **whenever**'s features.
To get more details, see the :ref:`advanced features <advanced>` or the :ref:`API reference <api>`.

Datetime types
--------------

.. epigraph::

   In API design, if you've got two things that are even subtly different,
   it's worth having them as separate types—because you're representing the
   meaning of your data more accurately.

   -- Jon Skeet

While the standard library has a single :class:`~datetime.datetime` type,
**whenever** provides five different types to represent datetimes.
Each type is designed to communicate intent and prevent common mistakes.

.. code-block:: python

   from whenever import (
       UTCDateTime, OffsetDateTime, ZonedDateTime, LocalSystemDateTime, NaiveDateTime,
   )

and here's a summary of how you can use them:

+-----------------------+-----+--------+-------+-------+-------+
| Feature               |         Aware                | Naive |
+                       +-----+--------+-------+-------+       +
|                       | UTC | Offset | Zoned | Local |       |
+=======================+=====+========+=======+=======+=======+
| comparison            | ✅  |  ✅    |  ✅   |  ✅   |  ✅   |
+-----------------------+-----+--------+-------+-------+-------+
| difference            | ✅  |  ✅    |  ✅   |  ✅   |  ✅   |
+-----------------------+-----+--------+-------+-------+-------+
| add/subtract time     | ✅  |  ❌    |  ✅   |  ✅   |  ✅   |
+-----------------------+-----+--------+-------+-------+-------+
| unambiguous           | ✅  |  ✅    |  ❌   |  ❌   |  ✅   |
+-----------------------+-----+--------+-------+-------+-------+
| to/from timestamp     | ✅  |  ✅    |  ✅   |  ✅   |  ❌   |
+-----------------------+-----+--------+-------+-------+-------+
| now                   | ✅  |  ✅    |  ✅   |  ✅   |  ❌   |
+-----------------------+-----+--------+-------+-------+-------+
| to/from RFC2822       | ✅  |  ✅    |  ❌   |  ❌   |  ✅   |
+-----------------------+-----+--------+-------+-------+-------+
| to/from RFC3339       | ✅  |  ✅    |  ❌   |  ❌   |  ❌   |
+-----------------------+-----+--------+-------+-------+-------+

:class:`~whenever.UTCDateTime`
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Always UTC: simple, fast, and unambiguous.
It's great if you're storing when something happened (or will happen)
regardless of location.

>>> py311_livestream = UTCDateTime(2022, 10, 24, hour=17)
UTCDateTime(2022-10-24 17:00:00Z)

In >95% of cases, you should use this class over the others. The other
classes are most often useful at the boundaries of your application.

:class:`~whenever.OffsetDateTime`
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Defines a local time with its UTC offset.
This is great if you're storing when something happened at a local time.

>>> # Pycon was in Salt Lake City that year
>>> pycon23_start = OffsetDateTime(2023, 4, 21, hour=9, offset=-6)
OffsetDateTime(2023-04-21 09:00:00-06:00)

It's less suitable for *future* events,
because the UTC offset may change (e.g. due to daylight saving time).
For this reason, you cannot add or subtract time from an :class:`~whenever.OffsetDateTime`
— the offset may have changed!

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

:class:`~whenever.NaiveDateTime`
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

In dealing with real-world data, you'll often encounter datetimes
that don't have timezone information.
Use ``NaiveDateTime`` to represent these datetimes.

>>> invite_received = NaiveDateTime(2020, 3, 14, hour=15)
NaiveDateTime(2020-03-14 15:00:00)

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
the :meth:`~whenever.AwareDateTime.exact_eq` method.

>>> d = OffsetDateTime(2023, 12, 28, 11, 30, offset=5)

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

   See the documentation of :meth:`AwareDateTime.__eq__ <whenever.AwareDateTime.__eq__>`
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
    d == OffsetDateTime(2023, 12, 28, 10, offset=0)

To work around this, you can either convert explicitly:

.. code-block:: python

    d == OffsetDateTime(2023, 12, 28, offset=0).as_utc()

Or annotate with the :class:`~whenever.AwareDateTime` base class:

.. code-block:: python

    d: AwareDateTime == OffsetDateTime(2023, 12, 28, 10, offset=0)


Conversion
----------

Between aware types
~~~~~~~~~~~~~~~~~~~

You can convert between aware datetimes with the :meth:`~whenever.AwareDateTime.as_utc`,
:meth:`~whenever.AwareDateTime.as_offset`, :meth:`~whenever.AwareDateTime.as_zoned`,
and :meth:`~whenever.AwareDateTime.as_local` methods. These methods return a new
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
:meth:`~whenever.AwareDateTime.naive` simply strips
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

You can subtract two :class:`~whenever.DateTime` instances to get a
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

You can add or subtract various units of time from a :class:`~whenever.DateTime` instance.

>>> d = ZonedDateTime(2023, 12, 28, 11, 30, tz="Europe/Amsterdam")
>>> d.add(hours=5, minutes=30)
ZonedDateTime(2023-12-28 17:00:00+01:00[Europe/Amsterdam])
>>> d.subtract(days=1)  # 1 day earlier
ZonedDateTime(2023-12-27 11:30:00+01:00[Europe/Amsterdam])

Adding/subtracting takes into account timezone changes (e.g. daylight saving time)
according to industry standard RFC 5545. This means:

- Exact time units (hours, minutes, and seconds) account for DST changes, 
  but "nominal" units (days, months, years) do not.
  The expectation is that rescheduling a 10am appointment "a day later"
  will still be at 10am, even after DST changes.
- Units are added from largest (year) to smallest (microsecond).
  This means that adding a month to January 31st will result in February 28th or 29th,
  depending on the year.

.. seealso::

   Have a look at the documentation on :ref:`durations <durations>` for more details
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
|                  | raise :exc:`~whenever.Ambiguous`                |
|                  | or :exc:`~whenever.DoesntExist` exception.      |
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
    whenever.Ambiguous: 2023-10-29 02:30:00 is ambiguous in timezone Europe/Paris

    >>> # Ambiguous: explicitly choose the earlier option
    >>> ZonedDateTime(2023, 10, 29, 2, 30, tz=paris, disambiguate="earlier")
    ZoneDateTime(2023-10-29 02:30:00+01:00[Europe/Paris])

    >>> # Non-existent: 2:30am doesn't exist.
    >>> ZonedDateTime(2023, 3, 26, 2, 30, tz=paris)
    Traceback (most recent call last):
      ...
    whenever.DoesntExistInZone: 2023-03-26 02:30:00 doesn't exist in timezone Europe/Paris

    >>> # Non-existent: extrapolate to 3:30am
    >>> ZonedDateTime(2023, 3, 26, 2, 30, tz=paris, disambiguate="later")
    ZonedDateTime(2023-03-26 03:30:00+02:00[Europe/Paris])


Integrate with the standard library
-----------------------------------

Each **whenever** datetime class wraps a standard
library :class:`~datetime.datetime` instance.
You can access it with the :meth:`~whenever.DateTime.py_datetime` method.
Conversely, you can create a type from a standard library datetime with the
:meth:`~whenever.DateTime.from_py_datetime` classmethod.

>>> from datetime import datetime, UTC
>>> UTCDateTime.from_py(datetime(2023, 1, 1, tzinfo=UTC))
UTCDateTime(2023-01-01 00:00:00Z)
>>> ZonedDateTime(2023, 1, 1, tz="Europe/Amsterdam").py_datetime()
datetime(2023, 1, 1, 0, 0, tzinfo=ZoneInfo('Europe/Amsterdam'))

.. note::

   The fact that whenever datetimes wrap standard library datetimes
   is an implementation detail, and you should not rely on it.
   In the future, the implementation may change.


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
| :class:`~whenever.ZonedDateTime`        | ``YYYY-MM-DDTHH:MM:SS(.ffffff)±HH:MM(:SS(.ffffff))[TIMEZONE NAME]`` |
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

   The methods :meth:`~whenever.DateTime.canonical_format` and
   :meth:`~whenever.DateTime.from_canonical_format` can be used to convert to and
   from the canonical string format.

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

