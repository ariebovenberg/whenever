.PHONY: typecheck
typecheck: 
	mypy pysrc/ tests/
	pytest typesafety/

.PHONY: format
format:
	black pysrc/ tests/
	isort pysrc/ tests/

.PHONY: docs
docs:
	@touch docs/api.rst
	make -C docs/ html

.PHONY: check-dist
check-dist:
	maturin build --sdist
	twine check target/wheels/*

.PHONY: ci-lint
ci-lint: check-dist
	flake8 pysrc/ tests/
	black --check pysrc/ tests/
	isort --check pysrc/ tests/
	python -m slotscheck pysrc/
