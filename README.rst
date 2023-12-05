⏰ Whenever
===========

.. image:: https://img.shields.io/pypi/v/whenever.svg?style=flat-square&color=blue
   :target: https://pypi.python.org/pypi/whenever

.. image:: https://img.shields.io/pypi/pyversions/whenever.svg?style=flat-square
   :target: https://pypi.python.org/pypi/whenever

.. image:: https://img.shields.io/pypi/l/whenever.svg?style=flat-square&color=blue
   :target: https://pypi.python.org/pypi/whenever

.. image:: https://img.shields.io/badge/mypy-strict-forestgreen?style=flat-square
   :target: https://mypy.readthedocs.io/en/stable/command_line.html#cmdoption-mypy-strict

.. image:: https://img.shields.io/badge/coverage-100%25-forestgreen?style=flat-square
   :target: https://github.com/ariebovenberg/whenever

.. image::  https://img.shields.io/github/actions/workflow/status/ariebovenberg/whenever/tests.yml?branch=main&style=flat-square
   :target: https://github.com/ariebovenberg/whenever

.. image:: https://img.shields.io/readthedocs/whenever.svg?style=flat-square
   :target: http://whenever.readthedocs.io/

**Type-safe datetimes for Python**

Five simple classes on top of the standard library to help you write bug-free code.

*Currently a work in progress. Leave a ⭐️ if you're interested how this develops.*

Why?
----

It's no secret that working with datetimes in Python has many pitfalls.
While advice like "always convert to UTC" or "avoid naive datetimes" is a good start,
it's useless if you can't actually enforce it.
In any non-trivial project, you end up crossing your fingers
and hoping you (and your teammates) didn't overlook anything.

As type checkers become more prevalent, the expectation is that
we can catch bugs like this before they happen.
But because most datetime libraries use a single
class for naive, UTC, and zoned times, you can't be sure until runtime.

**Whenever** gives you *distinct datetime types* with explicit semantics.
They're straightforward, fully typed, and ruthlessly unambiguous.
They're built on the good parts of the standard library,
and draw inspiration from battle-tested libraries in other languages.

Best of all, **whenever** is *boring*. It doesn't do anything fancy or magic.
It's just five dead-simple classes thinly wrapping the standard library.
There's only one function over 10 lines long, and no dependencies.
The goal isn't to be feature-rich, but to give you peace of mind.

Quickstart
----------

These are the classes you can import:

.. code-block:: python

   from whenever import (
       UTCDateTime, OffsetDateTime, ZonedDateTime, LocalDateTime, PlainDateTime
   )

and here's how you can use them:

+-----------------------+-----+--------+-------+-------+-------+
| Feature               | UTC | Offset | Zoned | Local | Plain |
+=======================+=====+========+=======+=======+=======+
| comparison            | ✅  |  ✅    |  ✅   |  ✅   |  ✅   |
+-----------------------+-----+--------+-------+-------+-------+
| difference            | ✅  |  ✅    |  ✅   |  ✅   |  ✅   |
+-----------------------+-----+--------+-------+-------+-------+
| add/subtract timedelta| ✅  |  ❌    |  ✅   |  ✅   |  ✅   |
+-----------------------+-----+--------+-------+-------+-------+
| no jumps back/forward | ✅  |  ✅    |  ❌   |  ❌   |  ✅   |
+-----------------------+-----+--------+-------+-------+-------+
| to RFC3339/ISO8601    | ✅  |  ✅    |  ❌   |  ❌   |  ❌   |
+-----------------------+-----+--------+-------+-------+-------+
| to/from timestamp     | ✅  |  ✅    |  ✅   |  ✅   |  ❌   |
+-----------------------+-----+--------+-------+-------+-------+
| now                   | ✅  |  ✅    |  ✅   |  ✅   |  ❌   |
+-----------------------+-----+--------+-------+-------+-------+

- **UTCDateTime** is always UTC: simple, fast, and unambiguous.
  It's great if you're storing when something happened (or will happen) regardless of location.

  *Example use cases:* The "created" timestamp of a blog post,
  or the scheduled start of a livestream.

  .. code-block:: python

     py311_release_livestream = UTCDateTime(2022, 10, 24, hour=17)

- **OffsetDateTime** defines a local time using a UTC offset.
  This is great if you're storing when something happened at a local time.
  It's less suitable for *future* events though,
  because the UTC offset may change (e.g. due to daylight savings time).
  For this reason, you cannot add/subtract a ``timedelta``
  — the offset may have changed!

  *Example use case:* Time at which a local event occurred.

  .. code-block:: python

     from whenever import hours  # alias for timedelta(hours=...)

     # 9:00 in Salt Lake City, with the UTC offset at the time
     pycon23_started = OffsetDateTime(2023, 4, 21, hour=9, offset=hours(-6))

- **ZonedDateTime** accounts for timezones and their variable UTC offset.
  When the clock is set backwards, times occurs twice:
  a ``fold`` attribute is required to explicitly `resolve these ambiguities <https://docs.python.org/3/library/datetime.html#datetime.datetime.fold>`_.

  *Example use case:* The time of an appointment at a specific location.

  .. code-block:: python

     from zoneinfo import ZoneInfo  # timezones from the standard library 🎉
     london = ZoneInfo("Europe/London")

     # always at 11:00 in London, regardless of the offset
     changing_the_guard = ZonedDateTime(2024, 12, 8, hour=11, tz=london, fold=0)

     # With `expect_unambiguous()` you can omit `fold`,
     # but you'll get a ValueError in ambiguous cases.
     changing_the_guard = ZonedDatetime.expect_unambiguous(2024, 12, 8, hour=11, tz=london)

- **LocalDateTime** is a datetime in the system local timezone.
  This type is great for representing a time on the current system.

  *Example use case:* An alarm clock app which runs on the user's system.

  .. code-block:: python

     print(f"Your timer will go off at {LocalDateTime.now() + hours(1)}.")


- **PlainDateTime** isn't aware of timezones or UTC offset.
  Use this if you need a datetime type detached from the complexities of the real world.

  *Example use case:* modeling time in a city simulation game.

  .. code-block:: python

     simulation_start = PlainDateTime(1900, 1, 1, hour=0)


What are the standard library's pitfalls?
-----------------------------------------

Here are some of the issues with the standard library, 
that you avoid by using **whenever**:

- **Can't statically enforce aware datetimes**. In the standard library, 
  you're left hoping that people read the docstring and pass in aware datetimes.
  With **whenever**, the code is self-documenting and statically checked.

  .. code-block:: python

      # 🧨 No foolproof way to enforce that it's aware
      def start_livestream(d: datetime) -> None:
          """...please pass in a UTC datetime..."""

- **Adding/subtracting timedelta doesn't account for DST**.
  You may think using timezoned datetimes solves this, but it doesn't!

  .. code-block:: python

     # on the eve of changing the clock forward
     bedtime = datetime(2023, 3, 26, hour=22, tzinfo=ZoneInfo("Europe/Amsterdam"))
     # 🧨 6:00, but should be 7:00 due to DST
     bedtime + timedelta(hours=8)

- **The meaning of naive datetimes is inconsistent**.

  .. code-block:: python

     d = datetime(1970, 1, 1, 0)  # a naive datetime

     # ⚠️ Treated as a local datetime here...
     d.timestamp()
     d.astimezone(UTC)

     # 🧨 ...but assumed UTC here.
     d.utctimetuple()
     email.utils.format_datetime(d)
     datetime.utcnow()

- **You aren't prevented from creating non-existent datetimes**,
  which creates subtle havoc once you perform basic operations.

  .. code-block:: python

     # ⚠️ No error that the datetime doesn't exist due to DST (clock set forward)
     d = datetime(2023, 3, 26, hour=2, minute=30, tzinfo=ZoneInfo("Europe/Amsterdam"))

     # 🧨 No UTC equivalent exists, so it just makes one up
     assert d.astimezone(UTC) == d  # False???

- **In the face of ambiguity, it guesses**.
  When a datetime occurs twice (due to the clock being set backwards),
  the ``fold`` attribute resolves the ambiguity.
  However, it defaults to 0, negating much of its value.

  .. code-block:: python

     # 🧨 Code silently assumes you mean the first occurrence
     d = datetime(2023, 10, 29, 2, 30, tzinfo=ZoneInfo("Europe/Amsterdam"))

- **Equality between ambiguous datetimes is always False**,
  even while the whole purpose of ``fold`` is to disambiguate them.

  .. code-block:: python

     # We carefully disembiguate a DST-ambiguous datetime with fold=1...
     x = datetime(2023, 10, 29, 2, 30, tzinfo=ZoneInfo("Europe/Amsterdam"), fold=1)

     # 🧨 But nonetheless comparisons with other timezones are *always* False
     y = d.astimezone(UTC)
     assert x == y  # False???

- **Timezone-aware equality behaves differently** within the same timezone 
  `than between different timezones <https://blog.ganssle.io/articles/2018/02/a-curious-case-datetimes.html>`_.

  .. code-block:: python

     # 🧨 In the same timezone, fold is ignored...
     before_dst = datetime(2023, 10, 29, 2, 30, tzinfo=ZoneInfo("Europe/Amsterdam"), fold=0)
     after_dst = before_dst_transition.replace(fold=1)
     before_dst == after_dst  # True -- even though one hour apart

     # ⁉️ ...but between different timezones, it's accounted for!
     after_dst = after_dst.astimezone(ZoneInfo("Europe/Paris"))
     before_dst == after_dst  # False -- even though Paris has same DST behavior as Amsterdam

- **Datetime inherits from date**. This is a design flaw in the standard library
  that leads to `unexpected behaviour <https://github.com/python/typeshed/issues/4802>`_.

  .. code-block:: python

     # 🧨 Breaks when you pass in a datetime, even though it's a date subclass!
     def is_in_future(dt: date) -> bool:
         return dt > date.today()

     # 🧨 Doesn't make sense (same as datetime.now)
     datetime.today()

Why not...?
-----------

python-dateutil
~~~~~~~~~~~~~~~

Dateutil attempts to solve some of the issues with the standard library,
but it still uses the standard ``datetime`` class.
It offers you functions to work around the issues,
but it doesn't remove any of the 'footguns' from the standard library,
leaving you almost just as vulnerable to mistakes.

pytz
~~~~

Pytz brought the IANA timezone database to Python,
before ``zoneinfo`` was added to the standard library.
Now that ``zoneinfo`` is available from Python 3.9 onwards,
and backported to Python 3.6+, there's no reason to use pytz anymore.
What's worse, pytz introduces `footguns of its own <https://blog.ganssle.io/articles/2018/03/pytz-fastest-footgun.html>`_.

Pendulum
~~~~~~~~

Although fast and full-featured, it critically inherits from the standard library ``datetime``,
which brings along a lot of the above mentioned baggage and pitfalls.
Additionally, having been developed before Python 3.9,
it doesn't leverage the standard library's ``zoneinfo`` module.

Arrow
~~~~~

Pendulum did a good write-up of `the issues with Arrow <https://pendulum.eustace.io/faq/>`_.
In addition to the issues mentioned there, Arrow also inherits from the standard library ``datetime``.

DateType
~~~~~~~~

DateType fixes most of the naive/aware issues at type-checking time, but:

- it doesn't enforce correctness at runtime.
- it doesn't distinguish offset and zoned datetimes.
- it still keeps the quirks of the standard library regarding timezones, equality, etc.
- it isn't able to *fully* type-check `all cases <https://github.com/glyph/DateType/blob/0ff07493bc2a13d6fafdba400e52ee919beeb093/tryit.py#L31>`_.

Heliclockter
~~~~~~~~~~~~

This library is a lot more explicit about the different types of datetimes,
however:

- it doesn't have a separate class for UTC and fixed-offset datetimes.
- its types inherit from the standard library ``datetime``,
  which brings along its baggage and pitfalls.
- No enorcement on resolving ambiguous datetimes.

Versioning and compatibility policy
-----------------------------------

**Whenever** follows semantic versioning.
Until the 1.0 version, the API may change with minor releases.
Breaking changes will be announced in the changelog.
Since the API is fully typed, your typechecker and/or IDE
will help you adjust to any API changes.

Acknowledgements
----------------

This project is inspired by the following projects. Check them out!

- `DateType <https://github.com/glyph/DateType/tree/trunk>`_
- `Pendulum <https://pendulum.eustace.io/>`_
- `Noda Time <https://nodatime.org/>`_
- `Chrono <https://docs.rs/chrono/latest/chrono/>`_

Development
-----------

An example of setting up things and running the tests:

.. code-block:: bash

   poetry install
   pytest
