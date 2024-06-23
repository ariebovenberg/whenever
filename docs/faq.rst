❓ FAQ
======

.. _faq-why-utc:

Why does :class:`~whenever.UTCDateTime` exist?
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Since you can express a UTC time using an :class:`~whenever.OffsetDateTime`
with offset 0, you might wonder why :class:`~whenever.UTCDateTime` exists.
The reason it exists is precisely *because* it doesn't allow an offset.
By using :class:`~whenever.UTCDateTime`, you clearly express that you only 
care about when something happened, and don't care about the local time.

Consider the difference in intent between these two classes:

.. code-block:: python
   :emphasize-lines: 2

   class ChatMessage:
       sent: UTCDateTime
       content: str


.. code-block:: python
   :emphasize-lines: 2

   class ChatMessage:
       sent: OffsetDateTime
       content: str

In the first example, it's clear that you only care about the moment when
chat messages were sent.
In the second, you communicate that you also store the user's local time.
This intent is crucial for reasoning about the code,
and extending it correctly (e.g. with migrations, API endpoints, etc).

.. _faq-why-system-tz:

Why does :class:`~whenever.SystemDateTime` exist?
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

While it may not make sense for server-type applications to use the system timezone,
it's often useful for CLI tools or desktop applications.

Using :class:`~whenever.SystemDateTime` has the following advantages:

- In contrast to :class:`~whenever.OffsetDateTime`, 
  :class:`~whenever.SystemDateTime` knows about the system's timezone changes,
  enabling DST-safe arithmetic.
- In contrast to :class:`~whenever.ZonedDateTime`, 
  :class:`~whenever.SystemDateTime` doesn't require the system be configured with an IANA timezone.
  While this is often the case, it's not guaranteed.

Of course, feel free to work with :class:`~whenever.ZonedDateTime` if
you know the system's IANA timezone. You can use
the `tzlocal <https://pypi.org/project/tzlocal/>`_ library to help with this.

.. _faq-why-naive:

Why does :class:`~whenever.NaiveDateTime` exist?
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

In most cases, it's best to use aware datetimes. However, there are valid exceptions.
A common case is when you simply *don't know* the timezone 
of a datetime you're working with.
For example, when parsing a date from a user input, 
or when reading datetimes from a CSV file.
Expressing these as :class:`~whenever.NaiveDateTime` makes it clear that
the timezone is unknown.

Additionally, :class:`~whenever.NaiveDateTime` offers these advantages over the standard library's
counterpart:

- It is a different class, so any mix-up will be caught by your IDE or type-checker.
- It doesn't have a ``.now()`` method, removing a common source of mistakenly naive datetimes.
- Conversions to aware datetimes are explicit about assumptions being made:

  >>> party_invite = NaiveDateTime(2022, 1, 1, 12)
  >>> party_invite.assume_tz("Europe/Berlin")
  ZonedDateTime(2022-01-01 12:00:00+01:00[Europe/Berlin])

.. _faq-offset-arithmetic:

Why can't :class:`~whenever.OffsetDateTime` add or subtract durations?
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

``OffsetDateTime`` does not support addition or subtraction of time deltas.
This is a deliberate decision to prevent inadvertent DST-related bugs.

In practice, fixed-offset datetimes are commonly used to express a time at
which something occurs at a specific location.
But for many locations, the offset changes throughout the year
(due to DST or political decisions).
Allowing users to add/subtract from fixed-offset datetimes gives them the
impression that they are doing valid arithmetic,
while in actuality they are setting themselves up for DST-bugs
(which, again, are rampant).

An example:

>>> departure = OffsetDateTime(2024, 11, 3, hour=1, offset=-7)
>>> departure.add(hours=2)  # a 2 hour delay
OffsetDateTime(2024-11-03 03:00:00-07:00)

While this is correct in theory, it may not be what the user intended.
Does the ``-7:00`` offset correspond to Denver, or Phoenix?
It would be correct in Phoenix (which doesn't observe DST), but
in Denver, the correct result would
actually be ``02:00:00-06:00`` — an hour earlier on the clock!

For whenever, preventing a damaging pitfall weighs heavier than supporting
a more theoretical usage pattern.
This is consisent with other libraries that emphasize correctness, such as NodaTime.
If you do need to perform arithmetic on a fixed-offset datetime,
you should make the location explicit by converting it to a
:class:`~whenever.ZonedDateTime` first:

>>> departure.to_tz("America/Denver").add(hours=2)
ZonedDateTime(2024-11-03 02:00:00-06:00[America/Denver])
>>> departure.to_tz("America/Phoenix").add(hours=2)
ZonedDateTime(2024-11-03 03:00:00-07:00[America/Phoenix])
>>> # not recommended, but possible:
>>> departure.to_utc().add(hours=2).to_fixed_offset(departure.offset)
OffsetDateTime(2024-11-03 03:00:00-07:00)

.. note::

   ``OffsetDateTime`` *does* support calculating the difference between two datetimes,
   because this isn't affected by DST changes:

   >>> a = OffsetDateTime(2024, 11, 3, hour=1, offset=-7)
   >>> a - OffsetDateTime(2024, 11, 3, hour=3, offset=4)
   TimeDelta(09:00:00)

.. _faq-leap-seconds:

Are leap seconds supported?
~~~~~~~~~~~~~~~~~~~~~~~~~~~

Leap seconds are unsupported.
Taking leap seconds into account is a complex and niche feature,
which is not needed for the vast majority of applications.
This decision is consistent with other modern libraries
(e.g. NodaTime, Temporal) and standards (RFC 5545, Unix time) which
do not support leap seconds.

Nonetheless, these improvements are possible in the future:

- Allow parsing of leap seconds, e.g. ``23:59:60``.
- Allow representation of leap seconds (similar to rust Chrono)

.. _faq-why-not-dropin:

Why isn't it a drop-in replacement for the standard library?
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Fixing the issues with the standard library requires a different API.
Keeping the same API would mean that the same issues would remain.
Also, inheriting from the standard library would result in brittle code:
many popular libraries expect ``datetime`` *exactly*,
and `don't work <https://github.com/sdispater/pendulum/issues/289#issue-371964426>`_
with `subclasses <https://github.com/sdispater/pendulum/issues/131#issue-241088629>`_.

.. _faq-production-ready:

Is it production-ready?
~~~~~~~~~~~~~~~~~~~~~~~

The core functionality is complete and mostly stable.
The goal is to reach 1.0 soon, but the API may change until then.
Of course, it's still a relatively young project, so the stability relies
on you to try it out and report any issues!
