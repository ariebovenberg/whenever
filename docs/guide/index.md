---
hide-toc: true
myst:
  html_meta:
    description: >-
      Entry point to the practical guide, grouped by task: choosing a type,
      comparison and conversion, ambiguity, arithmetic and deltas, parsing,
      standard library interop, and testing.
---

(guide)=
# Guide

Everything you need to use `whenever` day to day, roughly in the order
you'll run into it. Start with {ref}`choosing a type <choosing-a-type>`—the rest
follows from that decision.

For background on dates and times in general, see the
{ref}`fundamentals <fundamentals>`.
For the details of a specific class or method, see the {ref}`API reference <api>`.

## The essentials

```{eval-rst}
.. toctree::
   :maxdepth: 1

   choosing-a-type
   partial-types
   comparison
   conversions
   ambiguity
```

## Calculating with dates and times

```{eval-rst}
.. toctree::
   :maxdepth: 1

   arithmetic
   deltas
   rounding
```

## Talking to the outside world

```{eval-rst}
.. toctree::
   :maxdepth: 1

   parsing
   stdlib-convert
   system-tz
   pickling
```

## Keeping it reliable

```{eval-rst}
.. toctree::
   :maxdepth: 1

   testing
   warnings
```
