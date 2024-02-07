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

**Strict, predictable, and typed datetimes**

Do you cross your fingers every time you work with datetimes,
hoping that you didn't mix naive and aware?
or that you converted to UTC everywhere?
or that you avoided the many `pitfalls of the standard library <https://dev.arie.bovenberg.net/blog/python-datetime-pitfalls/>`_?
There's no way to be sure...

✨ Until now! ✨

**Whenever** is a datetime library designed from the ground up to enforce correctness.
Mistakes become red squiggles in your IDE, instead of bugs in production.

Benefits
--------

- Distinct classes with well-defined behavior
- Fixes datetime pitfalls that `Arrow and Pendulum don't address <https://dev.arie.bovenberg.net/blog/python-datetime-pitfalls/>`_
- Enforce correctness without runtime checks
- Based on `familiar concepts from other languages <https://www.youtube.com/watch?v=saeKBuPewcU>`_. Doesn't reinvent the wheel
- Simple and obvious. No frills or surprises
- `Thoroughly documented <https://whenever.rtfd.io/en/latest/overview.html>`_ and tested
- No third-party dependencies

Quickstart
----------

.. code-block:: python

   >>> from whenever import (
   ...    # Explicit types for different use cases
   ...    UTCDateTime,     # -> Great for codebases that normalize to UTC
   ...    OffsetDateTime,  # -> Localized times without ambiguities
   ...    ZonedDateTime,   # -> Full-featured IANA timezone support
   ...    LocalDateTime,   # -> In the local system timezone
   ...    NaiveDateTime,   # -> Detached from any timezone
   ...
   ...    hours, days, minutes  # aliases for timedelta(hours=...) etc.
   ... )

   >>> py311_release = UTCDateTime(2022, 10, 24, hour=17)
   UTCDateTime(2022-10-24 17:00:00Z)
   >>> pycon23_started = OffsetDateTime(2023, 4, 21, hour=9, offset=hours(-6))
   OffsetDateTime(2023-04-21 09:00:00-06:00)

   # Simple, explicit conversions
   >>> py311_in_paris = py311_release.as_zoned("Europe/Paris")
   ZonedDateTime(2022-10-24 19:00:00+02:00[Europe/Paris])
   >>> pycon23_started.as_local()
   LocalDateTime(2023-04-21 11:00:00-04:00)  # system timezone in NYC here

   # Comparison and equality across aware types
   >>> pycon23_started < py311_release
   False
   >>> py311_release == py311_release.as_zoned("America/Los_Angeles")
   True

   # DST-aware addition/subtraction
   >>> py311_in_paris + days(7)
   ZonedDateTime(2022-10-31 18:00:00+01:00[Europe/Paris])

   # Naive type that can't accidentally be mixed with aware types
   >>> simulation_start = NaiveDateTime(1950, 1, 1, hour=9)
   >>> # Mistakes caught by typechecker:
   >>> py311_release - simulation_start
   >>> simulation_start == pycon23_started

   # Lossless round-trip to/from text (useful for JSON/serialization)
   >>> py311_release.canonical_str()
   '2022-10-24T17:00:00Z'
   >>> ZonedDateTime.from_canonical_str('2022-10-24T19:00:00+02:00[Europe/Paris]')
   ZonedDateTime(2022-10-24 19:00:00+02:00[Europe/Paris])

   # Conversion to/from common formats
   >>> py311_release.rfc2822()  # also: from_rfc2822()
   "Mon, 24 Oct 2022 17:00:00 GMT"
   >>> pycon23_started.rfc3339()  # also: from_rfc3339()
   "2023-04-21T09:00:00-06:00"

   # Basic parsing
   >>> OffsetDateTime.strptime("2022-10-24+02:00", "%Y-%m-%d%z")
   OffsetDateTime(2022-10-24 00:00:00+02:00)

   # If you must: you can access the underlying datetime object
   >>> pycon23_started.py.ctime()
   'Fri Apr 21 09:00:00 2023'

Read more in the `full overview <https://whenever.readthedocs.io/en/latest/overview.html>`_
or `API reference <https://whenever.readthedocs.io/en/latest/api.html>`_.

Why not...?
-----------

The standard library
~~~~~~~~~~~~~~~~~~~~

The standard library is full of quirks and pitfalls.
To summarize the detailed `blog post <https://dev.arie.bovenberg.net/blog/python-datetime-pitfalls/>`_:

1.  Incompatible concepts of naive and aware are squeezed into one class
2.  Operations ignore Daylight Saving Time (DST)
3.  The meaning of "naive" is inconsistent (UTC, local, or unspecified?)
4.  Non-existent datetimes pass silently, then wreak havoc later
5.  It guesses in the face of ambiguity
6.  False negatives on equality of ambiguous times between timezones
7.  False positives on equality of ambiguous times within the same timezone
8.  ``datetime`` inherits from ``date``, but behaves inconsistently
9.  ``datetime.timezone`` isn’t a timezone. ``ZoneInfo`` is.
10. The local timezone is DST-unaware


Pendulum
~~~~~~~~

Pendulum is full-featured datetime library, but it's
hamstrung by the decision to inherit from the standard library ``datetime``.
This means it inherits most of the pitfalls mentioned above,
with the notable exception of DST-aware addition/subtraction.

Arrow
~~~~~

Arrow is probably the most historically popular datetime library.
Pendulum did a good write-up of `the issues with Arrow <https://pendulum.eustace.io/faq/>`_.
It addresses fewer of datetime's pitfalls than Pendulum.

DateType
~~~~~~~~

DateType mostly fixes the issue of mixing naive and aware datetimes,
and datetime/date inheritance during type-checking,
but doesn't address the other pitfalls.
The type-checker-only approach also means that it doesn't enforce correctness at runtime,
and it requires developers to be knowledgeable about
how the 'type checking reality' differs from the 'runtime reality'.

python-dateutil
~~~~~~~~~~~~~~~

Dateutil attempts to solve some of the issues with the standard library.
However, it only *adds* functionality to work around the issues,
instead of *removing* the pitfalls themselves.
This still puts the burden on the developer to know about the issues,
and to use the correct functions to avoid them.
Without removing the pitfalls, it's still very likely to make mistakes.

Maya
~~~~

It's unmaintained, but does have an interesting approach.
By enforcing UTC, it bypasses a lot of issues with the standard library.
To do so, it sacrifices the ability to represent offset, zoned, and local datetimes.
So in order to perform any timezone-aware operations, you need to convert
to the standard library ``datetime`` first, which reintroduces the issues.

Heliclockter
~~~~~~~~~~~~

This library is a lot more explicit about the different types of datetimes,
addressing issue of naive/aware mixing with UTC, local, and zoned datetime subclasses.
It doesn't address the other datetime pitfalls though.

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
- `Temporal <https://tc39.es/proposal-temporal/docs/>`_
- `Chrono <https://docs.rs/chrono/latest/chrono/>`_

Contributing
------------

Contributions are welcome! Please open an issue or a pull request.

  ⚠️ **Note**: big changes should be discussed in an issue first.
  This is to avoid wasted effort if the change isn't a good fit for the project.

..

  ⚠️ **Note**: Some tests are skipped on Windows.
  These tests use unix-specific features to set the timezone for the current process.
  As a result, Windows isn't able to run certain tests that rely on the system timezone.
  It appears that `this functionality is not available on Windows <https://stackoverflow.com/questions/62004265/python-3-time-tzset-alternative-for-windows>`_.

Setting up a development environment
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

You'll need `poetry <https://python-poetry.org/>`_ installed.
An example of setting up things up:

.. code-block:: bash

   poetry install

   # To run the tests with the current Python version
   pytest

   # if you want to build the docs
   pip install -r docs/requirements.txt

   # Various checks
   mypy src/ tests/
   flake8 src/ tests/

   # autoformatting
   black src/ tests/
   isort src/ tests/

   # To run the tests with all supported Python versions
   # Alternatively, let the github actions on the PR do it for you
   pip install tox
   tox -p auto
