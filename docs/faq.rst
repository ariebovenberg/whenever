❓ FAQ
======

Does performance really matter for a datetime library?
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Most of the time, datetime handling isn’t the main bottleneck in Python
programs—but then again, very few things are.
Still, datetime logic is arithmetic-heavy and often applied in bulk,
making it a classic case where faster code pays off.
That's why many core Python components are backed by optimized implementations,
and why this library offers a Rust version for speed alongside a pure-Python version
for portability.

Is free-threaded Python supported?
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Yes, free-threaded Python is supported. However, this support is 
still in beta. Please report any issues you encounter when using
whenever in a free-threaded Python environment.

.. _faq-why-instant:

Why does :class:`~whenever.Instant` exist?
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Since you can also express a moment in time using
:class:`~whenever.ZonedDateTime`
you might wonder why :class:`~whenever.Instant` exists.
The reason it exists is precisely *because* it doesn't include a timezone.
By using :class:`~whenever.Instant`, you clearly express that you only
care about when something happened, and don't care about the local time.

Consider the difference in intent between these two classes:

.. code-block:: python
   :emphasize-lines: 2

   class ChatMessage:
       sent: Instant
       content: str


.. code-block:: python
   :emphasize-lines: 2

   class ChatMessage:
       sent: ZonedDateTime
       content: str

In the first example, it's clear that you only care about the moment when
chat messages were sent.
In the second, you communicate that you also store the user's local time.
This intent is crucial for reasoning about the code,
and extending it correctly (e.g. with migrations, API endpoints, etc).

Why the name ``PlainDateTime``?
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

This has been an oft-discussed topic. Several names were considered
for the concept of a "datetime without a timezone".

Each option had its pros and cons.

- Why not ``NaiveDateTime``? This name is already used in the standard library,
  which does give it recognition. However, "naive" is a decidedly negative term.
  While datetimes without a timezone *can* be used in a naive way
  by developers who don't understand the implications, they are not inherently wrong to use.
- Why not ``CivilDateTime``? This is the most "technically correct" name,
  as it refers to the `time as used in civilian life <https://en.wikipedia.org/wiki/Civil_time>`_.
  This name is most notably used in Jiff (Rust) and Abseil (C++) libraries.
  While this niche name is a boon to these languages,
  Python tends to favor more common, non-jargon names:
  "dict" over "hashmap", "list" over "array", etc.
- Why not ``LocalDateTime``? This is the name that ISO8601 gives to the concept,
  also making it a "technically correct" name.
  However, the term "local" has become overloaded in the Python world
  where it often refers to the system timezone.

While ``PlainDateTime`` is not perfect, it has the following advantages:

- Javascript's new Temporal API uses this name. There's significant
  overlap between Python and Javascript developers,
  so this name is likely to be familiar as its popularity grows.
- It's a name that is easy to understand and remember, also for non-native speakers.

Common critiques of ``PlainDateTime`` are:

- *The name doesn't convey any meaning in itself.*
  This is also a strength. It *is* simply a date+time. Yes, it can
  be used to represent a local time, but it doesn't have to be.
- *The name is defined by what it is not.*
  Actually, it's really common to name things in opposition to something else.
  Think of: "*stainless* steel", "*plain* text", or "*serverless* computing".


.. _faq-leap-seconds:

Are leap seconds supported?
~~~~~~~~~~~~~~~~~~~~~~~~~~~

Leap seconds are unsupported.
Taking leap seconds into account is a complex and niche feature,
which is not needed for the vast majority of applications.
This decision is consistent with other modern libraries
(e.g. NodaTime, Temporal) and standards (RFC 5545, Unix time) which
do not support leap seconds.

One improvement that is planned: allowing the parsing of leap seconds,
which are then truncated to 59 seconds.

.. _faq-why-not-dropin:

Why no drop-in replacement for ``datetime``?
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Fixing the issues with the standard library requires a different API.
Keeping the same API would mean that the same issues would remain.
Also, inheriting from the standard library would result in brittle code:
many popular libraries expect ``datetime`` *exactly*,
and `don't work <https://github.com/sdispater/pendulum/issues/289#issue-371964426>`_
with `subclasses <https://github.com/sdispater/pendulum/issues/131#issue-241088629>`_.

.. _faq-production-ready:

Is it production-ready?
~~~~~~~~~~~~~~~~~~~~~~~

The core functionality is complete and mostly stable.
The goal is to reach 1.0 soon, but the API may change until then.
Of course, it's still a relatively young project, so the stability relies
on you to try it out and report any issues!

Where do the benchmarks come from?
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

More information about the benchmarks can be found in the ``benchmarks`` directory
of the repository.

How can I use the pure-Python version?
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

*Whenever* is implemented both in Rust and in pure Python.
By default, the Rust extension is used, as it's faster and more memory-efficient.
But you can opt out of it if you prefer the pure-Python version,
which has a smaller disk footprint and works on all platforms.

.. note::

   On PyPy and GraalVM, the Python implementation is automatically used. No need to configure anything.

To opt out of the Rust extension and use the pure-Python version,
install from the source distribution with the ``WHENEVER_NO_BUILD_RUST_EXT`` environment variable set:

.. code-block:: bash

   WHENEVER_NO_BUILD_RUST_EXT=1 pip install whenever --no-binary whenever

You can check if the Rust extension is being used by running:

.. code-block:: bash

   python -c "import whenever; print(whenever._EXTENSION_LOADED)"

.. note::

   If you're using Poetry or another third-party package manager,
   you should consult its documentation on opting out of binary wheels.

What about ``dateutil``?
~~~~~~~~~~~~~~~~~~~~~~~~

I haven't included it in the comparison since dateutil is more of an
*extension* to datetime, while *whenever* (and Pendulum and Arrow)
are more like replacements.

That said, here are my thoughts on dateutil: while it certainly provides
useful helpers (especially for parsing and arithmetic), it doesn't solve the
(IMHO) most glaring issues with the standard library: DST-safety and typing
for naive/aware. These are issues that only a full replacement can solve.

Why not simply wrap Rust's ``jiff`` library?
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Jiff is a modern datetime library in Rust with similar goals and inspiration as *whenever*.
There are several reasons that *whenever* doesn't simply wrap jiff though:

1. Jiff didn't exist when *whenever* was created. Wrapping jiff was only an
   option after most of the functionality was already implemented.
2. In order to provide a pure-Python version of *whenever*,
   jiff's logic would need to be re-implemented in Python--and kept in sync.
3. Jiff has a slightly different design philosophy, most notably
   de-emphasizing the difference between offset and zoned datetimes.
4. Jiff can't make use of Python's bundled timezone database (`tzdata`) if present.
5. Writing a rust library with Python bindings primarily in mind allows for
   some optimizations.

If you're interested in a straightforward wrapper around jiff,
check out `Ry <https://pypi.org/project/ry/>`_.

Why can't I subclass *whenever* classes?
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

*Whenever* classes aren't meant to be subclassed.
There's no plan to change this due to the following reasons:

1. The benefits of subclassing are limited.
   If you want to extend the classes, composition is a better way to do it.
   Alternatively, you can use Python's dynamic features to create
   something that behaves like a subclass.
2. For a class to support subclassing properly, a lot of extra work is needed.
   It also adds many subtle ways to misuse the API, that are hard to control.
3. Enabling subclassing would undo some performance optimizations.
