# Тестовый сервер AnyModel

Один контейнер Xray-core с VLESS/TCP/REALITY. Профили владельца и проверяющего создаются отдельно, с разными UUID. Аналитическая часть — [«Фильтрация трафика в России»](reports/Фильтрация%20трафика%20в%20России.md).

## Запуск на Ubuntu 24.04

Подключитесь по SSH, смените выданный пароль командой `passwd` и настройте вход по SSH-ключу. В панели хостера разрешите входящий `443/tcp`; на сервере этот порт должен быть свободен (`ss -ltnp 'sport = :443'`).

Под `root` установите зависимости:

```bash
apt-get update && apt-get install -y docker.io docker-compose-v2 python3
systemctl enable --now docker
docker compose version
```

В каталоге проекта выполните, заменив `SERVER_IP` на внешний IPv4 VPS:

```bash
python3 scripts/init.py SERVER_IP
docker compose run --rm --no-deps xray run -test -config /etc/xray/server.json && docker compose up -d
```

Compose публикует `443/tcp` на хосте и направляет его на `8443/tcp` в контейнере. При изменении внешнего порта задайте одинаковое значение для `XRAY_PORT` в Compose и `--port` при генерации.

## Проверка подключения

На своём устройстве импортируйте строку из `runtime/owner.txt` в клиент с поддержкой REALITY и Vision. Откройте `https://api.ipify.org` с активным профилем и проверьте, что отображается выходной IP VPS. Повторите с выключенным Wi-Fi. Запишите оператора, время и результат. Для диагностики на сервере:

```bash
docker compose ps
docker compose logs --tail=50 xray
```

Для проверки передайте только `runtime/reviewer.txt` по личному каналу. Весь каталог `runtime/` исключён из Git; не копируйте `server.json` и файлы профилей в публичный отчёт. После проверки удалите запись клиента с `email: reviewer` из `runtime/server.json` и выполните `docker compose up -d --force-recreate`. Перезапись `runtime/` генератором намеренно запрещена, чтобы случайно не сбросить действующие ключи.
