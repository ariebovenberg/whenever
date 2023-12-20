.PHONY: test
test:
	pytest -s

.PHONY: mypy
mypy: 
	mypy src/ tests/

.PHONY: format
format:
	black src/ tests/
	isort src/ tests/

.PHONY: lint
lint:
	flake8 src/ tests/

.PHONY: docs
docs:
	@touch docs/api.rst
	make -C docs/ html
