PYTHON=python3

tests:
	$(PYTHON) -m tests.runner

run:
	@docker-compose up

scaleup:
	@echo $(AMOUNT)
