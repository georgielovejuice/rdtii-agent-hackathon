.PHONY: install ollama-setup run-thailand run-vietnam run-singapore run-all run-thailand-llm run-vietnam-llm run-singapore-llm run-all-llm test clean

install:
	pip install -r requirements.txt
	playwright install chromium

ollama-setup:
	ollama pull qwen2.5:3b

run-thailand:
	python main.py --country thailand --pillars 6 7

run-vietnam:
	python main.py --country vietnam --pillars 6 7

run-singapore:
	python main.py --country singapore --pillars 6 7

run-all:
	python main.py --country thailand --pillars 6 7
	python main.py --country vietnam --pillars 6 7
	python main.py --country singapore --pillars 6 7

run-thailand-llm:
	LLM_BACKEND=ollama python main.py --country thailand --pillars 6 7

run-vietnam-llm:
	LLM_BACKEND=ollama python main.py --country vietnam --pillars 6 7

run-singapore-llm:
	LLM_BACKEND=ollama python main.py --country singapore --pillars 6 7

run-all-llm:
	LLM_BACKEND=ollama python main.py --country thailand --pillars 6 7
	LLM_BACKEND=ollama python main.py --country vietnam --pillars 6 7
	LLM_BACKEND=ollama python main.py --country singapore --pillars 6 7

test:
	pytest tests/ -v

clean:
	rm -rf outputs/ __pycache__ pipeline/__pycache__
