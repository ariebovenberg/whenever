.PHONY: build-dev
build-dev:
	maturin develop --extras test


.PHONY: test
test: build-dev
	pytest

.PHONY: mypy
mypy: build-dev
	mypy py/ tests/

.PHONY: format
format:
	black py/ tests/
	isort py/ tests/
	cargo fmt

.PHONY: docs
docs: build-dev
	@touch docs/api.rst
	make -C docs/ html
