PYTHON ?= python3
SCENARIO ?= increasing-vibration
DURATION ?= 3
WORKERS ?= 4
LOOPS ?= 1
ROUTING ?= mixed
PROFILE ?= local
NAMESPACE ?= vibration-watch
OPTIONS = --scenario "$(SCENARIO)" --duration "$(DURATION)" --workers "$(WORKERS)" --routing "$(ROUTING)"

.PHONY: validate build run simulate replay replay-build demo-local demo-distributed test test-unit test-integration test-replay test-cluster certs images push-images render deploy help
validate build run simulate:
	$(PYTHON) tools/vibration.py $@ $(OPTIONS)
replay:
	$(PYTHON) tools/vibration.py replay --recording "$(RECORDING)" --loops "$(LOOPS)" $(OPTIONS)
replay-build:
	$(PYTHON) tools/vibration.py replay-build --profile "$(PROFILE)" $(OPTIONS)
demo-local: run
demo-distributed:
	$(PYTHON) tools/vibration.py distributed-local $(OPTIONS) $(if $(FAIL_NODE),--fail-node "$(FAIL_NODE)")
test: test-unit test-integration
test-unit:
	$(PYTHON) -m unittest discover -s tests/unit -v
	mkdir -p build/tests
	rustc --edition 2021 --test components/analyzer/math.rs -o build/tests/analyzer
	build/tests/analyzer
	$(CC) -std=c99 -Wall -Wextra -Werror tests/unit/signal.c -lm -o build/tests/signal
	build/tests/signal
test-integration:
	$(PYTHON) -m unittest discover -s tests/integration -v
test-replay:
	$(PYTHON) tools/vibration.py recording-deps
	$(PYTHON) -m unittest discover -s tests/replay -v
test-cluster:
	$(PYTHON) -m unittest discover -s tests/cluster -v
certs:
	$(PYTHON) tools/vibration.py certs --namespace "$(NAMESPACE)"
images:
	$(PYTHON) tools/vibration.py images --registry "$(REGISTRY)" --scenario "$(SCENARIO)" --routing "$(ROUTING)"
push-images:
	$(PYTHON) tools/vibration.py images --registry "$(REGISTRY)" --scenario "$(SCENARIO)" --routing "$(ROUTING)" --push
render:
	$(PYTHON) tools/vibration.py render --namespace "$(NAMESPACE)" $(OPTIONS) $(if $(IMAGE_PULL_SECRET),--image-pull-secret "$(IMAGE_PULL_SECRET)")
deploy: render certs
	kubectl apply -f build/namespace.json
	kubectl apply -f build/tls-secrets.json
	kubectl apply -f build/kubernetes.json
help:
	@echo 'make validate build run simulate demo-distributed test'
	@echo 'make replay RECORDING=signals.pcapng DURATION=3; make test-replay'
	@echo 'make replay-build PROFILE=local (or cluster), then ose-ctl replay --mode realtime'
	@echo 'make demo-distributed FAIL_NODE=analyzer_1 DURATION=8'
	@echo 'make push-images REGISTRY=registry.lan/vibration-watch'
	@echo 'make deploy (requires Kubernetes access and published images)'
