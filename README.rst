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

**Foolproof datetimes for maintainable code**

Do you cross your fingers every time you work with datetimes,
hoping that you didn't mix naive and aware?
or that you diligently converted to UTC everywhere?
or that you avoided the :ref:`pitfalls of the standard library <pitfalls>`?
There's no way to be sure, until you run your code...

✨ Until now! ✨

**Whenever** is built from the ground up, explicitly designed to enforce correctness.
Mistakes become red squiggles in your IDE, instead of production outages.

Benefits:

- Fully typed classes with explicit semantics
- Built on top of the *good parts* of the standard library
- Removes footguns and pitfalls of the standard library
- No dependencies
- Minimal API surface. No frills or surprises.

Overview
--------

Whenever distinguishes these types of datetimes:

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

- **UTCDateTime** is always UTC: simple, fast, and unambiguous.
  It's great if you're storing when something happened (or will happen) regardless of location.

  .. code-block:: python

     py311_release_livestream = UTCDateTime(2022, 10, 24, hour=17)

  In >95% of cases, you should use this class over the others. The other
  classes are most often useful at the boundaries of your application.

- **OffsetDateTime** defines a local time with its UTC offset.
  This is great if you're storing when something happened at a local time.

  .. code-block:: python

     from whenever import hours  # alias for timedelta(hours=...)

     # 9:00 in Salt Lake City, with the UTC offset at the time
     pycon23_started = OffsetDateTime(2023, 4, 21, hour=9, offset=hours(-6))

  It's less suitable for *future* events,
  because the UTC offset may change (e.g. due to daylight savings time).
  For this reason, you cannot add/subtract a ``timedelta``
  — the offset may have changed!

- **ZonedDateTime** accounts for the variable UTC offset of timezones,
  and is great for representing localized times in the past and future.
  Note that when the clock is set backwards, times occur twice.
  Use ``disambiguate`` to resolve these situations.

  .. code-block:: python

     # always at 11:00 in London, regardless of the offset
     changing_the_guard = ZonedDateTime(2024, 12, 8, hour=11, zone="Europe/London")

     # Explicitly resolve ambiguities when clocks are set backwards.
     # Default is "raise", which raises an exception
     night_shift = ZonedDateTime(2023, 10, 29, 1, 15, zone="Europe/London", disambiguate="later")

- **LocalDateTime** is a datetime in the system local timezone.
  This type is great for representing times related to the user's system.

  .. code-block:: python

     print(f"Your timer will go off at {LocalDateTime.now() + hours(1)}.")


- **NaiveDateTime** has no timezone or UTC offset.
  Use this if you need a datetime type detached from the complexities of the real world.

  .. code-block:: python

     city_simulation_start = NaiveDateTime(1900, 1, 1, hour=0)

.. _pitfalls:

The pitfalls of ``datetime``
----------------------------

Here are some of the issues with the standard library:

1. **Can't statically enforce aware datetimes**. You can only
   annotate with ``datetime``, which doesn't distinguish between naive and aware.

   .. code-block:: python

       # 🧨 No easy way to enforce that it's aware, you only know at runtime
       def schedule_livestream(d: datetime) -> None: ...

2. **Adding/subtracting timedelta doesn't account for DST**.
   You may think using timezoned datetimes solves this, but it doesn't!

   .. code-block:: python

      # on the eve of changing the clock forward
      bedtime = datetime(2023, 3, 26, hour=22, tzinfo=ZoneInfo("Europe/Amsterdam"))
      # 🧨 6:00, but should be 7:00 due to DST
      bedtime + timedelta(hours=8)

3. **The meaning of naive datetimes is inconsistent**.

   .. code-block:: python

      d = datetime(1970, 1, 1, 0)  # a naive datetime

      # ⚠️ Treated as a local datetime here...
      d.timestamp()
      d.astimezone(UTC)

      # 🧨 ...but assumed UTC here.
      d.utctimetuple()
      email.utils.format_datetime(d)
      datetime.utcnow()

4. **You aren't prevented from creating non-existent datetimes**,
   which creates subtle havoc once you perform basic operations.

   .. code-block:: python

      # ⚠️ No error that the datetime doesn't exist due to DST (clock set forward)
      d = datetime(2023, 3, 26, hour=2, minute=30, tzinfo=ZoneInfo("Europe/Amsterdam"))

      # 🧨 No UTC equivalent exists, so it just makes one up
      assert d.astimezone(UTC) == d  # False???

5. **In the face of ambiguity, it guesses**.
   When a datetime occurs twice (due to the clock being set backwards),
   the ``fold`` attribute resolves the ambiguity.
   However, it silently defaults to 0, negating the explicitness of the attribute.

   .. code-block:: python

      # 🧨 Code silently assumes you mean the first occurrence
      d = datetime(2023, 10, 29, 2, 30, tzinfo=ZoneInfo("Europe/Amsterdam"))

6. **Equality between ambiguous datetimes is always False**,
   even while the whole purpose of ``fold`` is to disambiguate them.

   .. code-block:: python

      # We carefully disembiguate a DST-ambiguous datetime with fold=1...
      x = datetime(2023, 10, 29, 2, 30, tzinfo=ZoneInfo("Europe/Amsterdam"), fold=1)

      # 🧨 But nonetheless comparisons with other timezones are *always* False
      y = d.astimezone(UTC)
      assert x == y  # False, even though they're the same time!

7. **Equality behaves differently** within the same timezone
   `than between different timezones <https://blog.ganssle.io/articles/2018/02/a-curious-case-datetimes.html>`_.

   .. code-block:: python

      # 🧨 In the same timezone, fold is ignored...
      before_dst = datetime(2023, 10, 29, 2, 30, tzinfo=ZoneInfo("Europe/Amsterdam"), fold=0)
      after_dst = before_dst_transition.replace(fold=1)
      before_dst == after_dst  # True -- even though they are one hour apart!

      # ⁉️ ...but between different timezones, it *is* accounted for!
      after_dst = after_dst.astimezone(ZoneInfo("Europe/Paris"))
      before_dst == after_dst  # False -- even though Paris has same DST behavior as Amsterdam!

8. **Datetime inherits from date**, which leads to unexpected behavior.
   This is widely considered a `design <https://discuss.python.org/t/renaming-datetime-datetime-to-datetime-datetime/26279/2>`_ `flaw <https://github.com/python/typeshed/issues/4802>`_ in the standard library.

   .. code-block:: python

      # 🧨 Breaks when you pass in a datetime, even though it's a date subclass!
      def is_future(dt: date) -> bool:
          return dt > date.today()

      # 🧨 Doesn't make sense
      datetime.today()

Why not...?
-----------

Pendulum
~~~~~~~~

Pendulum is full-featured datetime library, but it's
hamstrung by the decision to inherit from the standard library ``datetime``.
From the issues mentioned above, it only addresses #2 (DST-aware addition/subtraction).
All other pitfalls are still present.

python-dateutil
~~~~~~~~~~~~~~~

Dateutil attempts to solve some of the issues with the standard library.
However, it only *adds* functionality to work around the issues,
instead of *removing* the pitfalls themselves.
It only solves issues if you carefully use the right functions,
which isn't easy to do.

pytz
~~~~

Pytz brought the IANA timezone database to Python,
before ``zoneinfo`` was added to the standard library.
Now that ``zoneinfo`` is available from Python 3.9 onwards,
and backported to Python 3.6+, there's no reason to use pytz anymore.
What's worse, pytz introduces `footguns of its own <https://blog.ganssle.io/articles/2018/03/pytz-fastest-footgun.html>`_.

Arrow
~~~~~

Pendulum did a good write-up of `the issues with Arrow <https://pendulum.eustace.io/faq/>`_.
It doesn't seem to address any of the above mentioned issues with the standard library.

Maya
~~~~

By enforcing UTC, Maya bypasses a lot of issues with the standard library.
To do so, it sacrifices the ability to represent offset, zoned, and local datetimes.
So in order to perform any timezone-aware operations, you need to convert
to the standard library ``datetime`` first, which reintroduces the issues.

Also, it appears to be unmaintained.

udatetime
~~~~~~~~~

udatetime focusses on fast RFC 3339 parsing and formatting,
and leaves other concerns by the wayside.

Also, it appears to be unmaintained, and doesn't support Windows.

DateType
~~~~~~~~

DateType mostly fixes issue #1 (statically enforce aware datetimes),
but doesn't address the other issues. Additionally,
it isn't able to *fully* type-check `all cases <https://github.com/glyph/DateType/blob/0ff07493bc2a13d6fafdba400e52ee919beeb093/tryit.py#L31>`_.

Heliclockter
~~~~~~~~~~~~

This library is a lot more explicit about the different types of datetimes,
solving issue #1 (statically enforce aware datetimes).
However, it doesn't address the other issues.

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

Contributing
------------

Contributions are welcome! Please open an issue or pull request.

An example of setting up things and running the tests:

.. code-block:: bash

   poetry install
   pytest

⚠️ **Note**: The tests don't run on Windows yet. This is because
the tests use unix-specific features to set the timezone for the current process.
It can be made to work on Windows too, but I haven't gotten around to it yet.
