# Welcome to Whenever

**Whenever** is a Python library for working with dates and times.

Over two decades, Python's `datetime` has accumulated pitfalls that trip up even
experienced developers: arithmetic that silently ignores DST, and a type system
that can't distinguish between naive and aware datetimes.
Popular alternatives like [Arrow](https://pypi.org/project/arrow/) and
[Pendulum](https://pypi.org/project/pendulum/) don't fully address these issues either.

*Whenever* takes a different approach: a typesafe API built on well-established
concepts from modern datetime libraries across languages—with exceptional
performance via a Rust extension, and a pure Python option for environments
that need it.

It's designed to be:

**{octicon}`shield-check` Correct**
: Handles DST correctly in all arithmetic and fixes the most common pitfalls
  of Python's standard `datetime` module.

**{octicon}`lock` Typesafe**
: Separate types for "aware" and plain datetimes make it
  impossible to accidentally mix them—modeled on proven concepts from
  modern datetime libraries in other languages.

**{octicon}`zap` Fast**
: In common operations, whenever is 10-100× faster than Pendulum and 
  Arrow---and 2-4× as fast as the standard library.

A quick taste:

```python
>>> from whenever import Instant, ZonedDateTime, PlainDateTime

# Identify a moment in time, without timezone/calendar complexity
>>> now = Instant.now()
Instant("2024-07-04 10:36:56Z")

# Explicit, type-safe conversions
>>> now.to_tz("Europe/Paris")
ZonedDateTime("2024-07-04 12:36:56+02:00[Europe/Paris]")

# DST-safe arithmetic; stdlib doesn't do this!
>>> zdt = ZonedDateTime("2023-10-28 22:00:00+02:00[Europe/Amsterdam]")
>>> zdt.add(hours=6)  # correctly accounts for the autumn clock change
ZonedDateTime("2023-10-29 03:00:00+01:00[Europe/Amsterdam]")

# Plain (naive) datetimes are a distinct type; impossible to mix with aware
>>> PlainDateTime("2024-07-04 15:30") < zdt  # caught by type checker!
```

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

   .. grid-item-card:: :octicon:`graph` Benchmarks
      :link: benchmarks
      :link-type: ref
      :shadow: md

      How whenever compares in speed

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

.. toctree::
   :maxdepth: 2
   :caption: Overview
   :hidden:

   Introduction <self>
   guide/index
   examples
   benchmarks
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
