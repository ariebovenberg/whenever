❓ FAQ
======

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

.. _faq-why-system-tz:

Why does :class:`~whenever.SystemDateTime` exist?
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

While it may not make sense for server-type applications to use the system timezone,
it's often useful for CLI tools or desktop applications.

Using :class:`~whenever.SystemDateTime` has the following advantages:

- In contrast to :class:`~whenever.OffsetDateTime`, 
  :class:`~whenever.SystemDateTime` knows about the system's timezone changes,
  enabling DST-safe arithmetic.
- In contrast to :class:`~whenever.ZonedDateTime`, 
  :class:`~whenever.SystemDateTime` doesn't require the system be configured with an IANA timezone.
  While this is often the case, it's not guaranteed.

Of course, feel free to work with :class:`~whenever.ZonedDateTime` if
you know the system's IANA timezone. You can use
the `tzlocal <https://pypi.org/project/tzlocal/>`_ library to help with this.

.. _faq-leap-seconds:

Are leap seconds supported?
~~~~~~~~~~~~~~~~~~~~~~~~~~~

Leap seconds are unsupported.
Taking leap seconds into account is a complex and niche feature,
which is not needed for the vast majority of applications.
This decision is consistent with other modern libraries
(e.g. NodaTime, Temporal) and standards (RFC 5545, Unix time) which
do not support leap seconds.

Nonetheless, these improvements are possible in the future:

- Allow parsing of leap seconds, e.g. ``23:59:60``.
- Allow representation of leap seconds (similar to rust Chrono)

Why not adopt Rust's Chrono API?
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

I did consider this initially, but decided against it for the following reasons:

- While I love Rust's functional approach to error handling,
  it doesn't map well to idiomatic Python.
- At the time of writing, Chrono is only on version 0.4 and its API is still evolving.
- Chrono's timezone functionality can't handle disambiguation in gaps yet
  (see `this issue <https://github.com/chronotope/chrono/issues/1448>`_)

.. _faq-why-not-dropin:

Why isn't it a drop-in replacement for the standard library?
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

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
