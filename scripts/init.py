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
    parser.add_argument("--port", type=int, default=443, help="Внешний порт (как XRAY_PORT в Compose)")
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("порт должен быть в диапазоне 1–65535")
    if RUNTIME.exists() or RUNTIME.is_symlink():
        parser.error("runtime/ уже существует; действующие ключи и UUID не перезаписаны")

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

    # Доступ на хосте ограничен правами каталога; контейнеру монтируется только JSON.
    RUNTIME.mkdir(mode=0o700)
    for name, label in (("owner", "AnyModel — личный"), ("reviewer", "AnyModel — проверка")):
        client_id = str(uuid.uuid4())
        inbound["settings"]["clients"].append({"id": client_id, "flow": FLOW, "email": name})
        profile = f"vless://{client_id}@{args.ip}:{args.port}?{params}#{quote(label)}\n"
        fd = os.open(RUNTIME / f"{name}.txt", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as file:
            file.write(profile)
    server = RUNTIME / "server.json"
    server.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    server.chmod(0o644)
    print("Готово: runtime/server.json, runtime/owner.txt, runtime/reviewer.txt")


if __name__ == "__main__":
    try:
        main()
    except (OSError, subprocess.CalledProcessError) as exc:
        raise SystemExit(f"Ошибка подготовки конфигурации: {exc}") from None
