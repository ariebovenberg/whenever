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

- I purposefully opted for ``pyo3_ffi`` over ``pyo3``. See the FAQ for the
  rationale.
- The Rust code contains a lot of unsafe code. This is because it
  mostly interacts with C code (Python's C API), which is inherently unsafe.
  It's planned to refactor the code to use safer abstractions. However,
  there will always be awkward cases since Python and Rust's memory model is
  different.
- The tests and documentation of the Rust code are sparse. This is because
  it has no public interface and is only used through its Python bindings.
  You can find comprehensive tests and documentation in the Python codebase.
- To keep import time fast, some "obvious" Python modules (pathlib, re,
  importlib.resources) are not used, or imported lazily.
