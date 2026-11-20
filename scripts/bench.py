#!/usr/bin/env python3
import argparse
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager, nullcontext
from datetime import datetime, timezone
import json
from math import ceil
from pathlib import Path
import socket
import subprocess
from tempfile import TemporaryDirectory
from threading import Event, Thread
import time
from urllib.parse import parse_qsl, urlsplit


ORIGIN = "https://speed.cloudflare.com/__down?bytes="


def request(size, proxy):
    args = ["curl", "-fsS", "--max-time", "15", "-o", "/dev/null",
            "-w", "%{http_code} %{size_download} %{time_total}"]
    args += ["--noproxy", "", "--proxy", proxy] if proxy else ["--noproxy", "*"]
    result = subprocess.run(args + [ORIGIN + str(size)], capture_output=True, text=True)
    fields = result.stdout.split()
    if result.returncode != 0 or len(fields) != 3 or fields[:2] != ["200", str(size)]:
        return None
    return float(fields[2]) * 1000


def pct(values, q):
    return round(sorted(values)[ceil(q * len(values)) - 1], 2) if values else None


def resources(cgroup):
    cpu = dict(line.split() for line in (cgroup / "cpu.stat").read_text().splitlines())
    return time.monotonic(), int(cpu["usage_usec"]), int((cgroup / "memory.current").read_text())


def measure(count, size, waves, proxy, cgroup):
    stop = Event()
    ready = Event()
    latency, samples = [], []

    def probe():
        ready.set()
        while not stop.is_set():
            latency.append((request(1024, proxy), time.monotonic()))
            stop.wait(.12)

    def sample():
        while not stop.is_set():
            samples.append(resources(cgroup))
            stop.wait(.2)

    sampler = Thread(target=sample)
    prober = Thread(target=probe)
    sampler.start()
    prober.start()
    ready.wait()
    start = time.monotonic()
    downloads = []
    try:
        with ThreadPoolExecutor(count) as pool:
            for _ in range(waves):
                downloads.extend(pool.map(lambda _: request(size, proxy), range(count)))
    finally:
        end = time.monotonic()
        elapsed = end - start
        stop.set()
        sampler.join()
        prober.join()
    samples.append(resources(cgroup))
    completed_probes = [value for value, finished in latency if start <= finished <= end]
    during = [value for value in completed_probes if value is not None]
    done = sum(x is not None for x in downloads)
    cpu = [(b[1] - a[1]) / ((b[0] - a[0]) * 10000)
           for a, b in zip(samples, samples[1:]) if b[0] - a[0] >= .15]
    return {
        "mode": "tunnel" if proxy else "direct", "parallel": count,
        "duration_s": round(elapsed, 3), "bytes": done * size,
        "download_errors": len(downloads) - done,
        "mbps": round(done * size * 8 / elapsed / 1e6, 2),
        "latency_samples": len(during), "latency_errors": completed_probes.count(None),
        "p50_ms": pct(during, .50), "p95_ms": pct(during, .95),
        "server_cpu_peak_pct": round(max(cpu), 2) if cpu else None,
        "server_ram_peak_mib": round(max(x[2] for x in samples) / 2**20, 2),
    }


@contextmanager
def loopback_client(profile, container):
    url = urlsplit(profile.read_text().strip())
    opts = dict(parse_qsl(url.query))
    if url.scheme != "vless" or opts.get("type") != "xhttp" or opts.get("security") != "reality":
        raise ValueError("для --profile нужен профиль VLESS/XHTTP/REALITY")
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    config = {
        "log": {"loglevel": "warning", "access": "none"},
        "inbounds": [{"listen": "127.0.0.1", "port": port, "protocol": "socks"}],
        "outbounds": [{"protocol": "vless", "settings": {"vnext": [{
            "address": "127.0.0.1", "port": url.port,
            "users": [{"id": url.username, "encryption": opts.get("encryption", "none")}],
        }]}, "streamSettings": {
            "network": "xhttp", "security": "reality",
            "xhttpSettings": {"path": opts["path"], "mode": opts["mode"]},
            "realitySettings": {"serverName": opts["sni"], "fingerprint": opts["fp"],
                                "password": opts["pbk"], "shortId": opts["sid"]},
        }}],
    }
    image = subprocess.check_output(["docker", "inspect", "-f", "{{.Image}}", container], text=True).strip()
    with TemporaryDirectory() as directory:
        path = Path(directory) / "client.json"
        path.write_text(json.dumps(config))
        path.chmod(0o644)  # На хосте файл находится в закрытом временном каталоге.
        client = subprocess.check_output([
            "docker", "run", "--rm", "-d", "--network", "host", "-v", f"{path}:/bench.json:ro",
            image, "run", "-config", "/bench.json",
        ], text=True).strip()
        try:
            proxy = f"socks5h://127.0.0.1:{port}"
            time.sleep(.6)
            if request(1024, proxy) is None:
                raise RuntimeError("контрольный HTTPS-запрос через XHTTP не прошёл")
            yield proxy
        finally:
            subprocess.run(["docker", "stop", client], stdout=subprocess.DEVNULL, check=False)


def main():
    parser = argparse.ArgumentParser(description="Сравнить прямой HTTPS и HTTPS через прокси")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--proxy", help="Например socks5h://127.0.0.1:1080")
    source.add_argument("--profile", type=Path, help="Профиль XHTTP; запустить временный клиент на VPS")
    parser.add_argument("--container", required=True, help="Контейнер серверного Xray на этом хосте")
    parser.add_argument("--waves", type=int, default=3)
    parser.add_argument("--bytes", type=int, default=4_000_000)
    args = parser.parse_args()
    if args.bytes < 1 or args.waves < 1:
        parser.error("--bytes и --waves должны быть положительными")
    pid = int(subprocess.check_output(["docker", "inspect", "-f", "{{.State.Pid}}", args.container], text=True))
    if pid <= 0:
        parser.error("серверный контейнер не запущен")
    path = next(x[3:] for x in Path(f"/proc/{pid}/cgroup").read_text().splitlines() if x.startswith("0::"))
    cgroup = Path("/sys/fs/cgroup") / path.lstrip("/")
    resources(cgroup)
    print(json.dumps({"started_utc": datetime.now(timezone.utc).isoformat(), "origin": ORIGIN,
                      "waves": args.waves, "bytes_per_download": args.bytes}), flush=True)
    context = loopback_client(args.profile, args.container) if args.profile else nullcontext(args.proxy)
    with context as proxy:
        for count in (1, 4, 8, 16):
            for mode in (None, proxy):
                print(json.dumps(measure(count, args.bytes, args.waves, mode, cgroup)), flush=True)


if __name__ == "__main__":
    main()
