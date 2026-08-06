---
myst:
  html_meta:
    description: >-
      What 'timezone' actually means: UTC offsets, abbreviations, and IANA
      timezones, what each can and cannot express, and when to use which.
---

(timezones-explained)=
# Timezones

{ref}`Exact time and local time <exact-vs-local>` are useful on their own, but most real programs need to move between them.
We store events as precise instants, display them to users as local clock readings,
and interpret user input as something that should happen at a specific moment.

A **time zone** describes how local time relates to exact time.

In practice, "time zone" is used to mean several different things.
Each of them captures part of that relationship, and each comes with different trade-offs.

## Offsets

The simplest way to relate local time to exact time is an **offset from UTC**,
such as `+01:00` or `-08:00`.

An offset answers a very narrow question:
*How far is local time from UTC at this moment?*

Examples:

* `2026-01-15T09:00:00+01:00`
* "This timestamp is 3 hours behind UTC"
* `Thu, 29 Jan 2026 00:03:32 +0900`

For the timestamp where it was recorded, an offset is precise and unambiguous.
Given local fields and an offset, you can determine the exact instant.

An offset is fixed by definition; what can change is the offset used by a
region. Many regions change theirs because of daylight saving time or
political decisions. A recorded offset therefore carries no guarantee about
which offset applies after shifting or modifying the timestamp. Reusing it may
produce an offset that is stale relative to the original region.

Offsets are excellent for *interchange*, but risky as long-term identifiers.

## Abbreviations

Time zone **abbreviations** like `PST`, `CET`, or `JST` are compact and human-friendly.

Examples:

* "The meeting is at 10:00 PST"
* "Logs are labeled in CET"

Abbreviations imply both an offset and a region,
and often suggest whether daylight saving time is in effect.
The problem is that abbreviations are **ambiguous**.
The same abbreviation can mean different things in different contexts.
For example, `CST` can refer to:

* **Central Standard Time** (North America),
* **China Standard Time**,
* or **Cuba Standard Time**

Abbreviations are useful for display purposes,
but they are a poor choice for storing or interpreting time programmatically.

## IANA time zones

The most complete way to describe the relationship between local and exact time
is using a time zone from the **[IANA Time Zone Database](https://en.wikipedia.org/wiki/Tz_database)**.
These time zones are identified uniquely by names such as `Europe/Amsterdam` or `America/Los_Angeles`.

An IANA time zone represents a *set of rules* in a *specific region*:

* how the offset from UTC changes over time
* when daylight saving transitions occur
* what those rules were in the past, and what they are expected to be in the future

Given a local time and an IANA time zone,
software can usually determine the corresponding exact time—and vice versa.

These identifiers are the closest thing we have to a "complete" time zone in software.
They are widely supported, regularly updated, and shared across programming languages and systems.

That said, they are not magical. IANA time zones can only reflect **known rules**.
If a government changes its timekeeping laws,
the database must be updated and redistributed before software can reflect the new reality.

Time zones know the future only as long as the rules stay the same.

## Choosing the right representation

None of these representations is "the true" time zone. Each answers a different question:

* Offsets describe *where local time is relative to UTC at that moment*
* Abbreviations describe *how humans commonly refer to a time in a timezone*
* IANA identifiers describe *the evolving rules of local time*

Understanding their strengths and limitations helps avoid subtle bugs and incorrect assumptions.

## Time zones in `whenever`

Whenever has two classes for dealing with time zones:

- {class}`~whenever.OffsetDateTime` represents a local date and time with a fixed UTC offset.
  It does not retain daylight-saving or historical rules; see
  {ref}`offset-datetime-guidance` for the resulting tradeoffs.
- {class}`~whenever.ZonedDateTime` represents a local date and time in the context of an IANA time zone.
  It uses the full set of rules to convert between local and exact time.

Use {class}`~whenever.ZonedDateTime` when regional rules are known and matter.

## Summary

| Representation               | What it captures            | Strengths                    | Limitations                     | `whenever` class                |
| ---------------------------- | --------------------------- | ---------------------------- | ------------------------------- | ------------------------------- |
| UTC offset (`+01:00`)        | Observed diff. from UTC | Simple, unambiguous | No regional rules; may be stale after shifting | {class}`~whenever.OffsetDateTime` |
| Abbreviation (`PST`)         | Human-friendly label        | Compact, readable            | Ambiguous | N/A                            |
| IANA ID (`Europe/Amsterdam`) | Full time zone rules        | Accurate, widely supported   | Depends on database updates     | {class}`~whenever.ZonedDateTime`   |

## What comes next: resolving local times

Converting an exact instant into a timezone is straightforward. Converting
local fields back to an instant can require a decision: transitions make some
local times occur twice and others not at all. Input containing both a numeric
offset and a timezone can also contain a conflict.

The next fundamental concept is {ref}`local-time ambiguity <ambiguity2>`.
For Whenever's complete resolution flow, including offset conflicts, see
{ref}`resolving-local-times`.
