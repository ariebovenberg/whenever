---
myst:
  html_meta:
    description: >-
      Conceptual introduction to dates and times, independent of any library, and
      why understanding the underlying model beats learning an API by trial and
      error.
---

(fundamentals)=
# The fundamentals of time

Time isn't actually that hard—once you understand a handful of concepts.

The trouble is that most of us learn it backwards: API first.
In Python that usually means the standard library's {mod}`datetime` module,
figured out by trial and error, without ever forming a clear picture of what a
time value is supposed to represent.
It's the same way many people use {class}`str` long before they've heard of
Unicode: a rule of thumb like *"just use UTF-8"* carries you a long way—right up
until something behaves strangely and you have no model to reason with.

*"Just use UTC"* is that kind of rule, and it fails the same way.
The pages below cover the handful of ideas such rules paper over.
They're written to be read in order, starting with the most important
distinction of all: exact time versus local time.

```{eval-rst}

.. grid:: 1 2 2 2
   :margin: 4 4 0 0
   :gutter: 2

   .. grid-item-card:: 1. Exact time vs local time
      :link: exact-vs-local
      :link-type: doc
      :shadow: md

      A moment on the timeline, or a reading on a clock: not the same thing

   .. grid-item-card:: 2. Timezones
      :link: timezones
      :link-type: doc
      :shadow: md

      The rules that connect the two—and what "timezone" actually means

   .. grid-item-card:: 3. Ambiguity
      :link: ambiguity
      :link-type: doc
      :shadow: md

      When the clock says something twice, or skips it entirely

   .. grid-item-card:: 4. Arithmetic
      :link: arithmetic
      :link-type: doc
      :shadow: md

      Why "a day later" and "24 hours later" are different questions

.. toctree::
   :maxdepth: 1
   :hidden:

   exact-vs-local
   timezones
   ambiguity
   arithmetic
```

```{tip}
Once you're comfortable with the fundamentals,
head to the {ref}`guide <guide>` to see how `whenever` puts them into practice.
```
