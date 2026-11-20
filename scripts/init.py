#!/usr/bin/env python3
import argparse
import ipaddress
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
from urllib.parse import quote, urlencode
import uuid


ROOT = Path(__file__).resolve().parent.parent
RUNTIME = ROOT / "runtime"
FLOW = "xtls-rprx-vision"


def main():
    parser = argparse.ArgumentParser(description="Создать конфигурацию Xray и два клиентских профиля.")
    parser.add_argument("ip", type=ipaddress.IPv4Address, help="Внешний IPv4-адрес сервера")
    parser.add_argument("--port", type=int, help="Внешний порт (по умолчанию 443)")
    parser.add_argument("--transport", choices=("tcp", "xhttp"), default="tcp")
    args = parser.parse_args()
    if args.port is None:
        args.port = 443
    if not 1 <= args.port <= 65535:
        parser.error("порт должен быть в диапазоне 1–65535")
    runtime = RUNTIME / "xhttp" if args.transport == "xhttp" else RUNTIME
    if runtime.exists() or runtime.is_symlink():
        parser.error(f"{runtime.relative_to(ROOT)}/ уже существует; действующие ключи и UUID не перезаписаны")
    if RUNTIME.is_symlink():
        parser.error("runtime/ не должен быть символической ссылкой")

    image = subprocess.check_output(["docker", "compose", "config", "--images"], cwd=ROOT, text=True).strip()
    output = subprocess.check_output(["docker", "run", "--rm", "--network", "none", image, "x25519"], text=True)
    values = dict(line.split(": ", 1) for line in output.splitlines() if ": " in line)
    private_key, public_key = values.get("PrivateKey", ""), values.get("Password (PublicKey)", "")
    if not all(re.fullmatch(r"[A-Za-z0-9_-]{43}", key) for key in (private_key, public_key)):
        parser.exit(1, "Не удалось прочитать ключи из вывода Xray.\n")

    config = json.loads((ROOT / "config/server.example.json").read_text(encoding="utf-8"))
    inbound = config["inbounds"][0]
    reality = inbound["streamSettings"]["realitySettings"]
    short_id = secrets.token_hex(8)
    reality.update(privateKey=private_key, shortIds=[short_id])
    params = urlencode({
        "encryption": "none", "security": "reality", "type": "tcp", "flow": FLOW,
        "sni": reality["serverNames"][0], "fp": "chrome", "pbk": public_key, "sid": short_id,
    })
    flow = {"flow": FLOW}
    if args.transport == "xhttp":
        settings = {"path": "/" + secrets.token_hex(10), "mode": "stream-one"}
        inbound["streamSettings"].update(network="xhttp", xhttpSettings=settings)
        params = urlencode({
            "encryption": "none", "security": "reality", "type": "xhttp", **settings,
            "sni": reality["serverNames"][0], "fp": "chrome", "pbk": public_key, "sid": short_id,
        })
        flow = {}

    # Доступ на хосте ограничен правами каталога; контейнеру монтируется только JSON.
    if args.transport == "xhttp":
        RUNTIME.mkdir(mode=0o700, exist_ok=True)
    runtime.mkdir(mode=0o700)
    for name, label in (("owner", "AnyModel — личный"), ("reviewer", "AnyModel — проверка")):
        client_id = str(uuid.uuid4())
        inbound["settings"]["clients"].append({"id": client_id, **flow, "email": name})
        if args.transport == "xhttp":
            label += " (XHTTP)"
        profile = f"vless://{client_id}@{args.ip}:{args.port}?{params}#{quote(label)}\n"
        fd = os.open(runtime / f"{name}.txt", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as file:
            file.write(profile)
    server = runtime / "server.json"
    server.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    server.chmod(0o644)
    print(f"Готово: конфигурация и профили в {runtime.relative_to(ROOT)}/")


if __name__ == "__main__":
    try:
        main()
    except (OSError, subprocess.CalledProcessError) as exc:
        raise SystemExit(f"Ошибка подготовки конфигурации: {exc}") from None
