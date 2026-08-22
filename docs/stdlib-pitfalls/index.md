---
hide-toc: true
myst:
  html_meta:
    description: >-
      Overview of the sharp edges in Python's standard datetime module, and how
      whenever addresses each of them.
---

(datetime-pitfalls)=
# The pitfalls of `datetime`

Python's `datetime` module first appeared in Python 2.3, back in 2003.
That it has remained usable for over twenty years is remarkable, in a problem
domain this treacherous: Java and JavaScript both ended up replacing their
date-time APIs wholesale, while Python never needed a wholesale replacement.

It does, however, have sharp edges—and they tend to show up at the worst
possible moment. On the night of a clock change, on a machine configured for
another timezone, or in the one branch nobody thought to test.
Below are the ones that draw blood most often, and what `whenever` does instead.

```{note}
None of this is a condemnation of `datetime`. It has been carefully maintained
and adapted over the years—through PEP 495 (disambiguating local times) and
PEP 615 (the `zoneinfo` module), among others—all while preserving backwards
compatibility. "Pitfall" is a subjective term: what follows is simply a catalog
of the places where the design makes certain mistakes easy to make.
```

```{eval-rst}

.. grid:: 1 2 2 3
   :margin: 4 4 0 0
   :gutter: 2

   .. grid-item-card:: :octicon:`north-star` One type for everything
      :link: naive-aware
      :link-type: doc
      :shadow: md

      One class for two incompatible concepts, so annotations can't tell
      them apart

   .. grid-item-card:: :octicon:`sun` Operators ignore DST
      :link: dst-ignored
      :link-type: doc
      :shadow: md

      Eight hours after 10pm isn't always 6am, but ``+`` thinks it is

   .. grid-item-card:: :octicon:`question` Inconsistent role of "naive"
      :link: naive-meaning
      :link-type: doc
      :shadow: md

      Sometimes the system timezone, sometimes UTC, sometimes neither

   .. grid-item-card:: :octicon:`mute` Ambiguity passes silently
      :link: silent-ambiguity
      :link-type: doc
      :shadow: md

      Times that happen twice—or never—are resolved without a word

   .. grid-item-card:: :octicon:`pulse` Equality edge cases
      :link: broken-equality
      :link-type: doc
      :shadow: md

      Identical moments can compare unequal, and distinct ones equal

   .. grid-item-card:: :octicon:`x` ``timezone`` isn't enough
      :link: timezone-classes
      :link-type: doc
      :shadow: md

      Three timezone classes to choose from; the obvious one is wrong

   .. grid-item-card:: :octicon:`location` Implicit system timezone
      :link: system-timezone
      :link-type: doc
      :shadow: md

      Your machine's configuration quietly leaks into the results

   .. grid-item-card:: :octicon:`flame` ``datetime`` inherits from ``date``
      :link: date-inheritance
      :link-type: doc
      :shadow: md

      A subclass that can't be compared with its own base class

   .. grid-item-card:: :octicon:`alert` ``timedelta.seconds`` footgun
      :link: timedelta-seconds
      :link-type: doc
      :shadow: md

      A remainder that looks like a total—right up until it doesn't

.. toctree::
   :maxdepth: 1
   :hidden:

   naive-aware
   dst-ignored
   naive-meaning
   silent-ambiguity
   broken-equality
   timezone-classes
   system-timezone
   date-inheritance
   timedelta-seconds
```
