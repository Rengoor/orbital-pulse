# Convenience targets. Works with GNU make on macOS/Linux, and on Windows
# wherever make is available (Git Bash, MSYS2): the venv's binary directory is
# Scripts/ there instead of bin/. Without make, the README's plain commands do
# the same things.
.PHONY: api demo reproduce test redteam validate

VENV := backend/.venv
ifeq ($(OS),Windows_NT)
BIN := $(VENV)/Scripts
else
BIN := $(VENV)/bin
endif

setup-%:
	python -m venv $*/.venv
	$*/.venv/$(notdir $(BIN))/pip install -r $*/requirements.txt

api:
	SIGNING_KEY=$${SIGNING_KEY:-local-dev-signing-key} $(BIN)/uvicorn backend.api.main:create_app --factory --host 127.0.0.1 --port 8000 --reload

demo:
	$(BIN)/python run_demo.py

reproduce:
	SIGNING_KEY=$${SIGNING_KEY:-local-dev-signing-key} $(BIN)/python -m evidence.run_all --seed 42

test:
	SIGNING_KEY=$${SIGNING_KEY:-local-dev-signing-key} $(BIN)/pytest backend/tests data/tests evidence/tests validation/tests -q

redteam:
	SIGNING_KEY=$${SIGNING_KEY:-local-dev-signing-key} $(BIN)/python -m evidence.redteam.run_redteam

validate:
	SIGNING_KEY=$${SIGNING_KEY:-local-dev-signing-key} $(BIN)/python -m validation.run
