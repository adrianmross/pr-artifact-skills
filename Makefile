PYTHON ?= python3
VERSION ?= v$(shell cat VERSION)

.PHONY: test ci syntax self-test e2e minio-integration plugin-validate skills-list shellcheck package

test: syntax self-test e2e minio-integration

ci: test plugin-validate skills-list shellcheck package

syntax:
	$(PYTHON) -c "from pathlib import Path; [compile(path.read_text(), str(path), 'exec') for path in [*Path('lib/python/pr_artifacts').glob('*.py'), *Path('tests').glob('*.py')]]; print('syntax ok')"

self-test:
	PYTHONPATH=lib/python/pr_artifacts $(PYTHON) lib/python/pr_artifacts/publish_pr_artifact.py --self-test

e2e:
	PYTHONPATH=lib/python/pr_artifacts $(PYTHON) tests/test_publish_pr_artifact.py

minio-integration:
	PYTHONPATH=lib/python/pr_artifacts $(PYTHON) tests/test_minio_integration.py

plugin-validate:
	./scripts/validate-plugin.sh

skills-list:
	npx skills add . --list --full-depth --yes

shellcheck:
	shellcheck scripts/*.sh

package:
	./scripts/package-release.sh $(VERSION)
