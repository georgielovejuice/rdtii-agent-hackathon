.PHONY: install ollama-setup run-ui run-thailand run-vietnam run-singapore run-all run-thailand-llm run-vietnam-llm run-singapore-llm run-all-llm test clean

install:
	pip install -r requirements.txt
	playwright install chromium

ollama-setup:
	ollama pull llama3.1:8b

run-ui:
	streamlit run app.py

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
	OLLAMA_MODEL=llama3.1:8b python main.py --country thailand --pillars 6 7

run-vietnam-llm:
	OLLAMA_MODEL=llama3.1:8b python main.py --country vietnam --pillars 6 7

run-singapore-llm:
	OLLAMA_MODEL=llama3.1:8b python main.py --country singapore --pillars 6 7

run-all-llm:
	OLLAMA_MODEL=llama3.1:8b python main.py --country thailand --pillars 6 7
	OLLAMA_MODEL=llama3.1:8b python main.py --country vietnam --pillars 6 7
	OLLAMA_MODEL=llama3.1:8b python main.py --country singapore --pillars 6 7

test:
	pytest tests/ -v

clean:
	rm -rf outputs/ __pycache__ pipeline/__pycache__
