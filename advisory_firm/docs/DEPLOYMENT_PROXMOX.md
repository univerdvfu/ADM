# Развёртывание на Proxmox: контейнер 107 `advisory-db`

## Где что находится

| Что | Значение |
|---|---|
| Хост Proxmox | `10.50.16.240` (SSH по ключу, root) |
| Контейнер | LXC **107**, имя `advisory-db`, Ubuntu 24.04, непривилегированный, автозапуск |
| Ресурсы | 4 ядра, 8 ГБ памяти, 1 ГБ swap, диск 40 ГБ на `local-lvm` |
| Сеть | `eth0` на `vmbr0`, без тега, **10.50.16.246/24**, шлюз 10.50.16.1, DNS 10.101.1.100 |
| Веб-сервис | `http://10.50.16.246/` (nginx, порт 80, базовая авторизация) |
| Пароль веб-сервиса | в контейнере: `/root/advisory-credentials.txt` (логин `advisory`) |
| Код | `/opt/advisory_firm` (владелец `advisory`) |
| Данные и бинарники | `/home/advisory/advisory-stack` (ClickHouse, MinIO, PostgreSQL, venv, Airflow) |
| Секреты MinIO | `/home/advisory/advisory-stack/secrets.env` (права 600) |

### Про сеть и VLAN 999

Создавался контейнер с интерфейсом `vmbr2`, `tag=999`: адрес по DHCP он не получил, а статический адрес
из сети 10.50.16.0/24 через этот тег не достучался до шлюза. Единственное описание VLAN 999 на хосте —
контейнер `gw-999-1101` («Шлюз VLAN 999 ↔ 1101»), у которого сторона 999 — это `vmbr0` без тега в сети
10.50.16.0/24. Поэтому контейнер 107 подключён так же: `vmbr0`, без тега. Если нужен именно `vmbr2` с
тегом 999, надо уточнить у сетевого администратора, как эта VLAN заведена на коммутаторе, и сменить:

```bash
pct set 107 --net0 name=eth0,bridge=vmbr2,tag=999,firewall=0,ip=<IP>/<маска>,gw=<шлюз>
pct reboot 107
```

IP 10.50.16.246 выбран свободным (на ARP-запросы не отвечал); если он занят, поменяйте через `pct set 107 --net0 ...`.

## Подключение (из сетей 10.50.16.0/24 и 10.53.16.0/24)

Пароли лежат только в контейнере: `ssh root@10.50.16.240 "pct exec 107 -- cat /root/advisory-credentials.txt"`.

| Что | Адрес | Логин | Права |
|---|---|---|---|
| Веб-сервис (таблицы, тесты, загрузка) | `http://10.50.16.246/` | `advisory` | полные, через сервис |
| Swagger (описание API, «Try it out») | `http://10.50.16.246/docs` | `advisory` | те же, что у веб-сервиса |
| Airflow | `http://10.50.16.246:8080/` | `admin` | администратор, вход через форму |
| PostgreSQL | `10.50.16.246:5432`, база `service` (старая `advisory` пуста) | `advisory_ro` | только чтение |
| ClickHouse HTTP | `http://10.50.16.246:8123`, база `service` (в старой `analytics` остались данные первых тестовых запусков) | `advisory_ro` | только чтение |
| ClickHouse native | `10.50.16.246:9000` | `advisory_ro` | только чтение |
| MinIO (S3 API) | `http://10.50.16.246:9100`, бакет `raw-market` | `advisory_ro` | только чтение (список и чтение объектов) |
| MinIO (консоль) | `http://10.50.16.246:9101` | `advisory_ro` | только чтение |

Примеры:

```bash
psql "host=10.50.16.246 port=5432 dbname=service user=advisory_ro"            # пароль спросит
clickhouse-client --host 10.50.16.246 --user advisory_ro --password <пароль> -q "SELECT count() FROM service.daily_bars"
curl -u advisory_ro:<пароль> "http://10.50.16.246:8123/?query=SELECT%20version()"
```

DBeaver и подобные клиенты: драйвер PostgreSQL (порт 5432) или ClickHouse (порт 8123), логин и пароль из файла выше.

Суперпользователи наружу закрыты: PostgreSQL `postgres`, ClickHouse `default` и администратор MinIO (`advisory`, пароль в `/home/advisory/advisory-stack/secrets.env`) работают только с самого контейнера.
Примеры для MinIO: `mc alias set adv http://10.50.16.246:9100 advisory_ro <пароль>` и `mc ls adv/raw-market`, либо любой S3-клиент (`boto3`, `aws s3 --endpoint-url`).
Доступ по сети разрешён только из подсетей 10.50.16.0/24 и 10.53.16.0/24 (правила в `pg_hba.conf` и в `users.xml`
ClickHouse). Чтобы добавить сеть, поправьте оба файла или перезапустите `deploy/ct/expose.sh <IP> "<сети через пробел>"`
(скрипт выдаст новые пароли). Все соединения без шифрования, пароли идут открытым текстом.

## Службы (systemd внутри контейнера)

| Служба | Что делает | Слушает |
|---|---|---|
| `advisory-postgres` | PostgreSQL 16 (бинарник из pgserver) | 127.0.0.1:5432 и 10.50.16.246:5432, сокет в каталоге данных |
| `advisory-clickhouse` | ClickHouse | 0.0.0.0:8123 и 9000 (доступ ограничен пользователями) |
| `advisory-minio` | MinIO | 0.0.0.0:9100 (S3 API) и 9101 (консоль); порт 9000 занят ClickHouse |
| `advisory-service` | сервис просмотра таблиц и тестов | 127.0.0.1:8765 |
| `advisory-airflow` | планировщик Airflow, DAG `advisory_pipeline`, будни 19:00 МСК | — |
| `advisory-airflow-web` | веб-интерфейс Airflow | 10.50.16.246:8080 |
| `nginx` | обратный прокси с паролем на `advisory-service` | 0.0.0.0:80 |

Только внутри контейнера остался сам сервис просмотра (127.0.0.1:8765, снаружи через nginx).

Нюансы, на которые наткнулись при развёртывании: у `systemd-logind` по умолчанию `RemoveIPC=yes`, из-за чего при
выходе сессии пользователя `advisory` удалялись сегменты общей памяти PostgreSQL (в `install_ct.sh` стоит `RemoveIPC=no`);
сервису просмотра нужен `XDG_RUNTIME_DIR` с правом записи; каталоги данных ClickHouse и MinIO создаются заранее.

## Команды

С хоста Proxmox:

```bash
pct enter 107                                    # консоль контейнера
pct exec 107 -- systemctl status advisory-service
pct exec 107 -- journalctl -u advisory-service -n 50 --no-pager
pct exec 107 -- cat /root/advisory-credentials.txt
pct stop 107 / pct start 107                     # остановка и запуск
```

Внутри контейнера (от root):

```bash
systemctl restart advisory-postgres advisory-clickhouse advisory-minio advisory-service advisory-airflow
systemctl status 'advisory-*' nginx
```

Тесты внутри контейнера:

```bash
su - advisory -c "cd /opt/advisory_firm && bash deploy/run_tests.sh tests/test_db_complex.py -vv"
```

## Как это ставилось

1. `pct create 107` из шаблона `ubuntu-24.04-standard`, ключ `id_ed25519` в `authorized_keys` контейнера.
2. Внутри: `apt install python3-venv python3-pip curl nginx apache2-utils`, пользователь `advisory`.
3. Проект распакован в `/opt/advisory_firm`, бинарник MinIO (собран из исходников) положен в `advisory-stack/bin`.
4. От `advisory`: `bash deploy/setup.sh` (ClickHouse скачивается, ставятся Python-окружение, PostgreSQL через pgserver и Airflow).
5. От root: `bash deploy/ct/install_ct.sh` — секреты, службы systemd, nginx, база `advisory`.
6. Данные загружены кнопкой «Загрузить данные» (живой API Мосбиржи), 15 тестов запущены через сервис: все прошли за 9,6 с.
7. DAG `advisory_pipeline` снят с паузы и выполнен планировщиком: ручной запуск и пропущенный запуск по расписанию завершились `success`. Следующий автоматический запуск — в будний день в 19:00 МСК.

По ходу выяснилось: каталоги данных ClickHouse и MinIO надо создавать заранее, а у службы Airflow в `PATH` должен быть `venv/bin` (иначе планировщик не находит команду `airflow`); обе правки уже внесены в `install_ct.sh` и юнит.

## Обновление проекта

С машины с проектом:

```bash
tar -czf /tmp/advisory_firm.tgz -C <папка-с-проектом> advisory_firm
scp /tmp/advisory_firm.tgz root@10.50.16.240:/tmp/
ssh root@10.50.16.240 'pct push 107 /tmp/advisory_firm.tgz /tmp/a.tgz && pct exec 107 -- bash -c "tar --no-same-owner -xzf /tmp/a.tgz -C /opt && chown -R advisory:advisory /opt/advisory_firm && systemctl restart advisory-service advisory-airflow"'
```

## Удаление

```bash
pct stop 107 && pct destroy 107
```

Это удалит контейнер вместе с данными и базами.

## Одна база для DAG и веб-сервиса

DAG Airflow и веб-сервис работают с **одними и теми же базами**: PostgreSQL `service` и ClickHouse `service`. Так сделано через
переменные `PG_DSN` (`dbname=service`) и `CH_DATABASE=service` в юнитах `advisory-airflow`, `advisory-airflow-web` и
`advisory-service`. Поэтому всё, что DAG загрузил ночью, видно во вкладке «Данные», а клиенты из демо-данных попадают под шаг `recommend`.
Старые базы `advisory` (PostgreSQL) и `analytics` (ClickHouse) остались от первых запусков и больше не пополняются.

Шаг `recommend` создаёт черновик только если для клиента, бумаги и даты данных его ещё нет, поэтому повторный запуск на тех же данных
возвращает 0.
