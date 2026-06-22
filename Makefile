.PHONY: init
init:
	uv sync --frozen -v --all-groups

.PHONY: lint
update:
	uv lock --upgrade

.PHONY: typecheck
typecheck:
	uv run mypy pysrc/ tests/

.PHONY: fix
fix:
	uv run --no-sync ruff check --select I --fix .
	uv run --no-sync ruff format .
	cargo fmt

.PHONY: docs
docs: clean-ext  # clean the extension since it messes with autodoc
	uv run make -C docs/ html

.PHONY: check-readme
check-readme:
	uv run python -m build --sdist
	uv run twine check dist/*

.PHONY: test-py
test-py:
	RUST_BACKTRACE=1 uv run pytest -s tests/


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
	uv run env PYTHONPATH=pysrc/ slotscheck pysrc
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
bench-compare: build-release
	rm -f benchmarks/comparison/result_*.json
	uv run python benchmarks/comparison/run_stdlib_dateutil.py --fast -o \
		benchmarks/comparison/result_stdlib_dateutil.json
	uv run python benchmarks/comparison/run_pendulum.py --fast -o \
		benchmarks/comparison/result_pendulum.json
	uv run python benchmarks/comparison/run_arrow.py --fast -o \
		benchmarks/comparison/result_arrow.json
	uv run python benchmarks/comparison/run_whenever.py --fast -o \
		benchmarks/comparison/result_whenever.json
	uv run python -m pyperf compare_to benchmarks/comparison/result_stdlib_dateutil.json \
		benchmarks/comparison/result_pendulum.json \
		benchmarks/comparison/result_arrow.json \
		benchmarks/comparison/result_whenever.json \
		--table
