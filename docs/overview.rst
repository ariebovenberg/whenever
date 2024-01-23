🧭 Overview
===========

This page gives a high-level overview of **whenever**'s features.
To get more details, see the :ref:`API reference <api>`.

The types
---------

**whenever** defines five types:

.. code-block:: python

   from whenever import (
       UTCDateTime, OffsetDateTime, ZonedDateTime, LocalDateTime, NaiveDateTime,
   )

and here's how you can use them:

+-----------------------+-----+--------+-------+-------+-------+
| Feature               |         Aware                | Naive |
+                       +-----+--------+-------+-------+       +
|                       | UTC | Offset | Zoned | Local |       |
+=======================+=====+========+=======+=======+=======+
| comparison            | ✅  |  ✅    |  ✅   |  ✅   |  ✅   |
+-----------------------+-----+--------+-------+-------+-------+
| difference            | ✅  |  ✅    |  ✅   |  ✅   |  ✅   |
+-----------------------+-----+--------+-------+-------+-------+
| add/subtract timedelta| ✅  |  ❌    |  ✅   |  ✅   |  ✅   |
+-----------------------+-----+--------+-------+-------+-------+
| unambiguous           | ✅  |  ✅    |  ❌   |  ❌   |  ✅   |
+-----------------------+-----+--------+-------+-------+-------+
| to/from timestamp     | ✅  |  ✅    |  ✅   |  ✅   |  ❌   |
+-----------------------+-----+--------+-------+-------+-------+
| now                   | ✅  |  ✅    |  ✅   |  ✅   |  ❌   |
+-----------------------+-----+--------+-------+-------+-------+
| hashable              | ✅  |  ✅    |  ✅   |  ❌   |  ✅   |
+-----------------------+-----+--------+-------+-------+-------+

``UTCDateTime``
~~~~~~~~~~~~~~~

Always UTC: simple, fast, and unambiguous.
It's great if you're storing when something happened (or will happen)
regardless of location.

.. code-block:: python

    py311_livestream = UTCDateTime(2022, 10, 24, hour=17)

In >95% of cases, you should use this class over the others. The other
classes are most often useful at the boundaries of your application.

``OffsetDateTime``
~~~~~~~~~~~~~~~~~~

Defines a local time with its UTC offset.
This is great if you're storing when something happened at a local time.

.. code-block:: python

    from whenever import hours  # alias for timedelta(hours=...)

    # 9:00 AM in Salt Lake City
    pycon23_start = OffsetDateTime(2023, 4, 21, hour=9, offset=hours(-6))

It's less suitable for *future* events,
because the UTC offset may change (e.g. due to daylight saving time).
For this reason, you cannot add/subtract a ``timedelta``
— the offset may have changed!

``ZonedDateTime``
~~~~~~~~~~~~~~~~~

This class accounts for the variable UTC offset of timezones,
and is great for representing localized times in the past and future.
Note that when the clock is set backwards, times occur twice.
Use ``disambiguate`` to resolve these situations.

.. code-block:: python

    # Always at 11:00 in London
    changing_the_guard = ZonedDateTime(2024, 12, 8, hour=11, tz="Europe/London")

    # Explicitly resolve ambiguities
    night_shift = ZonedDateTime(2023, 10, 29, 1, 15, tz="Europe/London", disambiguate="later")

``LocalDateTime``
~~~~~~~~~~~~~~~~~

This is a datetime in the system local timezone.
It's suitable for representing times related to the user's system.

.. code-block:: python

    print(f"Your timer will go off at {LocalDateTime.now() + hours(1)}.")

Because the local timezone may change, the moment in time represented by a
``LocalDateTime`` may change. Therefore, the type is not hashable.

``NaiveDateTime``
~~~~~~~~~~~~~~~~~

This type is detached from any timezone information.
Use this if you're only interested in what appears on a clock,
or if you absolutely don't need to account for the complexities of the real world.

.. code-block:: python

    clock_tower = NaiveDateTime(1955, 11, 12, hour=10, minute=4)
    city_simulation_start = NaiveDateTime(1900, 1, 1, hour=0)


Equality and comparison
-----------------------

All types support equality and comparison.
However, :class:`~whenever.NaiveDateTime` instances are
never equal or comparable to the aware types.

Aware types
~~~~~~~~~~~

For aware types (:class:`~whenever.UTCDateTime`, :class:`~whenever.OffsetDateTime`,
:class:`~whenever.ZonedDateTime`, and :class:`~whenever.LocalDateTime`),
comparison and equality are based on whether they represent the same moment in
time. This means that two datetimes with different values can be equal:

.. code-block:: python

    # different ways of representing the same moment in time
    >>> as_utc = UTCDateTime(2023, 12, 28, 11, 30)
    >>> as_5hr_offset = OffsetDateTime(2023, 12, 28, 16, 30, offset=hours(5))
    >>> as_8hr_offset = OffsetDateTime(2023, 12, 28, 19, 30, offset=hours(8))
    >>> as_zoned = ZonedDateTime(2023, 12, 28, 6, 30, tz="America/New_York")

    # all equal
    >>> as_utc == as_5hr_offset == as_8hr_offset == as_zoned
    True

    # comparison
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

Naive types
~~~~~~~~~~~

For :class:`~whenever.NaiveDateTime`, equality is simply based on
whether the values are the same, since there is no concept of timezones or UTC offset:

.. code-block:: python

    >>> d = NaiveDateTime(2023, 12, 28, 11, 30)
    >>> same = NaiveDateTime(2023, 12, 28, 11, 30)
    >>> different = NaiveDateTime(2023, 12, 28, 11, 31)

    >>> d == same
    >>> d != different


.. seealso::

   See the documentation of :meth:`AwareDateTime.__eq__ <whenever.AwareDateTime.__eq__>`
   and :meth:`NaiveDateTime.__eq__ <whenever.NaiveDateTime.__eq__>` for more details.


Strict equality
~~~~~~~~~~~~~~~

Naive and aware types are never equal or comparable to each other.
However, to comply with the Python data model, the equality operator
won't prevent you from using ``==`` to compare them.
It may *seem* like the equality operator should raise a :exc:`TypeError`
in these cases, but this would result in
`surprising behavior <https://stackoverflow.com/a/33417512>`_
when using values as dictionary keys.
Instead, use mypy's ``--strict-equality``
`flag <https://mypy.readthedocs.io/en/stable/command_line.html#cmdoption-mypy-strict-equality>`_
to detect and prevent these mistakes.

.. code-block:: python

    # These are never equal
    # Use mypy's --strict-equality flag to detect these mistakes
    >>> UTCDateTime(2023, 12, 28) == NaiveDateTime(2023, 12, 28)
    False

Conversion
----------

You can convert between aware datetimes with the :meth:`~whenever.AwareDateTime.as_utc`,
:meth:`~whenever.AwareDateTime.as_offset`, :meth:`~whenever.AwareDateTime.as_zoned`,
and :meth:`~whenever.AwareDateTime.as_local` methods. These methods return a new
instance of the appropriate type, representing the same moment in time.
This means the results will always compare equal to the original datetime.

.. code-block:: python

    >>> d = ZonedDateTime(2023, 12, 28, 11, 30, tz="Europe/Amsterdam")
    >>> d.as_utc()  # same moment in UTC
    >>> d.as_offset(hours(5))  # same moment with a +5:00 offset
    >>> d.as_zoned("America/New_York")  # same moment in New York
    >>> d.as_local()  # same moment in the system timezone

    >>> d.as_offset(hours(4)) == d  # True: always the same moment in time

You can convert to a :class:`~whenever.NaiveDateTime` with
:meth:`~whenever.AwareDateTime.naive`, which strips away any timezone or offset
information. Each aware type also defines a :meth:`from_naive` method.


.. code-block:: python

    >>> d = ZonedDateTime(2023, 12, 28, 11, 30, tz="Europe/Amsterdam")
    >>> n = d.naive()  # NaiveDateTime(2023-12-28 11:30:00)
    >>> OffsetDateTime.from_naive(n, offset=hours(5))  # 2023-12-28 11:30:00+05:00

.. note::

   The seemingly inconsistent naming of :meth:`~whenever.AwareDateTime.naive` and
   the ``as_*`` methods is intentional. The ``as_*`` methods preserve the same
   moment in time, while :meth:`~whenever.AwareDateTime.naive` converts to
   something else entirely.


Moving back and forwards in time
--------------------------------

You can add or subtract a :class:`~datetime.timedelta` from
:class:`~whenever.UTCDateTime`,
:class:`~whenever.ZonedDateTime`, :class:`~whenever.LocalDateTime`,
and :class:`~whenever.NaiveDateTime` instances. This represents moving forward or
backward in time by the given duration:

.. code-block:: python

    from whenever import days, hours  # aliases for timedelta(days=...) etc.

    >>> d = ZonedDateTime(2023, 12, 28, 11, 30, tz="Europe/Amsterdam")
    >>> d + hours(5)  # 5 hours later
    >>> d - days(1)  # 1 day earlier

Adding/subtracting takes into account daylight savings time and other
timezone variabilities.

.. attention::

   :class:`~whenever.OffsetDateTime` instances do not support moving back and
   forwards in time, because offsets in real world timezones aren't always constant.
   That is, the offset may be different after moving backwards or forwards in time.
   If you need to shift an :class:`~whenever.OffsetDateTime` instance,
   either convert to UTC or a proper timezone first.

Difference between datetimes
----------------------------

You can subtract two :class:`~whenever.DateTime` instances to get a
:class:`~datetime.timedelta` representing the duration between them.
Aware types can be mixed, but naive types cannot be mixed with aware types:

.. code-block:: python

    # difference between moments in time
    >>> UTCDateTime(2023, 12, 28, 11, 30) - ZonedDateTime(2023, 12, 14, tz="Europe/Amsterdam")

    # difference between naive datetimes
    >>> NaiveDateTime(2023, 12, 28, 11) - NaiveDateTime(2023, 12, 27, 11)

Timezone complexities
---------------------

In real-world timezones, local clocks are often moved backwards and forwards
due to daylight savings time or political decisions.
This creates two types of situations for the :class:`~whenever.ZonedDateTime`
and :class:`~whenever.LocalDateTime` types: *ambiguity* and *non-existence*.

Ambiguity
~~~~~~~~~

When a clock moves *backwards*, there is a period of time that occurs twice.
For example: if a clock goes back from 2am to 1am, then 1:30am occurs
twice: once before the clock goes back, and once after.

In such ambiguous cases, **whenever** `refuses to guess <https://peps.python.org/pep-0020/>`_
which of the two possible moments in time you intended:
You choose the disambiguation behavior you want with the ``disambiguate=`` argument:

+-------------------+-----------------------------------------------------------------------+
| ``disambiguate``  | Behavior in case of ambiguity                                         |
+===================+=======================================================================+
| ``"raise"``       | (default) Refuse to guess: raise :exc:`~whenever.Ambiguous` exception |
+-------------------+-----------------------------------------------------------------------+
| ``"earlier"``     | Choose the earlier of the two possible datetimes (before transition)  |
+-------------------+-----------------------------------------------------------------------+
| ``"later"``       | Choose the later of the two possible datetimes (after transition)     |
+-------------------+-----------------------------------------------------------------------+

.. code-block:: python

    ams = "Europe/Amsterdam"

    # Not ambiguous: everything is fine
    >>> ZonedDateTime(2023, 1, 1, tz=ams)

    # Ambiguous: 1:30am occurs twice. Refuse to guess.
    >>> ZonedDateTime(2023, 10, 29, 1, 30, tz=ams)
    Traceback (most recent call last):
      ...
    whenever.Ambiguous

    # Ambiguous: explicitly choose the earlier option
    >>> ZonedDateTime(2023, 10, 29, 1, 30, tz=ams, disambiguate="earlier")


Non-existence
~~~~~~~~~~~~~

When a clock moves forwards, there is a period of time that does not exist.
For example: if a clock skips forward from 1am to 2am, then 1:30am does not
exist.

:class:`~whenever.ZonedDateTime` and :class:`~whenever.LocalDateTime`
prevent you from creating non-existent datetimes, by raising a
:exc:`~whenever.DoesntExistInZone` exception if you try to create one.

.. code-block:: python

    >>> ZonedDateTime(2023, 3, 26, 2, 30, tz="Europe/Amsterdam")
    Traceback (most recent call last):
      ...
    whenever.DoesntExistInZone


Converting to/from standard library ``datetime``
------------------------------------------------

Each **whenever** class wraps a standard library :class:`~datetime.datetime` instance.
You can access it with the :attr:`~whenever.DateTime.py` attribute.
Conversely, you can create a type from a standard library datetime with the
:meth:`~whenever.DateTime.from_py` classmethod.

.. code-block:: python

   >>> from datetime import datetime, UTC
   >>> UTCDateTime.from_py(datetime(2023, 1, 1, tzinfo=UTC))
   UTCDateTime(2023-01-01 00:00:00Z)
   >>> ZonedDateTime(2023, 1, 1, tz="Europe/Amsterdam").py
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

.. note::

   :class:`~whenever.ZonedDateTime` and :class:`~whenever.LocalDateTime` do not (yet)
   implement ``strptime()`` methods, because they require disambiguation.
   If you'd like to parse into these types,
   use :meth:`NaiveDateTime.strptime() <whenever.NaiveDateTime.strptime>`
   to parse them, and then use the ``.from_naive()`` method to convert to the desired type:

   .. code-block:: python

      ZonedDateTime.from_naive(
          # This parsed datetime is ambiguous in the Europe/Amsterdam timezone
          NaiveDateTime.strptime("2023-10-29 02:30:00", "%Y-%m-%d %H:%M:%S"),
          disambiguate="earlier",
          tz="Europe/Amsterdam",
      )

.. admonition:: Future plans

   Python's builtin ``strptime`` has its limitations, so a more full-featured
   parsing API may be added in the future.


Canonical string format
-----------------------

Each type has a canonical textual format, which is used when converting to and
from strings. The canonical format is designed to be unambiguous, and to
preserve all information. This makes it ideal for storing datetimes in a
database, or inclusing in JSON.

Here are the canonical formats for each type:

+-----------------------------------+---------------------------------------------------------------------+
| Type                              | Canonical string format                                             |
+===================================+=====================================================================+
| :class:`~whenever.UTCDateTime`    | ``YYYY-MM-DDTHH:MM:SS(.ffffff)Z``                                   |
+-----------------------------------+---------------------------------------------------------------------+
| :class:`~whenever.OffsetDateTime` | ``YYYY-MM-DDTHH:MM:SS(.ffffff)±HH:MM(:SS(.ffffff))``                |
+-----------------------------------+---------------------------------------------------------------------+
| :class:`~whenever.ZonedDateTime`  | ``YYYY-MM-DDTHH:MM:SS(.ffffff)±HH:MM(:SS(.ffffff))[TIMEZONE NAME]`` |
+-----------------------------------+---------------------------------------------------------------------+
| :class:`~whenever.LocalDateTime`  | ``YYYY-MM-DDTHH:MM:SS(.ffffff)±HH:MM(:SS(.ffffff))``                |
+-----------------------------------+---------------------------------------------------------------------+
| :class:`~whenever.NaiveDateTime`  | ``YYYY-MM-DDTHH:MM:SS(.ffffff)``                                    |
+-----------------------------------+---------------------------------------------------------------------+

.. code-block:: python

   >>> UTCDateTime(2023, 1, 1, 0, 0).canonical_str()
   '2023-01-01T00:00:00Z'
   >>> ZonedDateTime.from_canonical_str('2022-10-24T19:00:00+02:00[Europe/Paris]')
   ZonedDateTime(2022-10-24 19:00:00+02:00[Europe/Paris])

.. seealso::

   The methods :meth:`~whenever.DateTime.canonical_str` and
   :meth:`~whenever.DateTime.from_canonical_str` can be used to convert to and
   from the canonical string format.
