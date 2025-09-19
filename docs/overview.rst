.. _overview:

🌎 Overview
============

This page gives an overview of ``whenever``'s main features for working
with date and time.
For more details, see the :ref:`API reference <api>`.

Core types
----------

While the standard library has a single :class:`~datetime.datetime` type
for all use cases,
``whenever`` provides distinct types similar to other modern datetime libraries [2]_:

- :class:`~whenever.Instant`—the simplest way to unambiguously represent a point on the timeline,
  also known as **"exact time"**.
  This type is analogous to a UNIX timestamp or UTC.
- :class:`~whenever.PlainDateTime`—how humans represent time (e.g. *"January 23rd, 2023, 3:30pm"*),
  also known as **"local time"**.
  This type is analogous to an "naive" datetime in the standard library.
- :class:`~whenever.ZonedDateTime`—A combination of the two concepts above:
  an exact time paired with a local time at a specific location.
  This type is analogous to an "aware" standard library datetime with ``tzinfo`` set to a ``ZoneInfo`` instance.

The distinction between these types is crucial for avoiding common pitfalls
when working with dates and times.
Read on to find out when to use each type.

.. tip::

   If you prefer a video explanation, `here is an excellent explanation of these concepts <https://www.youtube.com/watch?v=saeKBuPewcU>`_.

:class:`~whenever.Instant`
~~~~~~~~~~~~~~~~~~~~~~~~~~

This is the simplest way to represent a moment on the timeline,
independent of human complexities like timezones or calendars.
An ``Instant`` maps 1:1 to UTC or a UNIX timestamp.
It's great for storing when something happened (or will happen)
regardless of location.

>>> livestream_starts = Instant.from_utc(2022, 10, 24, hour=17)
Instant("2022-10-24 17:00:00Z")
>>> Instant.now() > livestream_starts
True
>>> livestream_starts.add(hours=3).timestamp()
1666641600

The value of this type is in its simplicity. It's straightforward to compare,
add, and subtract. It's always clear what moment in time
you're referring to—without having to worry about timezones,
Daylight Saving Time (DST), or the calendar.

.. seealso::

   :ref:`Why does Instant exist? <faq-why-instant>`

:class:`~whenever.PlainDateTime`
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Humans typically represent time as a combination of date and time-of-day.
For example: *January 23rd, 2023, 3:30pm*.
While this information makes sense to people within a certain context,
it doesn't by itself refer to a moment on the timeline.
This is because this date and time-of-day occur at different moments
depending on whether you're in Australia or Mexico, for example.

Another limitation is that you can't account for Daylight Saving Time
if you only have a date and time-of-day without a timezone.
Therefore, it's not possible to add exact time units to "plain" datetimes.
This is because—strictly speaking—you don't know what the
local time will be in 3 hours:
perhaps the clock will be moved forward or back due to Daylight Saving Time.

>>> bus_departs = PlainDateTime(2020, 3, 14, hour=15)
PlainDateTime("2020-03-14 15:00:00")
# NOT possible:
>>> Instant.now() > bus_departs                 # comparison with exact time
>>> bus_departs.add(hours=3)                    # adding exact time units
# IS possible:
>>> PlainDateTime(2020, 3, 15) > bus_departs    # comparison with other plain datetimes
>>> bus_departs.add(hours=3, ignore_dst=True)   # explicitly ignore DST
>>> bus_departs.add(days=2)                     # calendar operations are OK

So how do you account for daylight saving time?
Or find the corresponding exact time for a date and time-of-day?
That's what the next type is for.

:class:`~whenever.ZonedDateTime`
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

This is a combination of an exact *and* a local time at a specific location,
with rules about Daylight Saving Time and other timezone changes.

>>> bedtime = ZonedDateTime(2024, 3, 9, 22, tz="America/New_York")
ZonedDateTime("2024-03-09 22:00:00-05:00[America/New_York]")
# accounts for the DST transition overnight:
>>> bedtime.add(hours=8)
ZonedDateTime("2024-03-10 07:00:00-04:00[America/New_York]")

A timezone defines a UTC offset for each point on the timeline.
As a result, any :class:`~whenever.Instant` can
be converted to a :class:`~whenever.ZonedDateTime`.
Converting from a :class:`~whenever.PlainDateTime`, however,
may be ambiguous,
because changes to the offset can result in local times
occuring twice or not at all.

>>> # Instant->Zoned is always straightforward
>>> livestream_starts.to_tz("America/New_York")
ZonedDateTime("2022-10-24 13:00:00-04:00[America/New_York]")
>>> # Local->Zoned may be ambiguous
>>> bus_departs.assume_tz("America/New_York")
ZonedDateTime("2020-03-14 15:00:00-04:00[America/New_York]")

.. seealso::

    Read about ambiguity in more detail :ref:`here <ambiguity>`.

:class:`~whenever.OffsetDateTime`
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. epigraph::

   In API design, if you've got two things that are even subtly different,
   it's worth having them as separate types—because you're representing the
   meaning of your data more accurately.

   -- Jon Skeet

Like :class:`~whenever.ZonedDateTime`, this type represents an exact time
*and* a local time. The difference is that :class:`~whenever.OffsetDateTime`
has a *fixed* offset from UTC rather than a timezone.
As a result, it doesn't know about Daylight Saving Time or other timezone changes.

Then why use it? Firstly, most datetime formats (e.g. ISO 8601 and RFC 2822) only have fixed offsets,
making :class:`~whenever.OffsetDateTime` ideal for representing datetimes in these formats.
Second, a :class:`~whenever.OffsetDateTime` is simpler—so long as you
don't need the ability to shift it. This makes :class:`~whenever.OffsetDateTime`
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

   - :ref:`Performing DST-safe arithmetic <arithmetic-dst>`

.. _summary:

Comparison of types
~~~~~~~~~~~~~~~~~~~

Here's a summary of the differences between the types:

+------------------------------+---------+---------+-------+---------+
|                              | Instant | OffsetDT|ZonedDT|PlainDT  |
+==============================+=========+=========+=======+=========+
| knows the **exact** time     |   ✅    | ✅      | ✅    |  ❌     |
+------------------------------+---------+---------+-------+---------+
| knows the **local** time     |  ❌     |  ✅     |  ✅   |  ✅     |
+------------------------------+---------+---------+-------+---------+
| knows about DST rules [6]_   |  ❌     |  ❌     |  ✅   |  ❌     |
+------------------------------+---------+---------+-------+---------+


Comparison and equality
-----------------------

All types support equality and comparison.
However, :class:`~whenever.PlainDateTime` instances are
never equal or comparable to the "exact" types.

Exact time
~~~~~~~~~~

For exact types (:class:`~whenever.Instant`, :class:`~whenever.OffsetDateTime`,
:class:`~whenever.ZonedDateTime`),
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
the :meth:`~whenever._ExactTime.exact_eq` method.

>>> d = OffsetDateTime(2023, 12, 28, 11, 30, offset=5)
>>> same = OffsetDateTime(2023, 12, 28, 11, 30, offset=5)
>>> same_moment = OffsetDateTime(2023, 12, 28, 12, 30, offset=6)
>>> d == same_moment
True
>>> d.exact_eq(same_moment)
False
>>> d.exact_eq(same)
True

Local time
~~~~~~~~~~

For :class:`~whenever.PlainDateTime`, equality is simply based on
whether the values are the same, since there is no concept of timezones or UTC offset:

>>> d = PlainDateTime(2023, 12, 28, 11, 30)
>>> same = PlainDateTime(2023, 12, 28, 11, 30)
>>> different = PlainDateTime(2023, 12, 28, 11, 31)
>>> d == same
True
>>> d == different
False

.. seealso::

   See the documentation of :meth:`__eq__ (exact) <whenever._ExactTime.__eq__>`
   and :meth:`PlainDateTime.__eq__ <whenever.PlainDateTime.__eq__>` for more details.


Strict equality
~~~~~~~~~~~~~~~

Local and exact types are never equal or comparable to each other.
However, to comply with the Python data model, the equality operator
won't prevent you from using ``==`` to compare them.
To prevent these mix-ups, use mypy's ``--strict-equality``
`flag <https://mypy.readthedocs.io/en/stable/command_line.html#cmdoption-mypy-strict-equality>`_.

>>> # These are never equal, but Python won't stop you from comparing them.
>>> # Mypy will catch this mix-up if you use enable --strict-equality flag.
>>> Instant.from_utc(2023, 12, 28) == PlainDateTime(2023, 12, 28)
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

    x == OffsetDateTime(2023, 12, 28, 11, offset=1).to_instant()

Or annotate with a union:

.. code-block:: python

    x: OffsetDateTime | Instant == OffsetDateTime(2023, 12, 28, 11, offset=1)


Conversion
----------

Between exact types
~~~~~~~~~~~~~~~~~~~

You can convert between exact types with the :meth:`~whenever._ExactAndLocalTime.to_instant`,
:meth:`~whenever._ExactTime.to_fixed_offset`, :meth:`~whenever._ExactTime.to_tz`,
and :meth:`~whenever._ExactTime.to_system_tz` methods. These methods return a new
instance of the appropriate type, representing the same moment in time.
This means the results will always compare equal to the original datetime.

>>> d = ZonedDateTime(2023, 12, 28, 11, 30, tz="Europe/Amsterdam")
>>> d.to_instant()  # The underlying moment in time
Instant("2023-12-28 10:30:00Z")
>>> d.to_fixed_offset(5)  # same moment with a +5:00 offset
OffsetDateTime("2023-12-28 15:30:00+05:00")
>>> d.to_tz("America/New_York")  # same moment in New York
ZonedDateTime("2023-12-28 05:30:00-05:00[America/New_York]")
>>> d.to_system_tz()  # same moment in the system timezone (e.g. Europe/Paris)
ZonedDateTime("2023-12-28 11:30:00+01:00[Europe/Paris]")
>>> d.to_fixed_offset(4) == d
True  # always the same moment in time

To and from "plain" datetime
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Conversion to a "plain" datetime is easy: calling
:meth:`~whenever._ExactAndLocalTime.to_plain` simply
retrieves the date and time part of the datetime, and discards the any timezone
or offset information.

>>> d = ZonedDateTime(2023, 12, 28, 11, 30, tz="Europe/Amsterdam")
>>> n = d.to_plain()
PlainDateTime("2023-12-28 11:30:00")

You can convert from plain datetimes with the :meth:`~whenever.PlainDateTime.assume_utc`,
:meth:`~whenever.PlainDateTime.assume_fixed_offset`, and
:meth:`~whenever.PlainDateTime.assume_tz`, and
:meth:`~whenever.PlainDateTime.assume_system_tz` methods.

>>> n = PlainDateTime(2023, 12, 28, 11, 30)
>>> n.assume_utc()
Instant("2023-12-28 11:30:00Z")
>>> n.assume_tz("Europe/Amsterdam")
ZonedDateTime("2023-12-28 11:30:00+01:00[Europe/Amsterdam]")

.. note::

   The seemingly inconsistent naming of the ``to_*`` and ``assume_*`` methods is intentional. The ``assume_*`` methods
   emphasize that the conversion is not self-evident, but based on assumptions
   of the developer.

.. _ambiguity:

Ambiguity in timezones
----------------------

.. note::

   The API for handling ambiguity is largely inspired by that of
   `Temporal <https://tc39.es/proposal-temporal/docs/ambiguity.html>`_,
   the redesigned date and time API for JavaScript.

In timezones, local clocks are often moved backwards and forwards
due to Daylight Saving Time (DST) or political decisions.
This makes it complicated to map a local time to a point on the timeline.
Two common situations arise:

- When the clock moves backwards, there is a period of time that repeats.
  For example, Sunday October 29th 2023 2:30am occurred twice in Paris.
  When you specify this time, you need to specify whether you want the earlier
  or later occurrence.
- When the clock moves forwards, a period of time is skipped.
  For example, Sunday March 26th 2023 2:30am didn't happen in Paris.
  When you specify this time, you need to specify how you want to handle this non-existent time.
  Common approaches are to extrapolate the time forward or backwards
  to 1:30am or 3:30am.

  .. note::

     You may wonder why skipped time is "extrapolated" like this,
     and not truncated. Why turn 2:30am into 3:30am and not cut
     it off at 1:59am when the gap occurs?

     The reason for the "extrapolation" approach is:

     * It fits the most likely reason the time is skipped: we forgot to adjust the clock, or adjusted it too early
     * This is how other datetime libraries do it (e.g. JavaScript (Temporal), C# (Nodatime), Java, Python itself)
     * It corresponds with the iCalendar (RFC5545) standard of handling gaps

     The figure in the Python docs `here <https://peps.python.org/pep-0495/#mind-the-gap>`_ also shows how this "extrapolation" makes sense graphically.

``Whenever`` allows you to customize how to handle these situations
using the ``disambiguate`` argument:

+------------------+-------------------------------------------------+
| ``disambiguate`` | Behavior in case of ambiguity                   |
+==================+=================================================+
| ``"raise"``      | Raise :exc:`~whenever.RepeatedTime`             |
|                  | or :exc:`~whenever.SkippedTime` exception.      |
+------------------+-------------------------------------------------+
| ``"earlier"``    | Choose the earlier of the two options           |
+------------------+-------------------------------------------------+
| ``"later"``      | Choose the later of the two options             |
+------------------+-------------------------------------------------+
| ``"compatible"`` | Choose "earlier" for backward transitions and   |
| (default)        | "later" for forward transitions. This matches   |
|                  | the behavior of other established libraries,    |
|                  | and the industry standard RFC 5545.             |
|                  | It corresponds to setting ``fold=0`` in the     |
|                  | standard library.                               |
+------------------+-------------------------------------------------+

.. code-block:: python

    >>> paris = "Europe/Paris"

    >>> # Not ambiguous: everything is fine
    >>> ZonedDateTime(2023, 1, 1, tz=paris)
    ZonedDateTime("2023-01-01 00:00:00+01:00[Europe/Paris]")

    >>> # 1:30am occurs twice. Use 'raise' to reject ambiguous times.
    >>> ZonedDateTime(2023, 10, 29, 2, 30, tz=paris, disambiguate="raise")
    Traceback (most recent call last):
      ...
    whenever.RepeatedTime: 2023-10-29 02:30:00 is repeated in timezone Europe/Paris

    >>> # Explicitly choose the earlier option
    >>> ZonedDateTime(2023, 10, 29, 2, 30, tz=paris, disambiguate="earlier")
    ZoneDateTime(2023-10-29 02:30:00+01:00[Europe/Paris])

    >>> # 2:30am doesn't exist on this date (clocks moved forward)
    >>> ZonedDateTime(2023, 3, 26, 2, 30, tz=paris, disambiguate="raise")
    Traceback (most recent call last):
      ...
    whenever.SkippedTime: 2023-03-26 02:30:00 is skipped in timezone Europe/Paris

    >>> # Default behavior is compatible with other libraries and standards
    >>> ZonedDateTime(2023, 3, 26, 2, 30, tz=paris)
    ZonedDateTime("2023-03-26 03:30:00+02:00[Europe/Paris]")

.. _arithmetic:

Arithmetic
----------

Datetimes support various arithmetic operations.

Difference
~~~~~~~~~~

You can get the duration between two datetimes or instants with the ``-`` operator or
the :meth:`~whenever._ExactTime.difference` method.
Exact and local types cannot be mixed, although exact types can be mixed with each other:

>>> # difference in exact time
>>> Instant.from_utc(2023, 12, 28, 11, 30) - ZonedDateTime(2023, 12, 28, tz="Europe/Amsterdam")
TimeDelta(12:30:00)
>>> # difference in local time
>>> PlainDateTime(2023, 12, 28, 11).difference(
...     PlainDateTime(2023, 12, 27, 11),
...     ignore_dst=True
... )
TimeDelta(24:00:00)

.. _add-subtract-time:

Units of time
~~~~~~~~~~~~~

You can add or subtract various units of time from a datetime instance.

>>> d = ZonedDateTime(2023, 12, 28, 11, 30, tz="Europe/Amsterdam")
>>> d.add(hours=5, minutes=30)
ZonedDateTime("2023-12-28 17:00:00+01:00[Europe/Amsterdam]")

The behavior arithmetic behavior is different for three categories of units:

1. Adding **years and months** may result in truncation of the date.
   For example, adding a month to August 31st results in September 31st,
   which isn't valid. In such cases, the date is truncated to the last day of the month.

   .. code-block:: python

      >>> d = PlainDateTime(2023, 8, 31, hour=12)
      >>> d.add(months=1)
      PlainDateTime("2023-09-30 12:00:00")

   .. note::

      In case of dealing with :class:`~whenever.ZonedDateTime`
      there is a rare case where the resulting date might put the datetime in the middle of a DST transition.
      For this reason, adding years or months to these types accepts the
      ``disambiguate`` argument. By default, it tries to keep the same UTC offset,
      and if that's not possible, it chooses the ``"compatible"`` option.

      .. code-block:: python

         >>> d = ZonedDateTime(2023, 9, 29, 2, 15, tz="Europe/Amsterdam")
         >>> d.add(months=1, disambiguate="raise")
         Traceback (most recent call last):
           ...
         whenever.RepeatedTime: 2023-10-29 02:15:00 is repeated in timezone 'Europe/Amsterdam'

2. Adding **days** only affects the calendar date.
   Adding a day to a datetime will not affect the local time of day.
   This is usually same as adding 24 hours, *except* during DST transitions!

   This behavior may seem strange at first, but it's the most intuitive
   when you consider that you'd expect postponing a meeting "to tomorrow"
   should still keep the same time of day, regardless of DST changes.
   For this reason, this is the behavior of the industry standard RFC 5545
   and other modern datetime libraries.

   .. code-block:: python

      >>> # on the eve of a DST transition
      >>> d = ZonedDateTime(2023, 3, 25, hour=12, tz="Europe/Amsterdam")
      >>> d.add(days=1)  # a day later, still 12 o'clock
      ZonedDateTime("2023-03-26 12:00:00+02:00[Europe/Amsterdam]")
      >>> d.add(hours=24)  # 24 hours later (we skipped an hour overnight!)
      ZonedDateTime("2023-03-26 13:00:00+02:00[Europe/Amsterdam]")

   .. note::

      As with months and years, adding days to a :class:`~whenever.ZonedDateTime`
      accepts the ``disambiguate`` argument,
      since the resulting date might put the datetime in a DST transition.

3. Adding **precise time units** (hours, minutes, seconds) never results
   in ambiguity. If an hour is skipped or repeated due to a DST transition,
   precise time units will account for this.

   .. code-block:: python

      >>> d = ZonedDateTime(2023, 3, 25, hour=12, tz="Europe/Amsterdam")
      >>> d.add(hours=24)  # we skipped an hour overnight!
      ZonedDateTime("2023-03-26 13:00:00+02:00[Europe/Amsterdam]")

.. seealso::

   Have a look at the documentation on :ref:`deltas <durations>` for more details
   on arithmetic operations, as well as more advanced features.

.. _arithmetic-dst:

DST-safety
~~~~~~~~~~

Date and time arithmetic can be tricky due to daylight saving time (DST)
and other timezone changes.
The API of the different classes is designed to avoid implicitly ignoring these.
The type annotations and descriptive error messages should guide you
to the correct usage.

- :class:`~whenever.Instant` has no calendar, so it doesn't support
  adding calendar units. Precise time units can be added without any complications.
- :class:`~whenever.OffsetDateTime` has a fixed offset, so it *cannot*
  account for DST and other timezone changes.
  For example, the result of adding 24 hours to ``2024-03-09 13:00:00-07:00``
  is different whether the offset corresponds to Denver or Phoenix.
  To perform DST-safe arithmetic, you should convert to a :class:`~whenever.ZonedDateTime` first.
  Or, if you don't know the timezone and accept potentially incorrect results
  during DST transitions, pass ``ignore_dst=True``.

  >>> d = OffsetDateTime(2024, 3, 9, 13, offset=-7)
  >>> d.add(hours=24)
  Traceback (most recent call last):
    ...
  ImplicitlyIgnoringDST: Adjusting a fixed offset datetime implicitly ignores DST [...]
  >>> d.to_tz("America/Denver").add(hours=24)
  ZonedDateTime("2024-03-10 14:00:00-06:00[America/Denver]")
  >>> d.add(hours=24, ignore_dst=True)  # NOT recommended
  OffsetDateTime("2024-03-10 13:00:00-07:00")

  .. attention::

     Even when working in a timezone without DST, you should still use
     :class:`~whenever.ZonedDateTime`. This is because political decisions
     in the future can also change the offset!

- :class:`~whenever.ZonedDateTime` accounts for DST and other timezone changes,
  thus adding precise time units is always correct.
  Adding calendar units is also possible, but may result in ambiguity in rare cases,
  if the resulting datetime is in the middle of a DST transition:

  >>> d = ZonedDateTime(2024, 10, 3, 1, 15, tz="America/Denver")
  ZonedDateTime("2024-10-03 01:15:00-06:00[America/Denver]")
  >>> d.add(months=1)
  ZonedDateTime("2024-11-03 01:15:00-06:00[America/Denver]")
  >>> d.add(months=1, disambiguate="raise")
  Traceback (most recent call last):
    ...
  whenever.RepeatedTime: 2024-11-03 01:15:00 is repeated in timezone 'America/Denver'

- :class:`~whenever.PlainDateTime` doesn't have a timezone,
  so it can't account for DST or other clock changes.
  Calendar units can be added without any complications,
  but, adding precise time units is only possible with explicit ``ignore_dst=True``,
  because it doesn't know about DST or other timezone changes:

  >>> d = PlainDateTime(2023, 10, 29, 1, 30)
  >>> d.add(hours=2)  # There could be a DST transition for all we know!
  Traceback (most recent call last):
    ...
  whenever.ImplicitlyIgnoringDST: Adjusting a plain datetime by time units
  ignores DST and other timezone changes. [...]
  >>> d.assume_tz("Europe/Amsterdam").add(hours=2)
  ZonedDateTime("2023-10-29 02:30:00+01:00[Europe/Amsterdam]")
  >>> d.add(hours=2, ignore_dst=True)  # NOT recommended
  PlainDateTime("2024-10-03 03:30:00")

.. attention::

    Even when dealing with a timezone without DST, you should still use
    :class:`~whenever.ZonedDateTime` for precise time arithmetic.
    This is because political decisions in the future can also change the offset!

Here is a summary of the arithmetic features for each type:

+-----------------------+---------+---------+---------+---------+
|                       | Instant | OffsetDT|ZonedDT  |LocalDT  |
+=======================+=========+=========+=========+=========+
| Difference            | ✅      |  ✅     |   ✅    |⚠️  [3]_ |
+-----------------------+---------+---------+---------+---------+
| add/subtract years,   | ❌      |⚠️  [3]_ |✅  [4]_ |    ✅   |
| months, days          |         |         |         |         |
+-----------------------+---------+---------+---------+---------+
| add/subtract hours,   | ✅      |⚠️  [3]_ |  ✅     |⚠️  [3]_ |
| minutes, seconds, ... |         |         |         |         |
+-----------------------+---------+---------+---------+---------+

.. [3] Only possible by passing ``ignore_dst=True`` to the method.
.. [4] The result by be ambiguous in rare cases. Accepts the ``disambiguate`` argument.


.. admonition:: Why even have ``ignore_dst``? Isn't it dangerous?

   While DST-safe arithmetic is certainly the way to go, there are cases where
   it's simply not possible due to lack of information.
   Because there's no way to to stop users from working around
   restrictions to get the result they want, ``whenever`` provides the
   ``ignore_dst`` option to at least make it explicit when this is happening.

Rounding
~~~~~~~~

.. note::

   The API for rounding is largely inspired by that of Temporal (JavaScript)

It's often useful to truncate or round a datetime to a specific unit.
For example, you might want to round a datetime to the nearest hour,
or truncate it into 15-minute intervals.

The :class:`~whenever._LocalTime.round` method allows you to do this:

.. code-block:: python

    >>> d = PlainDateTime(2023, 12, 28, 11, 32, 8)
    PlainDateTime("2023-12-28 11:32:08")
    >>> d.round("hour")
    PlainDateTime("2023-12-28 12:00:00")
    >>> d.round("minute", increment=15, mode="ceil")
    PlainDateTime("2023-12-28 11:45:00")

See the method documentation for more details on the available options.

Formatting and parsing
----------------------

``Whenever`` supports formatting and parsing standardized formats

.. _iso8601:

ISO 8601
~~~~~~~~

The `ISO 8601 <https://en.wikipedia.org/wiki/ISO_8601>`_ standard
is probably the format you're most familiar with.
What you may not know is that it's a very complex standard with many options.
Asking whether something "is proper ISO" is like asking whether
something "is proper English"—there are many dialects and variations
and people hold different opinions on what is "proper".

Like all datetime libraries, ``whenever`` has to make some choices about which
parts of the standard to support. ``whenever`` targets the most common
and widely-used subset of the standard, while avoiding the more obscure
and rarely-used parts, which are often the source of confusion and bugs.

``whenever``'s
:meth:`~whenever._BasicConversions.parse_iso` methods take
mostly `after Temporal <https://tc39.es/proposal-temporal/#sec-temporal-iso8601grammar>`_,
namely:

- Both "extended" (e.g. ``2023-12-28``) and "basic" (e.g. ``20231228``) formats are supported.
- Weekday and ordinal date formats are *not* supported: e.g. ``2023-W52-5`` or ``2023-365``.
- A space (``" "``) may be used instead of ``T`` to separate the date and time parts.
- The date, time, and offset parts may independently choose to use extended or basic formats,
  so long as they are themselves consistent. e.g. ``2023-12-28T113000+03`` is OK, but
  ``2023-1228T11:23`` is not.
- Characters may be lowercase or uppercase (e.g. ``2023-12-28T11:30:00Z`` is the same as ``2023-12-28t11:30:00z``).
- Only seconds may be fractional (e.g. ``11:30:00.123456789Z`` is OK but ``11:30.5`` is not).
- Seconds may be precise up to 9 digits (nanoseconds).
- Both ``.`` and ``,`` may be used as decimal separators
- The offset ``-00:00`` is allowed, and is equivalent to ``+00:00``
- Offsets may be specified up to second-level precision (e.g. ``2023-12-28T11:30:00+01:23:45``).
- A IANA timezone identifier may be included in square brackets after the offset,
  like ``2023-12-28T11:30:00+01[Europe/Paris]``.
  This is part of the recent RFC 9557 extension to ISO 8601.
- In the duration format, the ``W`` unit may be used alongside other calendar units
  (``Y``, ``M``, ``D``).

Below are the default string formats you get for calling each type's
:meth:`~whenever._BasicConversions.format_iso` method:

+-----------------------------------------+------------------------------------------------+
| Type                                    | Default string format                          |
+=========================================+================================================+
| :class:`~whenever.Instant`              | ``YYYY-MM-DDTHH:MM:SSZ``                       |
+-----------------------------------------+------------------------------------------------+
| :class:`~whenever.PlainDateTime`        | ``YYYY-MM-DDTHH:MM:SS``                        |
+-----------------------------------------+------------------------------------------------+
| :class:`~whenever.ZonedDateTime`        | ``YYYY-MM-DDTHH:MM:SS±HH:MM[IANA TZ ID]`` [1]_ |
+-----------------------------------------+------------------------------------------------+
| :class:`~whenever.OffsetDateTime`       | ``YYYY-MM-DDTHH:MM:SS±HH:MM``                  |
+-----------------------------------------+------------------------------------------------+

Where applicable, the outputs can be customized using the ``unit``, ``basic``, ``sep``,
and ``tz`` keyword arguments. See the method documentation for details.

Example usage:

>>> d = OffsetDateTime(2023, 12, 28, 11, 30, offset=+5)
>>> d.format_iso()
'2023-12-28T11:30:00+05:00'
>>> OffsetDateTime.parse_iso('2021-07-13T09:45:00-09:00')
OffsetDateTime("2021-07-13 09:45:00-09:00")

.. note::

   The ISO formats in ``whenever`` are designed so you can format and parse
   them without losing information.
   This makes it ideal for JSON serialization and other data interchange formats.

.. admonition:: Why not support the full ISO 8601 spec?

   The full ISO 8601 standard is not supported for several reasons:

   - It allows for a lot of rarely-used flexibility:
     e.g. fractional hours, week-based years, etc.
   - There are different versions of the standard with different rules
   - The full specification is not freely available

   This isn't a problem in practice since people referring to "ISO 8601"
   often mean the most common subset, which is what ``whenever`` supports.
   It's rare for libraries to support the full standard.

   If you do need to parse the full spectrum of ISO 8601, you can use
   a specialized library such as `dateutil.parser <https://dateutil.readthedocs.io/en/stable/parser.html>`_.

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
OffsetDateTime("2021-07-13 09:45:00-09:00")

Custom formats
~~~~~~~~~~~~~~

.. admonition:: Future plans

   Python's builtin ``strptime`` has its limitations, so a more full-featured
   parsing API may be added in the future.

For now, basic customized parsing functionality is implemented in the ``parse_strptime()`` methods
of :class:`~whenever.OffsetDateTime` and :class:`~whenever.PlainDateTime`.
As the name suggests, these methods are thin wrappers around the standard library
:meth:`~datetime.datetime.strptime` function.
The same `formatting rules <https://docs.python.org/3/library/datetime.html#format-codes>`_ apply.

>>> OffsetDateTime.parse_strptime("2023-01-01+05:00", "%Y-%m-%d%z")
OffsetDateTime("2023-01-01 00:00:00+05:00")
>>> PlainDateTime.parse_strptime("2023-01-01 15:00", "%Y-%m-%d %H:%M")
PlainDateTime("2023-01-01 15:00:00")

:class:`~whenever.ZonedDateTime` does not (yet)
implement ``parse_strptime()`` methods, because they require disambiguation.
If you'd like to parse into these types,
use :meth:`PlainDateTime.parse_strptime() <whenever.PlainDateTime.parse_strptime>`
to parse them, and then use the :meth:`~whenever.PlainDateTime.assume_utc`,
:meth:`~whenever.PlainDateTime.assume_fixed_offset`,
:meth:`~whenever.PlainDateTime.assume_tz`,
or :meth:`~whenever.PlainDateTime.assume_system_tz`
methods to convert them.
This makes it explicit what information is being assumed.

>>> d = PlainDateTime.parse_strptime("2023-10-29 02:30:00", "%Y-%m-%d %H:%M:%S")
>>> d.assume_tz("Europe/Amsterdam")
ZonedDateTime("2023-10-29 02:30:00+02:00[Europe/Amsterdam]")

Pydantic integration
~~~~~~~~~~~~~~~~~~~~

.. warning::

   Pydantic support is still in preview and may change in the future.

``Whenever`` types support basic serialization and deserialization
with `Pydantic <https://docs.pydantic.dev>`_. The behavior is identical to
the ``parse_iso()`` and ``format_iso()`` methods.

>>> from pydantic import BaseModel
>>> from whenever import ZonedDateTime, TimeDelta
...
>>> class Event(BaseModel):
...     start: ZonedDateTime
...     duration: TimeDelta
...
>>> event = Event(
...     start=ZonedDateTime(2023, 2, 23, hour=20, tz="Europe/Amsterdam"),
...     duration=TimeDelta(hours=2, minutes=30),
... )
>>> d = event.model_dump_json()
'{"start":"2023-02-23T20:00:00+01:00[Europe/Amsterdam]","duration":"PT2H30M"}'

.. note::

   Whenever's parsing is stricter then Pydantic's default ``datetime`` parsing
   behavior. More flexible parsing may be added in the future.


To and from the standard library
--------------------------------

Each ``whenever`` datetime class can be converted to a standard
library :class:`~datetime.datetime`
with the :meth:`~whenever._BasicConversions.py_datetime` method.
Conversely, you can create instances from a standard library datetime with the
:meth:`~whenever._BasicConversions.from_py_datetime` classmethod.

>>> from datetime import datetime, UTC
>>> Instant.from_py_datetime(datetime(2023, 1, 1, tzinfo=UTC))
Instant("2023-01-01 00:00:00Z")
>>> ZonedDateTime(2023, 1, 1, tz="Europe/Amsterdam").py_datetime()
datetime(2023, 1, 1, 0, 0, tzinfo=ZoneInfo('Europe/Amsterdam'))

.. note::

   - Converting to the standard library is not always lossless.
     Nanoseconds will be truncated to microseconds.
   - ``from_py_datetime`` also works for subclasses, so you can also ingest types
     from ``pendulum`` and ``arrow`` libraries.


Date and time components
------------------------

Aside from the datetimes themselves, ``whenever`` also provides
:class:`~whenever.Date` for calendar dates and :class:`~whenever.Time` for
representing times of day.

>>> from whenever import Date, Time
>>> Date(2023, 1, 1)
Date("2023-01-01")
>>> Time(12, 30)
Time(12:30:00)

These types can be converted to datetimes and vice versa:

>>> Date(2023, 1, 1).at(Time(12, 30))
PlainDateTime("2023-01-01 12:30:00")
>>> ZonedDateTime.now("Asia/Tokyo").date()
Date("2023-07-13")

Dates support arithmetic with months and years,
with similar semantics to modern datetime libraries:

>>> d = Date(2023, 1, 31)
>>> d.add(months=1)
Date("2023-02-28")
>>> d - Date(2022, 10, 15)
DateDelta("P3M16D")

There's also :class:`~whenever.YearMonth` and :class:`~whenever.MonthDay` for representing
year-month and month-day combinations, respectively.
These are useful for representing recurring events or birthdays.

See the :ref:`API reference <date-and-time-api>` for more details.

Testing
-------

Patching the current time
~~~~~~~~~~~~~~~~~~~~~~~~~

Sometimes you need to 'fake' the output of ``.now()`` functions, typically for testing.
``Whenever`` supports various ways to do this, depending on your needs:

1. With :class:`whenever.patch_current_time`. This patcher
   only affects ``whenever``, not the standard library or other libraries.
   See its documentation for more details.
2. With the `time-machine <https://github.com/adamchainz/time-machine>`_ package.
   Using ``time-machine`` *does* affect the standard library and other libraries,
   which can lead to unintended side effects.
   Note that ``time-machine`` doesn't support PyPy.

.. note::

   It's also possible to use the
   `freezegun <https://github.com/spulec/freezegun>`_ library,
   but it will *only work on the Pure-Python version* of ``whenever``.

.. tip::

   Instead of relying on patching, consider using dependency injection
   instead. This is less error-prone and more explicit.

   You can do this by adding ``now`` argument to your function,
   like this:

   .. code-block:: python

      def greet(name, now=Instant.now):
          current_time = now()
          # more code here...

      # in normal use, you don't notice the difference:
      greet('bob')

      # to test it, pass a custom function:
      greet('alice', now=lambda: Instant.from_utc(2023, 1, 1))


Patching the system timezone
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

For changing the system timezone in tests, set the `TZ` environment variable
and use the :func:`~whenever.reset_system_tz` helper function to update the timezone cache.
Do note that this function only affects *whenever*, and not the standard library's
behavior.

Below is an example of a testing helper that can be used with ``pytest``:

.. code-block:: python

   import os
   import pytest
   from contextlib import contextmanager
   from unittest.mock import patch
   from whenever import reset_system_tz

   @contextmanager
   def system_tz_ams():
       try:
           with patch.dict(os.environ, {"TZ": "Europe/Amsterdam"}):
               reset_system_tz()  # update the timezone cache
               yield
       finally:
           reset_system_tz()  # don't forget to set the old timezone back!

.. _systemtime:

The system timezone
-------------------

The system timezone is the timezone that your operating system is set to.
You can create datetimes in the system timezone by using the
:meth:`~whenever.PlainDateTime.assume_system_tz`
or :meth:`~whenever._ExactTime.to_system_tz` methods:

>>> from whenever import PlainDateTime, Instant
>>> plain = PlainDateTime(2020, 8, 15, hour=8)
>>> d = plain.assume_system_tz()
ZonedDateTime("2020-08-15 08:00:00-04:00[America/New_York]")
>>> Instant.now().to_system_tz()
ZonedDateTime("2023-12-28 11:30:00-05:00[America/New_York]")

When working with the timezone of the current system, there
are a few things to keep in mind.

System timezone changes
~~~~~~~~~~~~~~~~~~~~~~~

It's important to be aware that the system timezone can change.
``whenever`` caches the system timezone at time you access it first.
This ensures predictable and fast behavior.

In the rare case that you need to change the system timezone
while your program is running, you can use the
:meth:`~whenever.reset_system_tz` method to determine the system timezone again.
Existing datetimes will not be affected by this change,
but new datetimes will use the updated system timezone.

>>> # initialization where the system timezone is America/New_York
>>> plain = PlainDateTime(2020, 8, 15, hour=8)
>>> d = plain.assume_system_tz()
ZonedDateTime("2020-08-15 08:00:00-04:00[America/New_York]")
...
>>> # we change the system timezone to Amsterdam
>>> os.environ["TZ"] = "Europe/Amsterdam"
>>> whenever.reset_system_tz()
...
>>> d  # existing objects remain unchanged
ZonedDateTime("2020-08-15 08:00:00-04:00[America/New_York]")
>>> # new objects will use the new system timezone
>>> Instant.now().to_system_tz()
ZonedDateTime("2025-08-15 15:03:28+01:00[Europe/Amsterdam]")

Non-IANA system timezones
~~~~~~~~~~~~~~~~~~~~~~~~~

While most system timezones can be matched with a IANA timezone ID
(like ``Europe/Amsterdam``),
some systems use custom timezone definitions that don't (unambiguously)
map to a IANA timezone ID.
For example, some systems may set the ``TZ`` environment variable to a POSIX TZ
string like ``CET-1CEST,M3.5.0,M10.5.0/3``,
or specify a custom timezone file.

>>> os.environ["TZ"] = "CET-1CEST,M3.5.0,M10.5.0/3"
>>> whenever.reset_system_tz()

These type of timezone definitions can still account for Daylight Saving Time
(DST) and other timezone changes:

>>> d = plain.assume_system_tz()
ZonedDateTime("2024-06-04 12:00:00+02:00[<system timezone without ID>]")
>>> # Correct UTC offset after adding 5 months
>>> d.add(months=5)
ZonedDateTime("2024-11-04 12:00:00+01:00[<system timezone without ID>]")

However there are some limitations of such instances of :class:`~whenever.ZonedDateTime`:

1. Their ``tz`` attribute is ``None``
2. They cannot be pickled
3. Their ISO 8601 string representation does not include a IANA timezone ID
4. The result of ``py_datetime()`` will have a fixed offset, not a ``ZoneInfo`` object.

.. [1] The timezone ID is not part of the core ISO 8601 standard,
   but is part of the RFC 9557 extension.
   This format is commonly used by datetime libraries in other languages as well.

.. [2] java.time, Noda Time (C#), and partly Temporal (JavaScript)
   all use a similar datamodel.

.. [6] Daylight Saving Time isn't the only reason for UTC offset changes.
   Changes can also occur due to political decisions, or historical reasons.
