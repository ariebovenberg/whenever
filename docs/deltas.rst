.. _durations:

⏳ Deltas
=========

As we've seen :ref:`earlier <add-subtract-time>`, you can add and subtract
time units from datetimes:

>>> dt.add(hours=5, minutes=30)

However, sometimes you want to operate on these durations directly.
For example, you might want to reuse a particular duration,
or perform arithmetic on it.
For this, **whenever** provides an API
designed to help you avoid common pitfalls.
The type annotations and descriptive errors should guide you
to the correct usage.

Durations are created using the duration units provided.
Here is a quick demo:

>>> from whenever import years, months, days, hours, minutes
>>> # Precise units create a TimeDelta, supporting broad arithmetic
>>> movie_runtime = hours(2) + minutes(9)
TimeDelta(02:09:00)
>>> movie_runtime.in_minutes()
129.0
>>> movie_runtime / 1.2  # what if we watch it at 1.2x speed?
TimeDelta(01:47:30)
...
>>> # Calendar units create a DateDelta, with more limited arithmetic
>>> project_estimate = months(1) + days(10)
DateDelta(P1M10D)
>>> Date(2023, 1, 29) + project_estimate
Date(2023-03-10)
>>> project_estimate * 2  # make it pessimistic
DateDelta(P2M20D)
...
>>> # Mixing date and time units creates a generic DateTimeDelta
>>> project_estimate + movie_runtime
DateTimeDelta(P1M10DT2H9M)
...
>>> # API ensures common mistakes are caught early:
>>> project_estimate * 1.3             # Impossible arithmetic on calendar units
>>> project_estimate.in_hours()        # Resolving calendar units without context
>>> Date(2023, 1, 29) + movie_runtime  # Adding time to a date

Types of deltas
---------------

There are three duration types in **whenever**:

-  :class:`~whenever.TimeDelta`, created by precise units
   :func:`~whenever.hours`, :func:`~whenever.minutes`, :func:`~whenever.seconds`,
   and :func:`~whenever.microseconds`.
   Their duration is always the same and independent of the calendar.
   Arithmetic on time units is straightforward.
   It behaves similarly to the :class:`~datetime.timedelta`
   of the standard library.

-  :class:`~whenever.DateDelta`, created by the calendar units
   :func:`~whenever.years`, :func:`~whenever.months`, :func:`~whenever.weeks`,
   and :func:`~whenever.days`.
   They don't have a precise duration, as this depends on the context.
   For example, the number of days in a month varies, and a day may be
   longer or shorter than 24 hours due to Daylight Saving Time.
   This makes arithmetic on calendar units less intuitive.

-  :class:`~whenever.DateTimeDelta`, created when you mix
   time and calendar units.

This distinction determines which operations are supported:

+------------------------------+--------------------------+-----------------------+-------------------------+
| Feature                      | ``TimeDelta``            | ``DateDelta``         | ``DateTimeDelta``       |
+==============================+==========================+=======================+=========================+
| Add to datetimes             | .. centered::   See :ref:`here <arithmetic-dst>`                           |
+------------------------------+--------------------------+-----------------------+-------------------------+
| Add to ``Date``              | .. centered:: ❌         | .. centered:: ✅      | .. centered:: ❌        |
+------------------------------+--------------------------+-----------------------+-------------------------+
| division (÷)                 | .. centered:: ✅         | .. centered:: ❌      | .. centered:: ❌        |
+------------------------------+--------------------------+-----------------------+-------------------------+
| multiplication (×)           | .. centered:: ✅         | .. centered:: ⚠️ [1]_ | .. centered:: ⚠️  [1]_  |
+------------------------------+--------------------------+-----------------------+-------------------------+
| comparison (``>, >=, <, <=``)| .. centered:: ✅         | .. centered:: ❌      | .. centered:: ❌        |
+------------------------------+--------------------------+-----------------------+-------------------------+
| Commutative:                 |                          |                       |                         |
| ``dt + a + b == dt + b + a`` | .. centered:: ✅         | .. centered:: ❌      | .. centered:: ❌        |
+------------------------------+--------------------------+-----------------------+-------------------------+
| Reversible:                  |                          |                       |                         |
| ``(dt + a) - a == dt``       | .. centered:: ✅         | .. centered:: ❌      | .. centered:: ❌        |
+------------------------------+--------------------------+-----------------------+-------------------------+
| normalized                   | .. centered:: ✅         | .. centered:: ⚠️ [2]_ | .. centered:: ⚠️  [2]_  |
+------------------------------+--------------------------+-----------------------+-------------------------+

.. [1] Only by integers
.. [2] Years/months and weeks/days are normalized amongst each other,
       but not with other units. 

Multiplication
--------------

You can multiply time units by a number:

>>> 1.5 * hours(2)
TimeDelta(03:00:00)

Date units can only be multiplied by integers.
"1.3 months" isn't a well-defined concept, so it's not supported:

>>> months(3) * 2
DateDelta(P6M)

Division
--------

Only time units can be divided:

>>> hours(3) / 1.5
TimeDelta(02:00:00)

Date units can't be divided. "A year divided by 11.2", for example, can't be defined.

Commutativity
-------------

The result of adding two time durations is the same, regardless of what order you add them in:

>>> dt = Instant.from_utc(2020, 1, 29)
>>> dt + hours(2) + minutes(30)
Instant(2020-01-29 02:30:00Z)
>>> dt + minutes(30) + hours(2)  # same result

This is not the case for date units. The result of adding two date units depends on the order:

>>> d = Date(2020, 1, 29)
>>> d + months(1) + days(3)
Date(2021-03-03)
>>> d + days(3) + months(1)
Date(2021-03-01)

Reversibility
-------------

Adding a time duration and then subtracting it again gives you the original datetime:

>>> dt + hours(3) - hours(3) == dt
True

This is not the case for date units:

>>> jan30 = Date(2020, 1, 30)
>>> jan30 + months(1)
Date(2020-02-29)
>>> jan30 + months(1) - months(1)
Date(2020-01-29)

Comparison
----------

You can compare time durations:

>>> hours(3) > minutes(30)
True

This is not the case for date units:

>>> months(1) > days(30)  # no universal answer

Normalization
-------------

Time durations are always fully normalized: hours, minutes, seconds,
milliseconds, microseconds, and nanoseconds all roll over into each other:

>>> minutes(70)
TimeDelta(01:10:00)

Only some date units can be normalized: years and months are normalized amongst each other,
and weeks and days are normalized amongst each other.
1 year doesn't always correspond to a fixed number of days, but it does always correspond to 12 months.
One day also doesn't correspond to a fixed number of hours,
as this can change depending on Daylight Saving Time, for example.

>>> months(13)
DateDelta(P1Y1M)
>>> months(1) + weeks(4)
DateDelta(P1M28D)
>>> days(1) + hours(24)
DateTimeDelta(P1DT24H)

Equality
--------

Two time durations are equal if their sum of components is equal:

>>> hours(1) + minutes(30) == hours(2) - minutes(30)
True

Since date units are only partially normalized, date durations are only
equal if months/years and weeks/days are equal amongst each other:

>>> months(1) == days(31)
False  # a month will never equal a fixed number of days
>>> years(1) + weeks(1) == months(12) + days(7)
True  # a years is always 12 months, and a week is always 7 days

.. _iso8601-durations:

ISO 8601 format
---------------

The ISO 8601 standard defines formats for specifying durations,
the `most common <https://en.wikipedia.org/wiki/ISO_8601#Durations>`_ being:

.. code-block:: none

   ±PnYnMnDTnHnMnS

Where:

- ``P`` is the period designator, and ``T`` separates date and time components.
- ``nY`` is the number of years, ``nM`` is the number of months, etc.
- Only seconds may have a fractional part.


For example:

- ``P3Y4DT12H30M`` is 3 years, 4 days, 12 hours, and 30 minutes.
- ``-P2M5D`` is -2 months, and -5 days.
- ``P0D`` is zero.
- ``+PT5M4.25S`` is 5 minutes and 4.25 seconds.

All deltas can be converted to and from this format using the methods
:meth:`~whenever.DateTimeDelta.format_common_iso`
and :meth:`~whenever.DateTimeDelta.parse_common_iso`.

>>> hours(3).format_common_iso()
'PT3H'
>>> (-years(1) - months(3) - minutes(30.25)).format_common_iso()
'-P1Y3MT30M15S'
>>> DateDelta.parse_common_iso('-P2M')
DateDelta(-2M)
>>> DateTimeDelta.parse_common_iso('P3YT90M')
DateTimeDelta(P3YT1H30M)

.. attention::

   Full conformance to the ISO 8601 standard is not provided, because:

   - It allows for a lot of unnecessary flexibility
     (e.g. fractional components other than seconds)
   - There are different revisions with different rules
   - The full specification is not freely available

   Supporting a commonly used subset is more practical.
   This is also what established libraries such as java.time and Nodatime do.
