.. _advanced:

🔧 Advanced features
====================

This page covers the more advanced features of **whenever**.
Read the :ref:`overview <overview>` first if you haven't already.

.. _durations:

Durations
---------

As we've seen :ref:`earlier <add-subtract-time>`, durations can easily
be added to and subtracted from datetimes:

>>> dt.add(hours=5, minutes=30)

However, sometimes you want to operate on durations directly.
For example, you might want to reuse a duration,
add 5 hours to it, or double it, for example.
For this, **whenever** provides a dedicated API.
As with datetimes, it's designed to help you avoid common pitfalls.

Durations are created using the duration units provided by **whenever**.
Here is a quick demo:

>>> from whenever import years, months, days, hours, minutes
>>> # Precise time units create a TimeDelta
>>> movie_runtime = hours(2) + minutes(9)
>>> movie_runtime.in_minutes()
129.0
>>> movie_runtime / 1.2  # watch it at 1.2x speed
TimeDelta(01:47:30)
...
>>> # Calendar units create a Period
>>> project_estimate = months(1) + days(10)
>>> Date(2023, 1, 29) + project_estimate
Date(2023-03-10)
>>> project_estimate * 2  # a pessimistic estimate
Period(2M20D)
...
>>> # Mixing date and time units creates a generic Duration
>>> project_estimate + movie_runtime
Duration(P1M10DT2H9M)
...
>>> # Mistakes prevented by the API:
>>> project_estimate * 1.3             # Precise arithmetic on calendar units
>>> project_estimate.in_hours()        # Value of calendar units depend on context
>>> Date(2023, 1, 29) + movie_runtime  # Can't add time to a date

Types of durations
~~~~~~~~~~~~~~~~~~

There are three duration types in **whenever**:

-  :class:`~whenever.Period`, created by :func:`~whenever.years`,
   :func:`~whenever.months`, :func:`~whenever.weeks`, and :func:`~whenever.days`.
   Their exact duration varies depending on the context.
   For example, the number of days in a month varies, and a day may be
   longer or shorter than 24 hours due to Daylight Saving Time.
   This makes arithmetic on calendar units tricky.

-  :class:`~whenever.TimeDelta`, created by :func:`~whenever.hours`,
   :func:`~whenever.minutes`, :func:`~whenever.seconds`,
   and :func:`~whenever.microseconds`.
   Their duration is always the same.
   Arithmetic on time units is straightforward.

-  :class:`~whenever.Duration`, created when you have a mix
   of time and date units.

Features
~~~~~~~~

This distinction determines which operations are supported:

+------------------------------+-------------------+--------------------+--------------------+
| Feature                      | ``TimeDelta``     | ``Period``         | ``Duration``       |
+==============================+===================+====================+====================+
| Add to ``DateTime``          | .. centered:: ✅  | .. centered:: ✅   | .. centered:: ✅   |
+------------------------------+-------------------+--------------------+--------------------+
| Add to ``Date``              | .. centered:: ❌  | .. centered:: ✅   | .. centered:: ❌   |
+------------------------------+-------------------+--------------------+--------------------+
| multiplication (×)           | .. centered:: ✅  | ⚠️  only by        | ⚠️  only by        |
|                              |                   | ``int``            | ``int``            |
+------------------------------+-------------------+--------------------+--------------------+
| division (÷)                 | .. centered:: ✅  | .. centered:: ❌   | .. centered:: ❌   |
+------------------------------+-------------------+--------------------+--------------------+
| Commutative, i.e.            |                   |                    |                    |
| ``dt + a + b == dt + b + a`` | .. centered:: ✅  | .. centered:: ❌   | .. centered:: ❌   |
+------------------------------+-------------------+--------------------+--------------------+
| Reversible, i.e              |                   |                    |                    |
| ``(dt + a) - a == dt``       | .. centered:: ✅  | .. centered:: ❌   | .. centered:: ❌   |
+------------------------------+-------------------+--------------------+--------------------+
| comparison (``>, >=, <, <=``)| .. centered:: ✅  | .. centered:: ❌   | .. centered:: ❌   |
+------------------------------+-------------------+--------------------+--------------------+
| normalization                | .. centered:: ✅  | .. centered:: ❌   | ⚠️ only the time   |
|                              |                   |                    | part               |
+------------------------------+-------------------+--------------------+--------------------+
| equality based on            | total sum in      | individual         | equality of date   |
|                              | microseconds      | fields             | and time parts     |
+------------------------------+-------------------+--------------------+--------------------+

Multiplication
++++++++++++++

You can multiply time units by a number:

>>> 1.5 * hours(2)
TimeDelta(03:00:00)

Date units can only be multiplied by integers.
"1.3 months" isn't a well-defined concept, so it's not supported:

>>> months(3) * 2

Division
++++++++

Only time units can be divided:

>>> hours(3) / 1.5
TimeDelta(02:00:00)

Date units can't be divided. "A year divided by 11.2", for example, can't be defined.

Commutativity
+++++++++++++

The result of adding two time durations is the same, regardless of what order you add them in:

>>> dt = UTCDateTime(2020, 1, 29)
>>> dt + hours(2) + minutes(30)
UTCDateTime(2020-01-29 02:30:00Z)
>>> dt + minutes(30) + hours(2)  # same result

This is not the case for date units. The result of adding two date units depends on the order:

>>> dt + months(1) + days(3)
UTCDateTime(2021-03-03 00:00:00)
>>> dt + days(3) + months(1)
UTCDateTime(2021-03-01 00:00:00)

Reversibility
+++++++++++++

Adding a time duration and then subtracting it again gives you the original datetime:

>>> dt + hours(3) - hours(3) == dt
True

This is not the case for date units:

>>> jan30 = UTCDateTime(2020, 1, 30)
>>> jan30 + months(1)
UTCDateTime(2020-02-29 00:00:00)
>>> jan30 + months(1) - months(1)
UTCDateTime(2020-01-29 00:00:00)

Comparison
++++++++++

You can compare time durations:

>>> hours(3) > minutes(30)
True

This is not the case for date units:

>>> months(1) > days(30)  # no universal answer

Normalization
+++++++++++++

Time durations are always normalized:

>>> minutes(70)
TimeDelta(01:10:00)

Date units are not normalized:

>>> months(13)
DateDuration(P13M)

Equality
++++++++

Two time durations are equal if their sum of components is equal:

>>> hours(1) + minutes(30) == hours(2) - minutes(30)
True

Since date units aren't normalized, two date duration are only
equal if their individual components are equal:

>>> months(1) + days(30) == months(2) - days(1)
False


.. _localtime:

The local system timezone
-------------------------

The local timezone is the timezone of the system running the code.
It's often useful to deal with times in the local timezone, but it's also
important to be aware that the local timezone can change.

Instances have the fixed offset of the system timezone
at the time of initialization.
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
and calculate the new local time, simply call :meth:`~AwareDateTime.as_local`.

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
