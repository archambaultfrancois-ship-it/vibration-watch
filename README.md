# Vibration Watch

A standalone SDL/OSE application: two synthetic C sensors, two Rust analyzers,
Python alarm policy and a Python terminal observer. Each signal block contains
16,384 float samples (64 KiB); results and alarm observations are small messages.
The sensor uses the OSE clock and a seeded generator, so simulation is reproducible.

## Requirements and first run

Python 3.10+, a C99 compiler, Rust/Cargo and Git. OpenSSL is needed to generate
development TLS certificates. No Python third-party runtime packages are required.

```sh
git submodule update --init --recursive
make validate
make demo-local DURATION=3
make simulate WORKERS=4 DURATION=2
make test
```

The pinned framework lives in `deps/sdl-ose`; for framework development, set
`FRAMEWORK_ROOT=/absolute/path/to/sdl-ose`. Build artifacts and prepared absolute
paths live in `build/`. Rebuild after moving a checkout. The workflow uses the
public `python -m chain_env.cli` interface from the selected framework checkout.

The `normal` scenario keeps both motors below their RMS thresholds. The default
`increasing-vibration` profile raises motor 1's amplitude with elapsed OSE time;
it crosses the 1 m/s² RMS threshold while motor 2 stays normal. These are
application signal-generation profiles, not OSE external-message scenario files.

```sh
make simulate SCENARIO=normal
make demo-distributed DURATION=8 FAIL_NODE=analyzer_1
make demo-distributed DURATION=3 ROUTING=broker
```

The distributed local demonstration launches a coordinator and six independent
worker processes over TCP. It uses explicit loopback-only plaintext mode.
`FAIL_NODE` terminates and replaces that worker; survivor PIDs remain unchanged.
Logs, counters and before/after PIDs are saved under `build/`. This exercises
the distributed protocol without claiming to test a physical node outage.

## Project resources

- `schemas/`: contracts and units; `vibration_signal.sdl` avoids shadowing Python's `signal` module.
- `components/`: reusable business implementations plus thin OSE handlers.
- `config/`: machine definitions, block sizes, seeds and thresholds.
- `model.json`: ports, graph, triggers and bounded QoS.
- `deployment.local.json`: ordinary OSE execution through the broker.
- `deployment.cluster.json`: distributed execution, direct signal routes, broker results and placement resources.
- `scenarios/`: deterministic profiles; `tests/`: business, end-to-end and opt-in cluster tests.
- `packaging/` and `deploy/`: image construction and cluster deployment instructions.

The alarm inputs are independent and optional: losing one motor's branch does
not stall the other. Every analysis produces an observation with state 0 or 1;
this application does not retain an alarm history or implement debouncing.

## Cluster deployment

See [deployment instructions](deploy/README.md) and [architecture](docs/architecture.md).
The image build compiles one component per image, with its generated container,
SDL runtime and OSE adapter. Cluster images are referenced by digest.
Distributed execution is real time; deterministic simulation remains local.

No images are published and no cluster is modified by `make test`.
The GitHub workflow runs the same checks. If the framework repository is private,
configure a read-only `FRAMEWORK_ACCESS_TOKEN` that can fetch its pinned revision.
