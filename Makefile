PY ?= python

.PHONY: help data verify test eval uplift-report serve ui ui-install all clean

help:
	@echo "data           regenerate the world and the historical exploration log"
	@echo "verify         check the generator property gates"
	@echo "test           run the test suite"
	@echo "eval           run the full three-arm evaluation, write eval/results/"
	@echo "uplift-report  print the fitted uplift table and p_natural coefficients"
	@echo "serve          start the API on :8000"
	@echo "ui             start the UI dev server on :5173"
	@echo "all            data -> verify -> test -> eval"
	@echo ""
	@echo "No make on this machine? Every target above also works as:"
	@echo "    python run.py <target>"

data:
	$(PY) -m data.generator

verify:
	$(PY) -m data.verify_world

test:
	$(PY) -m pytest tests/ -q

eval:
	$(PY) -m eval.run_eval

uplift-report:
	$(PY) -c "from agent.uplift import fit_from_history; print(fit_from_history().report())"

serve:
	$(PY) -m uvicorn api.main:app --reload --port 8000

ui-install:
	cd ui && npm install

ui:
	cd ui && npm run dev

all: data verify test eval

clean:
	rm -rf __pycache__ */__pycache__ */*/__pycache__ .pytest_cache
