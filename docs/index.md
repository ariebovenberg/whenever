---
myst:
  html_meta:
    description: >-
      Overview of whenever, a typesafe Python datetime library with separate
      Instant, ZonedDateTime, OffsetDateTime, and PlainDateTime types, DST-safe
      arithmetic, and a Rust-backed implementation.
---

# Whenever

**Type-safe datetimes for Python that get DST right. Rust or pure Python—your choice.**

Do you cross your fingers every time you work with Python's {mod}`datetime`—hoping
that you didn't mix naive and aware, or run into one of its
{ref}`other pitfalls <datetime-pitfalls>`?

```python
bedtime = datetime(2023, 3, 25, 22, tzinfo=ZoneInfo("Europe/Paris"))
full_rest = bedtime + timedelta(hours=8)
# It returns 6am, but should be 7am—because we skipped an hour due to DST!
```

*Whenever* takes the guesswork out, bringing **well-established concepts**
from modern datetime libraries in other languages to Python.
Mixing up naive and aware becomes a **type error** instead of a bug you find in
production, and DST is handled correctly in **all** arithmetic:

```python
>>> from whenever import Instant, ZonedDateTime, PlainDateTime

# The same bedtime, DST-safe: you get your full eight hours
>>> bedtime = ZonedDateTime(2023, 3, 25, 22, tz="Europe/Paris")
>>> bedtime.add(hours=8)
ZonedDateTime("2023-03-26 07:00:00+02:00[Europe/Paris]")

# Explicit, type-safe conversions
>>> bedtime.to_tz("America/New_York")
ZonedDateTime("2023-03-25 17:00:00-04:00[America/New_York]")

# A moment in time, without timezone or calendar complexity
>>> Instant.now()
Instant("2024-07-04 10:36:56Z")

# Plain (naive) datetimes are a distinct type; impossible to mix with aware
>>> PlainDateTime(2023, 3, 26, 7) < bedtime  # caught by your type checker!
```

In short, it's designed to be:

**{octicon}`shield-check` Correct**
: Smooths over the {ref}`sharp edges <datetime-pitfalls>` of the standard
  library---DST first among them, but far from the only one.

**{octicon}`lock` Typesafe**
: Distinct types for exact and local time mean your type checker catches
  what would otherwise be a production bug.

**{octicon}`zap` Fast**
: In common operations, whenever is 10-100× faster than Pendulum and
  Arrow---and 2-4× as fast as the standard library.
  Rather not depend on a Rust extension? A pure Python version is available too.

---

Browse the sidebar to navigate the documentation, or jump directly to a topic below.

```{eval-rst}

.. grid:: 1 2 2 3
   :margin: 4 4 0 0
   :gutter: 2

   .. grid-item-card:: :octicon:`light-bulb` Fundamentals of time
      :link: fundamentals
      :link-type: ref
      :shadow: md

      Time is easy---once you grasp the basics

   .. grid-item-card:: :octicon:`alert` Why not ``datetime``?
      :link: datetime-pitfalls
      :link-type: ref
      :shadow: md

      The pitfalls of the standard library

   .. grid-item-card:: :octicon:`book` Guide
      :link: guide
      :link-type: ref
      :shadow: md

      Learn how to use the library effectively

   .. grid-item-card:: :octicon:`rocket` Examples
      :link: examples
      :link-type: ref
      :shadow: md

      Dive into practical examples

   .. grid-item-card:: :octicon:`code` API Reference
      :link: api
      :link-type: ref
      :shadow: md

      All information on classes and functions

   .. grid-item-card:: :octicon:`graph` Performance
      :link: performance
      :link-type: ref
      :shadow: md

      Speed, import time, and binary size

   .. grid-item-card:: :octicon:`question` FAQ
      :link: faq
      :link-type: ref
      :shadow: md

      Find answers to common questions

   .. grid-item-card:: :octicon:`typography` Pattern format codes
      :link: pattern-format
      :link-type: ref
      :shadow: md

      Overview of the pattern formatting syntax

   .. grid-item-card:: :octicon:`repo` Repository
      :link: https://github.com/ariebovenberg/whenever
      :shadow: md
      :link-alt: GitHub repository

      Find code, issues, and discussions here



.. toctree::
   :maxdepth: 2
   :caption: Background
   :hidden:

   fundamentals/index
   stdlib-pitfalls/index
   why-not-pendulum
   glossary

.. toctree::
   :maxdepth: 2
   :caption: Overview
   :hidden:

   Introduction <self>
   guide/index
   examples
   performance
   design
   faq

.. toctree::
   :maxdepth: 1
   :caption: API Reference
   :hidden:

   reference/iso8601.rst
   reference/pattern-format
   reference/datetime.rst
   reference/partial-types
   reference/deltas.rst
   reference/misc.rst

.. toctree::
   :maxdepth: 2
   :caption: Development
   :hidden:

   changelog
   contributing
   Github repository <https://github.com/ariebovenberg/whenever>

```
