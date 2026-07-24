.PHONY: init
init:
	uv $(UV_ARGS) sync --frozen --all-groups

.PHONY: update
update:
	uv $(UV_ARGS) lock --upgrade

QUIET ?= 0
TEST_PATH ?= tests/

ifeq ($(QUIET),1)
.SILENT:
UV_ARGS := --quiet
DEFAULT_PYTEST_ARGS := -q --tb=short
DEFAULT_CARGO_ARGS := --quiet --message-format=short
MYPY_ARGS := --no-error-summary
RUFF_ARGS := --quiet
SLOTSCHECK_ARGS :=
SPHINXOPTS ?= -q
BUILD_ARGS := -q
RUST_BUILD_ARGS := --qbuild
DEFAULT_COV_REPORT_ARGS := --cov-report=term-missing:skip-covered --cov-report=html
DEFAULT_BENCH_PYTEST_ARGS := -q --benchmark-quiet
else
UV_ARGS :=
DEFAULT_PYTEST_ARGS := -s
DEFAULT_CARGO_ARGS :=
MYPY_ARGS :=
RUFF_ARGS :=
SLOTSCHECK_ARGS := -v
SPHINXOPTS ?=
BUILD_ARGS :=
RUST_BUILD_ARGS :=
DEFAULT_COV_REPORT_ARGS := --cov-report=term-missing --cov-report=html
DEFAULT_BENCH_PYTEST_ARGS := -s
endif

PYTEST_ARGS ?= $(DEFAULT_PYTEST_ARGS)
CARGO_ARGS ?= $(DEFAULT_CARGO_ARGS)
CLIPPY_ARGS ?= $(DEFAULT_CARGO_ARGS)
COV_REPORT_ARGS ?= $(DEFAULT_COV_REPORT_ARGS)
BENCH_PYTEST_ARGS ?= $(DEFAULT_BENCH_PYTEST_ARGS)

.PHONY: typecheck
typecheck:
	uv $(UV_ARGS) run mypy $(MYPY_ARGS) pysrc/ tests/

.PHONY: sync-docstrings
sync-docstrings:
	# --no-sync prevents rust rebuild, which fails on empty docstrings.rs
	uv $(UV_ARGS) run --no-sync python scripts/generate_docstrings.py > src/docstrings.rs

.PHONY: fix
fix:
	uv $(UV_ARGS) run --no-sync ruff check $(RUFF_ARGS) --select I --fix .
	uv $(UV_ARGS) run --no-sync ruff format $(RUFF_ARGS) .
	cargo fmt

.PHONY: docs
docs: clean-ext  # clean the extension since it messes with autodoc
	uv $(UV_ARGS) run --no-sync $(MAKE) --no-print-directory -C docs/ \
		SPHINXOPTS="$(SPHINXOPTS)" html

.PHONY: check-readme
check-readme:
	uv $(UV_ARGS) run python -m build $(BUILD_ARGS) --sdist
	uv $(UV_ARGS) run twine check dist/*

.PHONY: test-py
test-py:
	RUST_BACKTRACE=1 uv $(UV_ARGS) run pytest $(PYTEST_ARGS) $(TEST_PATH)

.PHONY: test-cov
test-cov: clean-ext
	RUST_BACKTRACE=1 uv $(UV_ARGS) run pytest $(PYTEST_ARGS) $(TEST_PATH) --cov=pysrc $(COV_REPORT_ARGS)


.PHONY: test-rs
test-rs:
	RUST_BACKTRACE=1 cargo test $(CARGO_ARGS)

.PHONY: test
test: test-py test-rs

.PHONY: ci-lint
ci-lint: check-readme
	uv $(UV_ARGS) lock --check
	uv $(UV_ARGS) run ruff check $(RUFF_ARGS) .
	uv $(UV_ARGS) run ruff format $(RUFF_ARGS) --check .
	cargo fmt -- --check
	# hash seed to ensure deterministic import order by slotscheck
	uv $(UV_ARGS) run env PYTHONPATH=pysrc/ PYTHONHASHSEED=3 slotscheck $(SLOTSCHECK_ARGS) pysrc
	cargo clippy $(CLIPPY_ARGS) --all-targets --all-features -- -D warnings

.PHONY: clean-ext
clean-ext:
	rm -f pysrc/whenever/*.so pysrc/whenever/*.dylib

.PHONY: clean
clean: clean-ext
	uv $(UV_ARGS) run python setup.py $(BUILD_ARGS) clean --all
	rm -rf build/ dist/ pysrc/**/__pycache__ *.egg-info **/*.egg-info \
		docs/_build/ htmlcov/ .mypy_cache/ .pytest_cache/ .ruff_cache/ \
		target/

.PHONY: build
build:
	uv $(UV_ARGS) run python setup.py $(BUILD_ARGS) build_rust $(RUST_BUILD_ARGS) --inplace

.PHONY: build-release
build-release:
	uv $(UV_ARGS) run python setup.py $(BUILD_ARGS) build_rust $(RUST_BUILD_ARGS) --inplace --release

.PHONY: bench
bench: build-release
	uv $(UV_ARGS) run pytest $(BENCH_PYTEST_ARGS) benchmarks/ \
		--benchmark-group-by=group \
		--benchmark-columns=median,stddev \
		--benchmark-autosave \
		--benchmark-group-by=fullname \

.PHONY: bench-compare
bench-compare:
	uv $(UV_ARGS) sync --locked --group benchmark
	$(MAKE) build-release
	uv $(UV_ARGS) run --no-sync --group benchmark benchmarks/comparison/run.sh

.PHONY: bench-compare-fast
bench-compare-fast:
	uv $(UV_ARGS) sync --locked --group benchmark
	$(MAKE) build-release
	uv $(UV_ARGS) run --no-sync --group benchmark benchmarks/comparison/run.sh --fast

.PHONY: bench-compare-docs
bench-compare-docs:
	uv $(UV_ARGS) sync --locked --group benchmark
	$(MAKE) build-release
	uv $(UV_ARGS) run --no-sync --group benchmark benchmarks/comparison/run.sh --update-docs
