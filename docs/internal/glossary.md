# Contributor glossary

Vocabulary for code, tests, plans, and agent instructions that a user of the
library never needs. This page is excluded from the docs build and from the
llms summaries. A term belongs in `docs/glossary.md` instead when it appears
in a warning message, a docs page, or a public name.

Same rules as the public glossary: use the headword in code, comments, and
messages; the "preferred over" words are rejected synonyms.

**compatibility shim**
: A deprecated path kept for one release cycle: it delegates to its
  replacement and emits `WheneverDeprecationWarning`.
  Preferred over *wrapper*, *alias*, and *legacy path*.

**replacement**
: What a deprecated path migrates to, as named in its warning message
  ("use X instead").
  Preferred over *preferred spelling* and *preferred path*.

**omitted**
: Said of an argument the caller did not pass. Omission is distinct from
  every accepted value, including `None`; where it has its own meaning, the
  runtime default is the private sentinel spelled `UNSET`
  (`pysrc/whenever/_common.py`).
  Preferred over *unset*, *missing*, and *not specified*.
