---
hide-toc: true
---

(datetime-pitfalls)=
# The pitfalls of `datetime`

Python's `datetime` module first appeared in Python 2.3, released in 2003.
In many ways, that’s remarkable: it has remained largely usable for over twenty years,
in a problem domain that is notoriously difficult and—at the time—still evolving.

Compared to other ecosystems, Python actually did quite well.
Java and JavaScript both eventually introduced entirely new date-time APIs
because their original designs proved too painful to work with.
Python never needed a wholesale replacement.

That does not mean `datetime` is free of problems.
It has a number of sharp edges that regularly trip up even experienced
developers—often in subtle ways that only show up in production,
around daylight saving time, time zones, or arithmetic.


```{note}

Before diving into those pitfalls, it's worth acknowledging the care that has
gone into maintaining and evolving `datetime`.
Over the years, it has adapted to new realities through changes
like PEP 495 (disambiguating local times) and PEP 615 (the `zoneinfo` module),
while preserving backward compatibility.

What follows is not a condemnation of `datetime`,
but a catalog of the places where its design makes certain mistakes easy to make.
"Pitfall" is, of course, a subjective
term—but these are issues that come up again and again in real codebases.
```

## Pitfalls covered

```{eval-rst}
.. toctree::
   :maxdepth: 1

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
