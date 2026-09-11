# Timestamps floor at the requested unit

`timestamp(unit=)` returns the integer that labels the half-open bucket of
the requested unit containing the instant, so it floors. `from_timestamp()`
reads its argument the same way: an integer names a bucket, and a float is
floored to whole nanoseconds. Both backends compute this with their own epoch
arithmetic; the Python reference no longer delegates to
`datetime.fromtimestamp()`.

## Semantics

- `1969-12-31T23:59:59.999999999Z` has timestamp `-1` in seconds,
  milliseconds, microseconds, and nanoseconds; `1969-12-31T23:59:58.5Z` has
  timestamp `-2` in seconds.
- `from_timestamp(1.5e-9)` is one nanosecond after the epoch;
  `from_timestamp(-1.5e-9)` is two nanoseconds before it.
- A value outside `Instant.MIN..MAX` raises `ValueError`, on every platform.
  An integer far outside it may raise `OverflowError` instead, and the two
  backends need not agree on which; simplicity of implementation wins there.

## Considered options

- **Truncate toward zero**, as `int()` does to a negative float timestamp.
  Rejected: `-0.5` and `0.5` seconds would both map to `0`, so the integer
  would no longer identify a bucket, and `from_timestamp(x).timestamp()` would
  not be monotonic across the epoch.
- **Round a float to the nearest nanosecond**, as the stdlib rounds to the
  nearest microsecond. Rejected: the two directions would then follow
  different rules, and the last-bit behavior is harder to keep identical
  between Python and Rust than a floor is.
- **Keep delegating to `datetime.fromtimestamp()`** in Python. Rejected: its
  exception type varies by platform (`OSError` on Windows), and on Windows
  `Instant.MIN.timestamp()` could not be read back.

## Consequences

- Both directions follow Euclidean division, so `divmod` in Python and
  `div_euclid` in Rust are the whole implementation.
- The stdlib comparison is documented once, in the conversions guide.
