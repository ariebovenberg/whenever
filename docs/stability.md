---
myst:
  html_meta:
    description: >-
      The whenever 1.x compatibility promise: which changes a release may make,
      how an API is deprecated, provisional APIs, warnings, security fixes, and
      what the promise does not cover.
---

(stability)=
# Stability policy

`whenever` follows [semantic versioning](https://semver.org).
Code that works with 1.0 keeps working on every 1.x release:
changes are additive,
and nothing is removed.

1.x is meant to last.
Nobody can promise the future,
but there is no plan for a 2.0:
the churn of a major release is exactly what this policy avoids.

The promise covers both the {term}`Rust extension`
and the {term}`pure-Python backend`.
Releases before 1.0 did make breaking changes;
the {doc}`changelog` explains each one.

## What may a 1.x release change?

A minor release may add:

- types, functions, methods, and attributes;
- keyword-only parameters, whose default keeps today's behavior;
- values for a parameter that takes a fixed set of strings,
  such as a new rounding mode;
- warnings (see [below](#stability-warnings)).

It may also make a call *more permissive*:
accept input it rejects today,
or return a value where it raises today.
Code that relies on a rejection—catching `ValueError` to validate input,
for example—may get a value instead after an upgrade.

Everything else stays.
A call that works today returns the same result on every 1.x release,
apart from the cases [not covered](#stability-not-covered).

## How is an API deprecated?

An API that a better one replaces is **deprecated**:

- the documentation says so and names the replacement;
- the type stubs mark it with [`@deprecated`](https://peps.python.org/pep-0702/),
  so your type checker points out each use;
- calling it emits {class}`~whenever.WheneverDeprecationWarning`,
  naming the replacement;
- it gets no new features;
- it stays supported for the rest of 1.x.

The warning says *switch when you can*,
not *this is about to break*.
To keep using the API for now,
filter the warning as {ref}`warnings` describes.

Only a major release—if one comes at all—removes an API,
and only one that an earlier release deprecated.

## Provisional APIs

A large new API may ship as **provisional**,
in the sense of [PEP 411](https://peps.python.org/pep-0411/).
Its documentation and the changelog entry that introduces it say so.

A provisional API may change incompatibly in a minor release,
and that release's changelog entry lists the change.
Provisional status lasts at most two minor releases;
after that, the API is stable as it stands.

No current API is provisional.

(stability-warnings)=
## Warnings

The warning classes are stable.
No class is removed or moved under a different parent,
so a filter on a class keeps matching.
A {term}`call-local escape` that silences a warning today keeps silencing it.

Which calls warn is *not* stable.
A minor release may add a warning,
or move one to a new subclass of its current class.
If your tests turn warnings into errors, as {ref}`warnings` suggests,
an upgrade can fail them.
That's the point of the setup:
read the new warning, then fix the call or escape it.

## Security fixes

A fix for a security vulnerability may break compatibility
when no compatible fix exists.
Its changelog entry says what changed and why.

(stability-not-covered)=
## What isn't covered?

- **Bug fixes.** Behavior that contradicts the documentation is a bug,
  and its fix changes that behavior, even if code relies on it.
- **Time zone data.** Results that depend on the IANA time zone database
  change when the installed database does.
  `whenever` reads it from your system or the `tzdata` package;
  see {ref}`faq-tzdb-version`.
- **Messages.** The text of exceptions and warnings may change,
  as may which of two defects in one call is reported.
- **The ends of the range.** Near year 1 and year 9999,
  a call may raise `OverflowError` instead of `ValueError`,
  or start or stop raising,
  and the two backends may differ.
- **Calls the type annotations reject.** An argument of the wrong type
  raises whatever falls out, and a later release may raise something else
  or accept it.
- **Type checker results.** More precise annotations, new overloads,
  and a new value in a set of strings may surface new type checker errors,
  for example in a `match` that handles every value.
- **`repr()` text.** It may change,
  but it keeps rebuilding an equal value.
- **Hash values.** `hash()` agrees with `==` within a release,
  not across releases.
- **Pickles from the future.** A pickle loads in the release that wrote it
  and in later ones, not in earlier ones;
  see {ref}`pickling`.
- **Private names.** Anything whose name starts with an underscore,
  including modules such as `whenever._pywhenever`.
- **Python versions.** A minor release may drop a Python version
  that has reached its end of life.
- **Performance.** Speed and memory use may change in either direction.
