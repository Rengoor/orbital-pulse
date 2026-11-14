.PHONY: api ui reproduce test

setup-%:
	python -m venv $*/.venv
	$*/.venv/bin/pip install -r $*/requirements.txt

api:
	uvicorn backend.api.main:app --reload

ui:
	streamlit run frontend/app.py

reproduce:
	python -m evidence.run_all --seed 42

test:
	pytest backend/tests data/tests evidence -q
