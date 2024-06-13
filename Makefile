.PHONY: init
init:
	pip install -U pip setuptools-rust build twine build pyperf
	pip install -r requirements/all.txt
	pip install -e .

.PHONY: typecheck
typecheck:
	mypy pysrc/ tests/
	pytest typesafety/

.PHONY: format
format:
	black pysrc/ tests/
	isort pysrc/ tests/
	cargo fmt

.PHONY: docs
docs:
	rm -f pysrc/whenever/*.so  # Presence of the rust extension breaks sphinx (TODO: a better workaround)
	@touch docs/api.rst  # force rebuild of API docs: code changes aren't detected
	make -C docs/ html

.PHONY: check-readme
check-readme:
	python -m build --sdist
	twine check dist/*

.PHONY: test-py
test-py:
	RUST_BACKTRACE=1 pytest -s tests/


.PHONY: test-rs
test-rs:
	RUST_BACKTRACE=1 cargo test

.PHONY: test
test: test-py test-rs

.PHONY: ci-lint
ci-lint: check-readme
	flake8 pysrc/ tests/
	black --check pysrc/ tests/
	isort --check pysrc/ tests/
	cargo fmt -- --check
	env PYTHONPATH=pysrc/ slotscheck pysrc
	cargo clippy -- -D warnings

.PHONY: clean
clean:
	python setup.py clean --all
	rm -rf build/ dist/ pysrc/**/*.so pysrc/**/__pycache__ *.egg-info **/*.egg-info \
		docs/_build/ htmlcov/ .mypy_cache/ .pytest_cache/ target/


.PHONY: build
build:
	python setup.py build_rust --inplace

.PHONY: build-release
build-release:
	python setup.py build_rust --inplace --release

.PHONY: bench
bench: build-release
	pytest -s benchmarks/ \
		--benchmark-group-by=group \
		--benchmark-columns=median,stddev \
		--benchmark-autosave \
		--benchmark-group-by=fullname \

.PHONY: bench-compare
bench-compare: build-release
	rm -f benchmarks/comparison/result_*.json
	python benchmarks/comparison/run_stdlib_dateutil.py --fast -o \
		benchmarks/comparison/result_stdlib_dateutil.json
	python benchmarks/comparison/run_pendulum.py --fast -o \
		benchmarks/comparison/result_pendulum.json
	python benchmarks/comparison/run_arrow.py --fast -o \
		benchmarks/comparison/result_arrow.json
	python benchmarks/comparison/run_whenever.py --fast -o \
		benchmarks/comparison/result_whenever.json
	python -m pyperf compare_to benchmarks/comparison/result_stdlib_dateutil.json \
		benchmarks/comparison/result_pendulum.json \
		benchmarks/comparison/result_arrow.json \
		benchmarks/comparison/result_whenever.json \
		--table
