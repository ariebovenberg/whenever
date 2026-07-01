.PHONY: init
init:
	uv sync --frozen -v --all-groups

.PHONY: lint
update:
	uv lock --upgrade

.PHONY: typecheck
typecheck:
	uv run mypy pysrc/ tests/

.PHONY: sync-docstrings
sync-docstrings:
	# --no-sync prevents rust rebuild, which fails on empty docstrings.rs
	uv run --no-sync python scripts/generate_docstrings.py > src/docstrings.rs

.PHONY: fix
fix:
	uv run --no-sync ruff check --select I --fix .
	uv run --no-sync ruff format .
	cargo fmt

.PHONY: docs
docs: clean-ext  # clean the extension since it messes with autodoc
	uv run --no-sync $(MAKE) -C docs/ html

.PHONY: check-readme
check-readme:
	uv run python -m build --sdist
	uv run twine check dist/*

.PHONY: test-py
test-py:
	RUST_BACKTRACE=1 uv run pytest -s tests/

.PHONY: test-cov
test-cov: clean-ext
	RUST_BACKTRACE=1 uv run pytest -s tests/ --cov=pysrc --cov-report=term-missing --cov-report=html


.PHONY: test-rs
test-rs:
	RUST_BACKTRACE=1 cargo test

.PHONY: test
test: test-py test-rs

.PHONY: ci-lint
ci-lint: check-readme
	uv run ruff check .
	uv run ruff format --check .
	cargo fmt -- --check
	uv run env PYTHONPATH=pysrc/ slotscheck -v pysrc
	cargo clippy --all-targets --all-features -- -D warnings

.PHONY: clean-ext
clean-ext:
	rm -f pysrc/whenever/*.so pysrc/whenever/*.dylib

.PHONY: clean
clean: clean-ext
	uv run python setup.py clean --all
	rm -rf build/ dist/ pysrc/**/__pycache__ *.egg-info **/*.egg-info \
		docs/_build/ htmlcov/ .mypy_cache/ .pytest_cache/ .ruff_cache/ \
		target/

.PHONY: build
build:
	uv run python setup.py build_rust --inplace

.PHONY: build-release
build-release:
	uv run python setup.py build_rust --inplace --release

.PHONY: bench
bench: build-release
	uv run pytest -s benchmarks/ \
		--benchmark-group-by=group \
		--benchmark-columns=median,stddev \
		--benchmark-autosave \
		--benchmark-group-by=fullname \

.PHONY: bench-compare
bench-compare:
	uv sync --locked --group benchmark
	$(MAKE) build-release
	uv run --no-sync --group benchmark benchmarks/comparison/run.sh

.PHONY: bench-compare-fast
bench-compare-fast:
	uv sync --locked --group benchmark
	$(MAKE) build-release
	uv run --no-sync --group benchmark benchmarks/comparison/run.sh --fast

.PHONY: bench-compare-docs
bench-compare-docs:
	uv sync --locked --group benchmark
	$(MAKE) build-release
	uv run --no-sync --group benchmark benchmarks/comparison/run.sh --update-docs
