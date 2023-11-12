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

.. image::  https://img.shields.io/github/actions/workflow/status/ariebovenberg/whenever/CI.yml?branch=main&style=flat-square
   :target: https://github.com/ariebovenberg/whenever

.. image:: https://img.shields.io/readthedocs/whenever.svg?style=flat-square
   :target: http://whenever.readthedocs.io/

**Typesafe datetimes powered by Rust's chrono library.**

*Currently a work in progress. Leave a ⭐️ if you're interested how this develops.*

Why?
----

Most Python datetime libraries use a single class for
naive, timezoned, *and* offset datetimes,
making it all too easy to mistakenly (and *silently!*) mix them.
Your type checker and IDE are powerless to help you,
leaving you to discover these errors at runtime.

**Whenever** takes a different approach, and provides dedicated datetime
types that reveal mistakes *before* you run your code.

Types of datetime (and why they're important)
---------------------------------------------

🚧 **NOT YET FULLY IMPLEMENTED** 🚧

**Whenever** distinguishes these types:

1. **Naive** datetime: A simple type that isn't aware of any timezone or
   UTC offset.
2. **UTC**-only datetime: A fast and efficient type for when you
   *only* want to deal with UTC.
3. **Offset** datetime: A datetime with a *fixed* offset from UTC.
4. **Zoned** datetime: A datetime within a timezone, often with a variable
   UTC offset. Zoned datetimes may be ambiguous or non-existent.

Below is a table of supported operations for each type:

+-----------------------+-------+-----+--------+-------+
| Operation             | Naive | UTC | Offset | Zoned |
+=======================+=======+=====+========+=======+
| comparison            |  ✅   | ✅  |  ✅    |  ❌   |
+-----------------------+-------+-----+--------+-------+
| difference            |  ✅   | ✅  |  ✅    |  ❌   |
+-----------------------+-------+-----+--------+-------+
| add/subtract duration |  ✅   | ✅  |  ✅    |  ❌   |
+-----------------------+-------+-----+--------+-------+
| to timestamp          |  ❌   | ✅  |  ✅    |  ⚠️   |
+-----------------------+-------+-----+--------+-------+
| from timestamp        |  ❌   | ✅  |  ✅    |  ✅   |
+-----------------------+-------+-----+--------+-------+
| now()                 |  ❌   | ✅  |  ✅    |  ✅   |
+-----------------------+-------+-----+--------+-------+
| to naive              |  n/a  | ✅  |  ✅    |  ✅   |
+-----------------------+-------+-----+--------+-------+
| to UTC                |  ❌   | n/a |  ✅    |  ⚠️   |
+-----------------------+-------+-----+--------+-------+
| to offset             |  ❌   | ✅  |  n/a   |  ⚠️   |
+-----------------------+-------+-----+--------+-------+
| to zoned              |  ❌   | ✅  |  ✅    |  n/a  |
+-----------------------+-------+-----+--------+-------+

⚠️ = returns 0, 1, or 2 results, which must explicitly be handled.

❌ = Too ambiguous to provide a sensible result.

Quickstart
----------

**Most of the functionality it not yet implemented.**
Some basic UTC functionality is already available though:

.. code-block:: python

   from whenever.utc import DateTime
   from whenever import Some, Nothing

   # Explicit types for functional/Rust-style error handling
   d = DateTime.new(2020, 1, 1, 12, 0, 0).unwrap()

   match DateTime.parse("2020-08-15T12:08:30Z"):
       case Some(d2) if d2 > d:
           print('parsed a datetime after 2020-01-01T12:00:00Z')
       case Nothing():
           print('failed to parse')

   d.timestamp()  # UNIX timestamp
   d.to_py()  # convert to Python's datetime.datetime


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

   pip install maturin
   maturin develop --extras test
   pytest
