# Contributing

## Before you start

Contributions are welcome, but be sure to read the guidelines below first.

- Non-trivial changes should be discussed in an issue first.
  This is to avoid wasted effort if the change isn't a good fit for the project.

- Before picking up an issue, please comment on it to let others know you're working on it.
  This will help avoid duplicated effort.

- Some tests are skipped on Windows.
  These tests use unix-specific features to set the timezone for the current process.
  As a result, Windows isn't able to run certain tests that rely on the system timezone.
  It appears that this functionality (only needed for the tests) is
  [not available on Windows](https://stackoverflow.com/questions/62004265/python-3-time-tzset-alternative-for-windows).

## Setting up a development environment

An example of setting up things up on a Unix-like system:

```bash
# install the dependencies
make init

# build the rust extension
make build

make test  # run the tests (Python and Rust)
make format  # apply autoformatting
make ci-lint  # various static checks
make typecheck  # run mypy and typing tests
```

## Maintainer's notes

Below are some points to keep in mind when making changes to the codebase:

- I purposefully opted for ``pyo3_ffi`` over ``pyo3``. There are two main reasons:

    1. The higher-level binding library PyO3 has a small additional overhead for function calls,
       which can be significant for small functions. Whenever has a lot of small functions.
       Only with ``pyo3_ffi`` can these functions be on par (or faster) than the standard library.
       The overhead has decreased in recent versions of PyO3, but it's still there.
    2. I was eager to learn to use the bare C API of Python, in order to better
       understand how Python extension modules and PyO3 work under the hood.
    3. ``whenever``'s use case is quite simple: it only contains immutable data types
       with small methods. It doesn't need the full power of PyO3.

    Additional advantages of ``pyo3_ffi`` are:

    - Its API is more stable than PyO3's, which is still evolving.
    - It allows support for per-interpreter GIL, and free-threaded Python,
      which are not yet (fully) supported by PyO3.

- The tests and documentation of the Rust code are sparse. This is because
  it has no public interface and is only used through its Python bindings.
  You can find comprehensive tests and documentation in the Python codebase.
- To keep import time fast, some "obvious" Python modules (pathlib, re, dataclasses,
  importlib.resources) are not used, or imported lazily.
