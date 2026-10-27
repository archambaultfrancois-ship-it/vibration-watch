# Vibration Watch

A standalone SDL/OSE application: two synthetic C sensors, two Rust analyzers,
Python alarm policy and a Python terminal observer. Each signal block contains
16,384 float samples by default (64 KiB); results and alarm observations are small messages.
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

On Android/Termux, keep the host awake during real-time/distributed tests with
`termux-wake-lock`, then release it with `termux-wake-unlock` afterwards. Host
suspension expires worker leases by design.

The pinned framework (`cad7cba`, including typed shared parameter blocks) lives
in `deps/sdl-ose`; for framework development, set
`FRAMEWORK_ROOT=/absolute/path/to/sdl-ose`. Build artifacts and prepared absolute
paths live in `build/`. Rebuild after moving a checkout. The workflow uses the
public `python -m ose.cli` interface from the selected framework checkout.

For local development, initialize the pinned framework submodule, then load its
environment and shortcuts in each Bash terminal:

```sh
git submodule update --init --recursive
source ./setenv.sh
app-run
# In a second terminal, source ./setenv.sh again, then:
record
```

The application environment selects Vibration Watch as `OSE_APP_ROOT` and sources
`deps/sdl-ose/setenv.sh`, including when `FRAMEWORK_ROOT` was previously set to
another checkout. `app-run` builds and runs until Ctrl+C;
`app-run DURATION=60` limits the run. `record` prepares missing recording/filter
dependencies and opens the external console. `ose-env` lists the shortcuts.
`record-inspect FILE` displays all recorded messages; use `--limit N` to show
only the first N selected messages.
Recording content filters are evaluated at the source: in the broker for local
execution, or in each producer worker for distributed execution, before capture
queue admission and network delivery. Each recorder has independent filters.
Build the SDL filter service with `make -C deps/sdl-ose/sdl filter-python` using
the application's Python interpreter, then restart the application with the
updated framework. Cluster images build this service for their own interpreter;
rebuild and redeploy images after updating the framework submodule.

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

## Change settings while running

Each machine has two typed SDL parameter blocks:

| Path | Fields | Reader |
| --- | --- | --- |
| `machines/1/sensor`, `machines/2/sensor` | `samples`, `sample_rate_hz`, `frequency_hz`, `amplitude`, `noise`, `seed`, `ramp_per_second` | Corresponding C sensor |
| `machines/1/detection`, `machines/2/detection` | `rms_threshold` | Python alarm policy |

`config/machines.json`, `config/thresholds.json` and the selected signal profile
provide the initial values when building. The alarm and sensors read generated
typed bindings at every callback. Machine identity, graph, tick period and queue
policies remain deployment/model configuration.

Start `make run DURATION=60`, then use a second terminal in the application:

```sh
source ./setenv.sh
export OSE_PARAMETER_TOKEN='vibration-watch-local-operator'
ose-ctl parameters list --client operator
ose-ctl parameters get machines/1/detection --client operator
python3 tools/vibration.py set-threshold --machine 1 --rms-threshold 2.0
ose-ctl parameters watch machines/1/detection --client operator --count 2
```

The token above is the local development credential declared in
`deployment.local.json`. The `operator` client has read/write rights on these
four blocks; application components have read access only. To change a sensor,
retrieve its complete settings, edit the JSON, and submit the whole block:

```sh
ose-ctl parameters get machines/1/sensor --client operator > build/sensor-1.json
# Edit build/sensor-1.json, keeping all seven fields.
python3 tools/vibration.py set-sensor --machine 1 --file build/sensor-1.json
```

The application commands validate business constraints before submitting values:
1–131072 samples, a nonzero uint32 seed, sample rate 1–1e9 Hz, vibration frequency
0–half the sample rate, amplitude/noise/ramp 0–1e6 and RMS threshold 1e-12–1e12.
The generic `ose-ctl parameters set` checks SDL types; writers using that interface
must also respect these business constraints.

An update applies at a subsequent callback, without restarting the component.
Sensor changes affect the next generated block. Sample count changes resize its
buffer; a different seed resets only the noise generator. Sample index and sequence
continue. Frequency/rate changes may introduce a phase jump. Amplitude remains
`amplitude + ramp_per_second * elapsed OSE time`, including after a ramp change.
An alarm threshold change is used on subsequent analyses; it does not reclassify
previous observations. Updating one machine leaves the other machine's settings
unchanged. Writes replace complete blocks, and separate blocks do not change
atomically.

A replacement worker receives the current settings before starting. Values live
in broker/coordinator memory; restarting it restores the built initial values.
Captures contain signal messages, not parameter updates: replay uses the replay
plan's settings. Reproducing a session with changed settings requires supplying
those settings separately. Deterministic simulations can schedule complete block
updates using `ose-ctl run --mode simulated --scenario FILE`, as described in the
[framework parameter guide](deps/sdl-ose/ose/docs/parameters.md).

The same commands accept `--host`, `--port` and `--plan`; use
`--plan build/replay/plan.json --endpoint build/replay/endpoint.json` for a local
replay application (only detection blocks are retained there). Distributed clients
use `--distributed --tls-ca build/pki/ca.crt --tls-cert build/pki/operator.crt
--tls-key build/pki/operator.key` with an explicit host and port. `make certs`
generates the development operator credentials. Cluster access authenticates the
`operator` certificate identity; it does not use the local development token.
See [cluster deployment](deploy/README.md) for credentials and connectivity.

## Replay captured signals

The pinned framework provides `ose-ctl replay`. During framework development,
set `FRAMEWORK_ROOT=/absolute/path/to/sdl-ose` to select another checkout. In that
case, source that checkout's `setenv.sh` from the application directory instead
of the application environment below.

Start the application, then capture both sensors in another terminal using the
same framework and Python interpreter:

```sh
make run DURATION=60
# Second terminal, from the application directory:
source ./setenv.sh
record --command 'select sensor_1.signal sensor_2.signal' \
  --command 'start signals.pcapng' --command 'wait 2' --command stop
```

Replay the signals through the Rust analyzers, Python alarm policy and observer:

```sh
make replay RECORDING=signals.pcapng DURATION=3 WORKERS=4
make replay RECORDING=signals.pcapng DURATION=6 LOOPS=2
make test-replay
```

`replay` builds a separate model under `build/replay/`: the C sensors are removed
and their subscriptions are connected to external topics. The workflow invokes
`ose-ctl replay` with `sensor_1.signal=replay.signal_1` and
`sensor_2.signal=replay.signal_2`. It accepts PCAPNG or MCAP captures; both sensor
topics must contain messages. `tools/vibration.py replay --recording FILE`
also accepts `--start-ns` and `--end-ns` for a recorded log-time range.
`LOOPS` (CLI: `--loops`) is the total number of passes, defaulting to 1; 0 repeats
until the global `DURATION` limit. Components retain state between passes, and
payload timestamps and sequence numbers are preserved.

The first selected message becomes virtual time zero; recorded intervals and
payloads are preserved. `DURATION` is the virtual horizon from that origin;
choose it long enough to cover the selected capture. Terminal observations are
recomputed from the samples, including the original payload sequence numbers
and timestamps. The logical trace is saved as `build/replay/trace.jsonl`.

For live replay, build the model without sensors and start it separately:

```sh
make replay-build
ose-ctl run --plan build/replay/plan.json
# In a second terminal with the same framework environment:
ose-ctl replay signals.pcapng --mode realtime --plan build/replay/plan.json \
  --map sensor_1.signal=replay.signal_1 --map sensor_2.signal=replay.signal_2 \
  --speed 1 --interactive
```

Use `speed 0.5`, `speed 2`, `pause`, `resume`, `status` and `stop` in the replay
console. Speed 0 runs as quickly as admission permits. Application timestamps
stay unchanged; changing playback speed changes the spacing between publications.
For a scripted session, replace `--interactive` with repeated options such as
`--command 'speed 2' --command 'wait 3' --command status --command stop`.
Commands run in order; `wait` uses wall time, and the end of the script stops
replay. A capture that finishes earlier cancels the remaining commands.
Add `--loops N` for N passes or `--loops 0` for continuous live replay. In the
latter case, commands, signals or an optional global `--duration` stop playback.

`make replay-build PROFILE=cluster` builds the four-worker distributed version.
Start its coordinator and workers using `build/replay/plan.json`, as described
in the [framework's distributed guide](deps/sdl-ose/ose/docs/distributed.md).
Feed it with the same replay command plus `--host HOST --port PORT` and the TLS
credentials of a client certificate named `replay`. For a loopback development
cluster, use `--host 127.0.0.1 --port 7000 --insecure`. External signal routes use
the coordinator. Live replay uses the running application's state and ordinary
queue policies; increasing speed can cause `drop_oldest` to discard inputs if
the consumers cannot keep up. Check runtime counters when selecting a rate.

`make test-replay` prepares the optional recording dependency, captures a live
two-second signal sequence, and checks that replay reproduces every corresponding
live observation, including RMS, peak and alarm state. It compares simulation
traces from one and four workers, then checks live local and distributed replay.
This test uses temporary captures; it does not consume
existing recordings or require a cluster. It is separate from `make test` so the
ordinary suites keep their standard-library-only Python requirements.

## Cluster deployment

See [deployment instructions](deploy/README.md) and [architecture](docs/architecture.md).
The image build compiles one component per image, with its generated container,
SDL runtime, native recording filter service and OSE adapter. Cluster images are referenced by digest.
Distributed execution is real time; deterministic simulation remains local.

No images are published and no cluster is modified by `make test`.
The GitHub workflow runs the same checks. If the framework repository is private,
configure a read-only `FRAMEWORK_ACCESS_TOKEN` that can fetch its pinned revision.
