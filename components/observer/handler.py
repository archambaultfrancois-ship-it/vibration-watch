import json
import sys


def on_input(ctx, message):
    print(json.dumps({"event": "vibration", "machine_id": message.machine_id,
        "sequence": message.sequence, "time_ns": message.time_ns,
        "rms": message.rms, "peak": message.peak, "state": message.state}), file=sys.stderr, flush=True)
