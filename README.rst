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

Are you tired of crossing your fingers and hoping you didn't mix up
aware and naive datetimes?
Or that you were careful to always use UTC? Or that you didn't forget
to account for daylight savings time?

Most datetime libraries leave you vulnerable to these pitfalls:
They use a single class for all datetimes.
As a result, a type checker or IDE can't detect these mistakes,
and you end up discovering them at runtime — or worse, not at all.

**Whenever** gives you *distinct datetime types* you can't mix up.
They're fully typed, and avoid common pitfalls.
It builds on the good parts of the standard library,
and draws inspiration from battle-tested libraries in other languages.

Best of all, **whenever** is *boring*. It doesn't do anything fancy or magic.
It's just five dead-simple classes thinly wrapping the standard library.
There's no function over 10 lines long, and no dependencies.
The goal is your peace of mind.


Quickstart
----------

🚧 WORK IN PROGRESS 🚧

Whenever provides these datetime types:

.. code-block:: python

   from whenever import (
       UTCDateTime, OffsetDateTime, ZonedDateTime, LocalDateTime, NaiveDateTime
   )

and here's how you can use them:

+-----------------------+-----+--------+-------+-------+-------+
| Feature               |         Aware                | Naive |
+                       +-----+--------+-------+-------+       +
|                       | UTC | Offset | Zoned | Local |       |
+=======================+=====+========+=======+=======+=======+
| comparison            | ✅  |   ✅   |  ✅   |  ✅   |  ✅   |
+-----------------------+-----+--------+-------+-------+-------+
| difference            | ✅  |   ✅   |  ✅   |  ✅   |  ✅   |
+-----------------------+-----+--------+-------+-------+-------+
| add/subtract timedelta| ✅  |  ❌    |  ✅   |  ✅   |  ✅   |
+-----------------------+-----+--------+-------+-------+-------+
| unambiguous           | ✅  |  ✅    |  ❌   |  ❌   |  ✅   |
+-----------------------+-----+--------+-------+-------+-------+
| to RFC3339/ISO8601    | ✅  |  ✅    |  ❌   |  ❌   |  ❌   |
+-----------------------+-----+--------+-------+-------+-------+
| to/from timestamp     | ✅  |  ✅    |  ✅   |  ✅   |  ❌   |
+-----------------------+-----+--------+-------+-------+-------+
| now                   | ✅  |  ✅    |  ✅   |  ✅   |  ❌   |
+-----------------------+-----+--------+-------+-------+-------+

- **UTCDateTime** is always UTC: simple, fast, and unambiguous.
  It's great if you're storing when something happened (or will happen) regardless of location.

  *Example use cases:* The "created" timestamp of a blog post
  the scheduled start of a livestream.

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


- **NaiveDateTime** isn't aware of timezones or UTC offset.
  Use this if you need a datetime type detached from the complexities of the real world.

  *Example use case:* modeling time in a city simulation game.

  .. code-block:: python

     simulation_start = NaiveDateTime(1900, 1, 1, hour=0)


Why not...?
-----------

The standard library
~~~~~~~~~~~~~~~~~~~~

While it has all the functionality you need, it has many pitfalls:

- You can't be certain if ``datetime`` is naive or aware
  without running the code.
- ``datetime`` inherits from ``date``,
  `giving unexpected behaviour <https://github.com/python/typeshed/issues/4802>`_.
- adding/subtracting ``timedelta`` does not account for daylight savings time.
- naive datetimes implicitly function as local datetimes,
  which is often not what you want.
- ``fold`` defaults to 0 for ambiguous datetimes, instead of forcing you to be explicit.
- Some outdated methods still exist (although they are deprecated),
  such as ``datetime.utcnow()``

Pendulum
~~~~~~~~

Although fast and full-featured:

- aware/naive datetimes cannot be distinguished at type-checking time.
- its types inherit from the standard library ``datetime``,
  which brings along a lot of baggage and potential pitfalls.

DateType
~~~~~~~~

DateType fixes most of the naive/aware issues at type-checking time, but:

- it doesn't enforce correctness at runtime.
- it doesn't distinguish offset and zoned datetimes.
- it isn't able to *fully* type-check all `cases <https://github.com/glyph/DateType/blob/0ff07493bc2a13d6fafdba400e52ee919beeb093/tryit.py#L31>`_.

Heliclockter
~~~~~~~~~~~~

This library is a lot more explicit about the different types of datetimes,
however:

- it doesn't have a separate class for UTC and fixed-offset datetimes.
- its types inherit from the standard library ``datetime``,
  which brings along a lot of baggage and potential pitfalls.
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
