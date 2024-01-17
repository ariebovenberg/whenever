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

**Foolproof datetimes for maintainable Python code**

Do you cross your fingers every time you work with datetimes,
hoping that you didn't mix naive and aware?
or that you converted to UTC everywhere?
or that you avoided the `many pitfalls of the standard library`_?
There's no way to be sure, until you run your code...

✨ Until now! ✨

**Whenever** is a datetime library designed from the ground up to enforce correctness.
Mistakes become red squiggles in your IDE, instead of production outages.

Benefits
--------

- Distinct classes with well-defined behavior
- Fixes timezone quirks that even `pendulum`_ doesn't address
- Enforce correctness without runtime checks
- Built on the standard library, but eliminates its pitfalls
- Based on familiar concepts from other languages. Doesn't reinvent the wheel.
- Simple and obvious. No frills or surprises.
- No dependencies

.. _overview:

Quick overview
--------------

Whenever distinguishes these classes:

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


``NaiveDateTime``
~~~~~~~~~~~~~~~~~

This type is detached from any timezone information.
Use this if you're only interested in what appears on a clock,
or if you absolutely don't need to account for the complexities of the real world.

.. code-block:: python

    clock_tower = NaiveDateTime(1955, 11, 12, hour=10, minute=4)
    city_simulation_start = NaiveDateTime(1900, 1, 1, hour=0)

.. _many pitfalls of the standard library:

The problems with ``datetime``
------------------------------

Since its adoption is 2003, the datetime library has accumulated
a lot of cruft and pitfalls. Below is an overview:

Conflicting ideas in one class
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Naive and aware datetimes mix like oil and water,
but they're both represented by the same class.
Because you can only annotate ``datetime``,
you don't know if your code breaks until you run it.

.. code-block:: python

    # 🧨 Naive or aware? no way to tell until you run it...
    def set_alarm(d: datetime) -> None: ...

Operators ignore DST
~~~~~~~~~~~~~~~~~~~~

You might think that the whole purpose of aware datetimes is to account for
Daylight Saving Time (DST). But surprisingly, basic operations don't do that.

.. code-block:: python

    # On the eve of moving the clock forward 1 hour...
    bedtime = datetime(2023, 3, 25, hour=22, tzinfo=ZoneInfo("Europe/Amsterdam"))
    # 🧨 returns 6:00, but should be 7:00 due to DST
    full_rest = bedtime + timedelta(hours=8)

Inconsistent meaning of "naive"
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Sometimes naive means "local time", sometimes it's interpreted as UTC,
and still in other cases it means "detached from the real world".

.. code-block:: python

    d = datetime(2024, 1, 1, ...)  # naive

    # ⚠️ Treated as a local datetime here...
    d.timestamp()
    d.astimezone(UTC)

    # 🧨 ...but assumed UTC here.
    d.utctimetuple()
    email.utils.format_datetime(d)
    datetime.utcnow()

    # 🤷 ...detached from the real world here (error)
    d >= datetime.now(UTC)

Silently non-existent datetimes
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

You aren't warned when you create a datetime that doesn't exist
(e.g. when the clock is set forward due to DST).
These invalid objects then create problems in subsequent operations.

.. code-block:: python

    # ⚠️ No error that this time doesn't exist on this date
    d = datetime(2023, 3, 26, hour=2, minute=30, tzinfo=ZoneInfo("Europe/Amsterdam"))

    # 🧨 No UTC equivalent exists, so it just makes one up
    assert d.astimezone(UTC) == d  # False???

Guessing on ambiguity
~~~~~~~~~~~~~~~~~~~~~

When a datetime occurs twice (due to the clock being set backwards),
the ``fold`` attribute `resolves the ambiguity <https://peps.python.org/pep-0495/>`_.
However, by defaulting to ``0``, it silently assumes you mean the first occurrence.

.. code-block:: python

    # 🧨 Datetime is guessing your intention here without warning
    d = datetime(2023, 10, 29, 2, 30, tzinfo=ZoneInfo("Europe/Amsterdam"))

Disambiguation is often futile
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Even though ``fold`` was introduced to disambiguate times,
equality comparisons don't make use of it: comparisons of disambiguated times
are always False!

.. code-block:: python

    # We carefully disambiguate an ambiguous datetime with fold=1...
    x = datetime(2023, 10, 29, 2, 30, tzinfo=ZoneInfo("Europe/Amsterdam"), fold=1)

    # 🧨 Nonetheless comparisons with other timezones are *always* False
    x.astimezone(UTC) == y  # False???

Equality behaves inconsistently
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Within the same timezone, times are compared naively (ignoring ``fold``),
while between different timezones, `they are compared by their UTC time <https://blog.ganssle.io/articles/2018/02/a-curious-case-datetimes.html>`_.

.. code-block:: python

    # 🧨 In the same timezone, fold is ignored...
    d = datetime(2023, 10, 29, 2, 30, tzinfo=ZoneInfo("Europe/Amsterdam"), fold=0)
    d_1h_later = d.replace(fold=1)
    d == d_1h_later  # True -- even though they are one hour apart!

    # ⁉️ ...but between different timezones, it *is* accounted for!
    d_1h_later = d_1h_later.astimezone(ZoneInfo("Europe/Paris"))
    d == d_1h_later  # False -- even though Paris has same DST behavior as Amsterdam!

Datetime inherits from date
~~~~~~~~~~~~~~~~~~~~~~~~~~~

This leads to unexpected behavior and it is widely considered a
`design <https://discuss.python.org/t/renaming-datetime-datetime-to-datetime-datetime/26279/2>`_ `flaw <https://github.com/python/typeshed/issues/4802>`_ in the standard library.

.. code-block:: python

    # 🧨 Breaks when you pass in a datetime, even though it's a subclass
    def is_future(dt: date) -> bool:
        return dt > date.today()

    # 🧨 Some methods inherited from `date` don't make sense
    datetime.today()

Why not...?
-----------

Pendulum
~~~~~~~~

Pendulum is full-featured datetime library, but it's
hamstrung by the decision to inherit from the standard library ``datetime``.
This means it inherits all the issues mentioned above, with the exception of #2
(DST-aware addition/subtraction).

Arrow
~~~~~

Pendulum did a good write-up of `the issues with Arrow <https://pendulum.eustace.io/faq/>`_.
It doesn't seem to address any of the above mentioned issues with the standard library.

Maya
~~~~

It's unmaintained, but does have an interesting approach.
By enforcing UTC, it bypasses a lot of issues with the standard library.
To do so, it sacrifices the ability to represent offset, zoned, and local datetimes.
So in order to perform any timezone-aware operations, you need to convert
to the standard library ``datetime`` first, which reintroduces the issues.

DateType
~~~~~~~~

DateType mostly fixes issues #1 (naive/aware distinction)
and #8 (datetime/date inheritance) during type-checking,
but doesn't address the other issues. Additionally,
it isn't able to *fully* type-check `all cases <https://github.com/glyph/DateType/blob/0ff07493bc2a13d6fafdba400e52ee919beeb093/tryit.py#L31>`_.

Heliclockter
~~~~~~~~~~~~

This library is a lot more explicit about the different types of datetimes,
addressing issue #1 (naive/aware distinction) with UTC, local, and zoned datetime types.
It doesn't address the other datetime pitfalls though.
Additionally, its "local" type doesn't account for DST.

python-dateutil
~~~~~~~~~~~~~~~

Dateutil attempts to solve some of the issues with the standard library.
However, it only *adds* functionality to work around the issues,
instead of *removing* the pitfalls themselves.
Without removing the pitfalls, it's still very likely to make mistakes.

FAQs
----

**Why isn't it a drop-in replacement for the standard library?**

Fixing the issues with the standard library requires a different API.
Keeping the same API would mean that the same issues would remain.

**Why not inherit from datetime?**

Not only would this keep most of the issues with the standard library,
it would result in brittle code: many popular libraries expect ``datetime`` *exactly*,
and `don't work <https://github.com/sdispater/pendulum/issues/289#issue-371964426>`_
`with subclasses <https://github.com/sdispater/pendulum/issues/131#issue-241088629>`_.

**What is the performance impact?**

Because whenever wraps the standard library, head-to-head performance will always be slightly slower.
However, because **whenever** removes the need for many runtime checks,
it may result in a net performance gain in real-world applications.

**Why not a C or Rust extension?**

It actually did start out as a Rust extension. But since the wrapping code
is so simple, it didn't make much performance difference.
Since it did make the code a lot more complex, a simple pure-Python implementation
was preferred.
If more involved operations are needed in the future, we can reconsider.

**Is this production-ready?**

The core functionality is complete and stable and the goal is to reach 1.0 soon.
The API may change slightly until then.
Of course, it's still a relatively young project, so the stability relies
on you to try it out and report any issues!


Versioning and compatibility policy
-----------------------------------

**Whenever** follows semantic versioning.
Until the 1.0 version, the API may change with minor releases.
Breaking changes will be avoided as much as possible,
and meticulously explained in the changelog.
Since the API is fully typed, your typechecker and/or IDE
will help you adjust to any API changes.

Acknowledgements
----------------

This project is inspired by the following projects. Check them out!

- `Noda Time <https://nodatime.org/>`_
- `Chrono <https://docs.rs/chrono/latest/chrono/>`_
- `DateType <https://github.com/glyph/DateType/tree/trunk>`_

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
