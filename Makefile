PYTHON ?= python3
VENV ?= .venv
PIP := $(VENV)/bin/pip
PY := $(VENV)/bin/python

.PHONY: install synth deploy destroy ingest check

install:
	$(PYTHON) -m venv $(VENV)
	$(PIP) install --upgrade pip
	$(PIP) install -r requirements.txt -r infrastructure/requirements.txt

synth:
	cd infrastructure && cdk synth

deploy:
	bash scripts/deploy.sh

destroy:
	bash scripts/destroy.sh

ingest:
	bash scripts/ingest.sh

check:
	$(PY) -m compileall agents knowledge_base tools runtime evaluation infrastructure/stacks
