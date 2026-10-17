#!/usr/bin/env python3
"""Application workflow using the public ose-ctl CLI and reproducible inputs."""
import argparse
import base64
import json
import math
import os
from pathlib import Path
import socket
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]


def read(path):
    with Path(path).open() as stream:
        return json.load(stream)


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")


def framework(args):
    root = Path(args.framework_root or os.environ.get("FRAMEWORK_ROOT", ROOT / "deps/sdl-ose")).resolve()
    if not (root / "sdl/sdlc/generator.py").is_file() or not (root / "ose/src/ose/cli.py").is_file():
        raise ValueError("initialize deps/sdl-ose with git submodule update --init --recursive")
    return root


def environment(args):
    root = framework(args)
    return dict(os.environ, SDL_ROOT=str(root / "sdl"), PYTHONPATH=str(root / "ose/src"))


def cli(args, *arguments, **kwargs):
    return subprocess.run([sys.executable, "-m", "ose.cli", *map(str, arguments)],
                          cwd=ROOT, env=environment(args), check=True, **kwargs)


def finite(value, minimum, maximum, name, integer=False):
    if type(value) not in (int, float) or not math.isfinite(value) or not minimum <= value <= maximum:
        raise ValueError(f"invalid {name}")
    if integer and (type(value) is not int):
        raise ValueError(f"{name} must be an integer")
    return value


def prepare(args):
    if not args.scenario.replace("-", "").isalnum():
        raise ValueError("invalid scenario name")
    model = read(ROOT / "model.json")
    deployment = read(ROOT / f"deployment.{args.profile}.json")
    machines = read(ROOT / "config/machines.json")
    thresholds = read(ROOT / "config/thresholds.json")
    scenario = read(ROOT / "scenarios" / (args.scenario + ".json"))
    if any(document.get("version") != 1 for document in (machines, thresholds, scenario)):
        raise ValueError("application configurations require version 1")
    if any(set(document) != {"1", "2"} for document in
           (machines["machines"], thresholds["rms"], scenario["ramp_per_second"])):
        raise ValueError("configuration must describe machines 1 and 2")
    model["schemas"] = str(ROOT / "schemas")
    model["components"]["alarm"]["parameters"] = {"thresholds": thresholds["rms"]}
    for identity, machine in machines["machines"].items():
        number = int(identity)
        values = {
            "VW_MACHINE": number,
            "VW_SAMPLES": finite(machine["samples"], 1, 131072, "sample count", True),
            "VW_SEED": finite(machine["seed"], 1, 2**32 - 1, "seed", True),
            "VW_RATE": finite(machine["sample_rate_hz"], 1, 1e9, "sample rate"),
            "VW_FREQUENCY": finite(machine["frequency_hz"], 0, machine["sample_rate_hz"] / 2, "frequency"),
            "VW_AMPLITUDE": finite(machine["amplitude"], 0, 1e6, "amplitude"),
            "VW_NOISE": finite(machine["noise"], 0, 1e6, "noise"),
            "VW_RAMP": finite(scenario["ramp_per_second"][identity], 0, 1e6, "ramp"),
        }
        finite(thresholds["rms"][identity], 1e-12, 1e12, "threshold")
        deployment["components"][f"sensor_{number}"]["env"] = {k: str(v) for k, v in values.items()}
    for component in deployment["components"].values():
        component["container"]["handler"] = str(ROOT / component["container"]["handler"])
        component["cwd"] = str(ROOT)
    if args.profile == "cluster" and args.routing == "broker":
        deployment["subscriptions"] = {key: {"routing": "broker", "transport": "tcp"}
                                       for key in deployment.get("subscriptions", {})}
    destination = ROOT / "build/prepared"
    write(destination / "model.json", model)
    write(destination / "deployment.json", deployment)
    write(destination / "inputs.json", {"scenario": args.scenario, "profile": args.profile, "routing": args.routing})
    return destination


def compile_app(args, *, validate=False):
    prepared = prepare(args)
    options = ["validate" if validate else "build", "--model", prepared / "model.json",
               "--deployment", prepared / "deployment.json", "--build-dir", ROOT / "build"]
    if not validate and args.component:
        options += ["--component", args.component]
    cli(args, *options)


def terminate(process):
    if process.poll() is None:
        process.terminate()
    try:
        process.wait(timeout=6)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=3)


def distributed_local(args):
    args.profile = "cluster"
    compile_app(args)
    logs = ROOT / "build/distributed-logs"
    logs.mkdir(exist_ok=True)
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    processes, streams = {}, []
    command = [sys.executable, "-m", "ose.cli"]
    def launch(name, options):
        stream = (logs / (name + ".log")).open("ab")
        streams.append(stream)
        process = subprocess.Popen(command + options, cwd=ROOT, env=environment(args), stdout=stream, stderr=stream)
        processes[name] = process
        return process
    try:
        # Fresh logs keep observations from previous runs out of the demonstration.
        for path in logs.glob("*.log"):
            path.write_bytes(b"")
        launch("coordinator", ["serve", "--plan", "build/plan.json", "--port", str(port), "--insecure", "--lease-seconds", "2"])
        deadline = time.monotonic() + 10
        while True:
            if processes["coordinator"].poll() is not None:
                raise RuntimeError((logs / "coordinator.log").read_text())
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=.1):
                    break
            except OSError:
                if time.monotonic() >= deadline:
                    raise RuntimeError("coordinator startup timeout")
                time.sleep(.05)
        nodes = read(ROOT / "model.json")["components"]
        def start(name):
            return launch(name, ["worker", "--plan", "build/plan.json", "--node", name,
                                 "--port", str(port), "--insecure"])
        for name in nodes:
            start(name)
        initial_pids = {name: p.pid for name, p in processes.items()}
        status = None
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            result = cli(args, "cluster-status", "--port", port, "--insecure", capture_output=True, text=True)
            status = json.loads(result.stdout)
            if status["enabled"]:
                break
            time.sleep(.1)
        else:
            raise RuntimeError("workers did not become ready; inspect build/distributed-logs")
        started = time.monotonic()
        replaced = False
        while time.monotonic() - started < args.duration:
            if any(p.poll() is not None for p in processes.values()):
                raise RuntimeError("a distributed process exited; inspect build/distributed-logs")
            if args.fail_node and not replaced and time.monotonic() - started > args.duration / 2:
                if args.fail_node not in nodes:
                    raise ValueError("unknown fail-node")
                terminate(processes[args.fail_node])
                start(args.fail_node)
                replaced = True
            time.sleep(.05)
        result = cli(args, "cluster-status", "--port", port, "--insecure", capture_output=True, text=True)
        status = json.loads(result.stdout)
        write(ROOT / "build/distributed-status.json", status)
        write(ROOT / "build/distributed-processes.json", {"initial": initial_pids,
              "final": {name: p.pid for name, p in processes.items()}})
        print(json.dumps(status, indent=2))
    finally:
        for name, process in reversed(list(processes.items())):
            terminate(process)
        for stream in streams:
            stream.close()
        observer = logs / "observer.log"
        if observer.exists():
            print(observer.read_text(), file=sys.stderr, end="")


def certs(args):
    directory = ROOT / "build/pki"
    directory.mkdir(parents=True, exist_ok=True)
    os.chmod(directory, 0o700)
    def openssl(*options):
        subprocess.run(["openssl", *map(str, options)], check=True, capture_output=True)
    ca_key, ca_cert = directory / "ca.key", directory / "ca.crt"
    if not ca_key.exists():
        openssl("req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "365", "-subj", "/CN=vibration-watch-dev-ca",
                "-addext", "basicConstraints=critical,CA:TRUE", "-addext", "keyUsage=critical,keyCertSign,cRLSign",
                "-keyout", ca_key, "-out", ca_cert)
        os.chmod(ca_key, 0o600)
    extensions = directory / "leaf.ext"
    extensions.write_text("basicConstraints=critical,CA:FALSE\nkeyUsage=critical,digitalSignature,keyEncipherment\nextendedKeyUsage=serverAuth,clientAuth\nsubjectKeyIdentifier=hash\nauthorityKeyIdentifier=keyid,issuer\n")
    items = []
    for name in ["coordinator", *read(ROOT / "model.json")["components"]]:
        key, csr, cert = (directory / (name + suffix) for suffix in (".key", ".csr", ".crt"))
        if not cert.exists():
            openssl("req", "-newkey", "rsa:2048", "-nodes", "-subj", "/CN=" + name, "-keyout", key, "-out", csr)
            os.chmod(key, 0o600)
            openssl("x509", "-req", "-in", csr, "-CA", ca_cert, "-CAkey", ca_key, "-CAcreateserial", "-days", "365", "-extfile", extensions, "-out", cert)
        items.append({"apiVersion": "v1", "kind": "Secret", "type": "Opaque",
            "metadata": {"name": "ose-" + name.replace("_", "-") + "-tls", "namespace": args.namespace},
            "data": {field: base64.b64encode(path.read_bytes()).decode() for field, path in
                     (("ca.crt", ca_cert), ("tls.crt", cert), ("tls.key", key))}})
    destination = ROOT / "build/tls-secrets.json"
    write(destination, {"apiVersion": "v1", "kind": "List", "items": items})
    os.chmod(destination, 0o600)
    print(destination)


def images(args):
    if not args.registry:
        raise ValueError("pass --registry REGISTRY/PROJECT (for example registry.lan/vibration-watch)")
    if framework(args) != ROOT / "deps/sdl-ose":
        raise ValueError("images use the pinned deps/sdl-ose submodule; omit FRAMEWORK_ROOT")
    revision = subprocess.check_output(["git", "-C", str(ROOT / "deps/sdl-ose"), "rev-parse", "HEAD"], text=True).strip()[:12]
    if subprocess.check_output(["git", "-C", str(ROOT / "deps/sdl-ose"), "status", "--porcelain"], text=True).strip():
        raise ValueError("framework submodule must be clean before building release images")
    source_hash = sources_digest()
    published = {}
    for name in read(ROOT / "model.json")["components"]:
        image = f"{args.registry.rstrip('/')}/{name.replace('_', '-')}:{revision}-{source_hash[:12]}-{args.scenario}-{args.routing}"
        subprocess.run(["docker", "build", "-f", "packaging/Dockerfile", "--build-arg", "COMPONENT=" + name,
                        "--build-arg", "SCENARIO=" + args.scenario, "--build-arg", "ROUTING=" + args.routing,
                        "-t", image, "."], cwd=ROOT, check=True)
        if args.push:
            subprocess.run(["docker", "push", image], check=True)
            refs = json.loads(subprocess.check_output(["docker", "image", "inspect", image, "--format", "{{json .RepoDigests}}"], text=True))
            published[name] = next(ref for ref in refs if ref.split("@")[0] == image.rsplit(":", 1)[0])
    if args.push:
        published["coordinator"] = published["observer"]
        write(ROOT / "build/images.json", published)
        write(ROOT / "build/release.json", {"scenario": args.scenario, "routing": args.routing,
              "framework_revision": revision, "sources_sha256": source_hash})


def sources_digest():
    import hashlib
    content = hashlib.sha256()
    for folder in ("schemas", "components", "config", "scenarios", "tools", "packaging"):
        for path in sorted((ROOT / folder).rglob("*")):
            if path.is_file() and "__pycache__" not in path.parts:
                content.update(path.relative_to(ROOT).as_posix().encode() + b"\0" + path.read_bytes())
    for path in sorted(ROOT.glob("*.json")):
        content.update(path.name.encode() + b"\0" + path.read_bytes())
    return content.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("task", choices=("prepare", "validate", "build", "run", "simulate", "distributed-local", "certs", "images", "render"))
    parser.add_argument("--profile", choices=("local", "cluster"), default="local")
    parser.add_argument("--scenario", default="increasing-vibration")
    parser.add_argument("--routing", choices=("mixed", "broker"), default="mixed")
    parser.add_argument("--duration", type=float, default=3)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--component")
    parser.add_argument("--fail-node")
    parser.add_argument("--framework-root")
    parser.add_argument("--registry")
    parser.add_argument("--push", action="store_true")
    parser.add_argument("--namespace", default="vibration-watch")
    parser.add_argument("--image-pull-secret", action="append", default=[])
    args = parser.parse_args()
    try:
        finite(args.duration, 1e-6, 1e9, "duration")
        finite(args.workers, 1, 256, "workers", True)
        if args.task == "prepare":
            print(prepare(args))
        elif args.task in ("validate", "build"):
            compile_app(args, validate=args.task == "validate")
        elif args.task in ("run", "simulate"):
            args.profile = "local"
            compile_app(args)
            options = ["run", "--duration", args.duration]
            if args.task == "simulate":
                options += ["--mode", "simulated", "--workers", args.workers, "--trace", ROOT / "build/simulation.jsonl"]
            cli(args, *options)
        elif args.task == "distributed-local":
            distributed_local(args)
        elif args.task == "certs":
            certs(args)
        elif args.task == "images":
            images(args)
        elif args.task == "render":
            release = read(ROOT / "build/release.json")
            revision = subprocess.check_output(["git", "-C", str(framework(args)), "rev-parse", "HEAD"], text=True).strip()[:12]
            if release != {"scenario": args.scenario, "routing": args.routing, "framework_revision": revision,
                           "sources_sha256": sources_digest()}:
                raise ValueError("release images do not match these sources/configuration; rebuild and publish images")
            args.profile = "cluster"
            # Resolve the entire graph while building only the Python observer.
            args.component = "observer"
            compile_app(args)
            cli(args, "export-kubernetes", "--images", ROOT / "build/images.json", "--namespace", args.namespace,
                "--output", ROOT / "build/kubernetes.json",
                *(option for name in args.image_pull_secret for option in ("--image-pull-secret", name)))
            write(ROOT / "build/namespace.json", {"apiVersion": "v1", "kind": "Namespace", "metadata": {"name": args.namespace}})
    except (ValueError, KeyError, OSError, RuntimeError, subprocess.CalledProcessError) as error:
        print(f"vibration-watch: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
