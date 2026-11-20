# Тестовый сервер AnyModel

Основной вариант — Xray-core с VLESS/XHTTP/REALITY (`stream-one`). Профили владельца и проверяющего создаются отдельно, с разными UUID. Аналитическая часть и результаты проб — [«Фильтрация трафика в России»](reports/Фильтрация%20трафика%20в%20России.md).

## Запуск на Ubuntu 24.04

Подключитесь по SSH, смените выданный пароль командой `passwd` и настройте вход по SSH-ключу. В панели хостера разрешите входящий `443/tcp`; на сервере этот порт должен быть свободен (`ss -ltnp 'sport = :443'`). Для дополнительного файла Compose нужна версия Docker Compose 2.24.4 или новее.

Под `root` установите зависимости:

```bash
apt-get update && apt-get install -y docker.io docker-compose-v2 python3
systemctl enable --now docker
docker compose version
```

В каталоге проекта выполните, заменив `SERVER_IP` на внешний IPv4 VPS:

```bash
python3 scripts/init.py SERVER_IP --transport xhttp
docker compose -p anymodel-xhttp -f compose.yaml -f compose.xhttp.yaml run --rm --no-deps xray run -test -config /etc/xray/server.json && \
docker compose -p anymodel-xhttp -f compose.yaml -f compose.xhttp.yaml up -d
```

Compose публикует `443/tcp` на хосте и направляет его на `8443/tcp` в контейнере. При изменении внешнего порта задайте одинаковое значение для `XRAY_PORT` в Compose и `--port` при генерации. Контрольный вариант VLESS/TCP/REALITY с Vision настраивается так же, но с `--transport tcp` и только файлом `compose.yaml` (профили прямо в `runtime/`).

## Проверка подключения

На своём устройстве импортируйте строку из `runtime/xhttp/owner.txt` в клиент с поддержкой XHTTP (`stream-one`) и REALITY. Откройте `https://api.ipify.org` с активным профилем и проверьте, что отображается выходной IP VPS. Повторите с выключенным Wi-Fi. Запишите оператора, время и результат. Для диагностики на сервере:

```bash
docker compose -p anymodel-xhttp -f compose.yaml -f compose.xhttp.yaml ps
docker compose -p anymodel-xhttp -f compose.yaml -f compose.xhttp.yaml logs --tail=50 xray
```

Для проверки передайте только `runtime/xhttp/reviewer.txt` по личному каналу. Весь каталог `runtime/` исключён из Git. После проверки удалите клиента `reviewer` из `runtime/xhttp/server.json` и выполните `docker compose -p anymodel-xhttp -f compose.yaml -f compose.xhttp.yaml up -d --force-recreate`. Генератор не перезаписывает действующие ключи.

## Нагрузочный прогон на VPS

На хосте с Docker, cgroup v2, Python 3 и `curl` запустите из каталога проекта:

```bash
CONTAINER=$(docker compose -p anymodel-xhttp -f compose.yaml -f compose.xhttp.yaml ps -q xray)
python3 scripts/bench.py --container "$CONTAINER" --profile runtime/xhttp/owner.txt --waves 2
```

Скрипт печатает JSON по каждой ступени. Клиент запускается в отдельном временном контейнере на VPS; такой прогон измеряет работу туннеля и нагрузку на сервер, но не доступность из сети абонента.
