PYTHON ?= python3

.PHONY: test syntax self-test e2e

test: syntax self-test e2e

syntax:
	$(PYTHON) -c "from pathlib import Path; [compile(path.read_text(), str(path), 'exec') for path in [*Path('lib/python/pr_artifacts').glob('*.py'), *Path('tests').glob('*.py')]]; print('syntax ok')"

self-test:
	PYTHONPATH=lib/python/pr_artifacts $(PYTHON) lib/python/pr_artifacts/publish_pr_artifact.py --self-test

e2e:
	PYTHONPATH=lib/python/pr_artifacts $(PYTHON) tests/test_publish_pr_artifact.py
