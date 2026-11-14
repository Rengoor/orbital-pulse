.PHONY: api ui reproduce test

setup-%:
	python -m venv $*/.venv
	$*/.venv/bin/pip install -r $*/requirements.txt

api:
	SIGNING_KEY=$${SIGNING_KEY:-local-dev-signing-key} backend/.venv/bin/uvicorn backend.api.main:create_app --factory --host 127.0.0.1 --port 8000 --reload

ui:
	backend/.venv/bin/python -m frontend.app

reproduce:
	backend/.venv/bin/python -m evidence.run_all --seed 42

test:
	backend/.venv/bin/pytest backend/tests data/tests evidence -q
