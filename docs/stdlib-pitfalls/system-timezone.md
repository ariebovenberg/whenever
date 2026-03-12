---
hide-toc: true
---

# Implicit system time zone

In the standard library,
converting to the system time zone is implicit--and often the default.
While this may be convenient in some cases,
it's hardly something you want to depend on in most applications.
In most cases, it's a surprise to developers when their code
suddenly depends on the system configuration.

For example, you may be surprised to learn that the output of these lines
depend on the system time zone:

```python
>>> datetime.fromtimestamp(t)  # returns a naive datetime in system tz
>>> my_datetime.astimezone(None)  # converts to system tz if no tz is given
>>> date.today()  # returns a date in the system tz
```

This implicit behavior makes it hard to see when code is depending on the system configuration.
Many applications do not need the system time zone at all—but can stumble into it accidentally.

Worse, the system time zone obtained this way is represented as a **fixed offset** or **naive**,
not a full set of rules.
That means the resulting datetime is not safe for arithmetic across DST transitions.

## How `whenever` solves this

Whenever makes converting to the system time zone an explicit operation,
and never assumes this intention implicitly.

This is the case when converting from a naive datetime:

```python
>>> from whenever import PlainDateTime
>>> dt = PlainDateTime(2024, 3, 10, 15, 0, 0)
>>> dt.assume_system_tz()
ZonedDateTime("2024-03-10 15:00:00-05:00[America/New_York]")
```

or when converting from a moment in time:

```python
>>> now = Instant.now()
>>> now.to_system_tz()
ZonedDateTime("2024-03-10 10:30:00-05:00[America/New_York]")
```

The resulting time zone always has the full knowledge of DST rules and historical changes,
making it safe for further operations.
