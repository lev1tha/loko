# Запуск моста Kargoosh ↔ Loko на продакшене

Инструкция для DevOps. Цель: чтобы клиенты продолжали работать на kargoosh.kg (PHP,
hoster.kg), сотрудники — в Loko (lokobooking.com, наш VPS), а данные ходили между
системами сами, в обе стороны.

## Что получится

| Поток | Как работает | Задержка |
|---|---|---|
| Kargoosh → Loko | cron `import_kargoosh --incremental` читает MySQL сайта, ночью `--rescan` сверяет всё | ≤ 5 мин |
| Loko → Kargoosh | бэкенд Loko пишет продажи в таблицу `orders` сайта при сохранении (best effort), недошедшее добирает cron | секунды |
| PHP → Loko API | `/api/kargo/…` готов, но сайт его ещё не использует | — |

Компоненты: Django-бэкенд в Docker (`/opt/loko`, compose-проект `loko`), Postgres 17, host nginx.
Внешняя зависимость: MySQL сайта `176.126.165.65`, база `user143204_kargoosh`.

## Что нужно заранее

- root на VPS `157.250.205.157`, репозиторий `/opt/loko` на ветке `main`.
- Пароль MySQL базы сайта (`inc/db.inc.php` в проекте kargoosh, `DB_PASSWORD`).
- Удалённый доступ к этой базе с IP VPS (в ISPmanager у пользователя базы добавлен `157.250.205.157`). Если порт 3306 закрыт файрволом хостинга — см. шаг 3, туннель.
- 30 минут окна: первый импорт и перезапуск бэкенда.

## Шаг 1. Выкатить код

```bash
cd /opt/loko && git pull
cd infra
docker compose up -d --build backend
docker compose --profile build run --rm --build frontend
docker compose logs --tail=50 backend      # должно быть «Applying migrations… OK» без трейсбеков
```

Миграции применяются entrypoint'ом (express 0012–0016, finance 0016–0017). Ничего руками не мигрировать.

## Шаг 2. Переменные окружения

В `/opt/loko/infra/.env` добавить (образец — `infra/.env.example`):

```ini
# доступ PHP-сайта к /api/kargo/ (пока не используется, но пусть будет закрыт токеном)
KARGO_API_TOKEN=<openssl rand -hex 32>

# MySQL сайта kargoosh.kg
KARGO_DB_HOST=176.126.165.65
KARGO_DB_PORT=3306
KARGO_DB_USER=user143204_kargoosh
KARGO_DB_PASSWORD=<из inc/db.inc.php>
KARGO_DB_NAME=user143204_kargoosh

# обратный мост Loko → Kargoosh
KARGO_PUSH_IMMEDIATE=1
KARGO_DEFAULT_ADMIN_ID=2          # admin.pk_i_id «Ош» в Kargoosh: от его имени заводятся заказы Loko-филиалов
```

Проверить, что в `ALLOWED_HOSTS` / `CORS_ALLOWED_ORIGINS` / `CSRF_TRUSTED_ORIGINS` есть `api.kargoosh.kg` и `panel.kargoosh.kg` (уже в `.env.example`). Перезапустить бэкенд:

```bash
docker compose up -d backend
```

## Шаг 3. Проверить доступ к MySQL сайта

Из контейнера бэкенда (важно: именно оттуда, а не с хоста):

```bash
docker compose exec backend python - <<'PY'
import pymysql, os
c = pymysql.connect(host=os.environ["KARGO_DB_HOST"], port=int(os.environ["KARGO_DB_PORT"]),
    user=os.environ["KARGO_DB_USER"], password=os.environ["KARGO_DB_PASSWORD"],
    database=os.environ["KARGO_DB_NAME"], connect_timeout=8)
cur = c.cursor(); cur.execute("SELECT COUNT(*) FROM orders"); print("orders:", cur.fetchone()[0])
PY
```

Ожидается число порядка 171 000.

- `Access denied … @'157.250.205.157'` — порт открыт, но IP не применился в ISPmanager (проверить пользователя базы, сохранить форму ещё раз).
- `timed out` — порт 3306 закрыт файрволом хостинга. Либо заявка в поддержку hoster.kg («разрешить подключение к MySQL базы user143204_kargoosh с IP 157.250.205.157»), либо туннель ниже.

### Вариант: SSH-туннель (порт 22 у хостинга открыт)

Нужен SSH-доступ для аккаунта хостинга `user143204` (в ISPmanager: Пользователи → user143204 → «Доступ по SSH»). Пароль не хранить, только ключ.

```bash
apt-get install -y autossh
ssh-keygen -t ed25519 -f /root/.ssh/kargo_tunnel -N ''
cat /root/.ssh/kargo_tunnel.pub     # добавить в ~/.ssh/authorized_keys аккаунта user143204 на хостинге

# адрес шлюза docker-сети compose-проекта — на нём слушает туннель, из контейнера он доступен
GW=$(docker network inspect loko_default -f '{{(index .IPAM.Config 0).Gateway}}'); echo $GW
```

`/etc/systemd/system/kargo-tunnel.service`:

```ini
[Unit]
Description=SSH tunnel to kargoosh.kg MySQL
After=network-online.target docker.service

[Service]
Environment=AUTOSSH_GATETIME=0
ExecStart=/usr/bin/autossh -M 0 -N -o ServerAliveInterval=30 -o ServerAliveCountMax=3 \
  -o ExitOnForwardFailure=yes -o StrictHostKeyChecking=accept-new \
  -i /root/.ssh/kargo_tunnel -L <GW>:3307:127.0.0.1:3306 user143204@176.126.165.65
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
systemctl daemon-reload && systemctl enable --now kargo-tunnel && systemctl status kargo-tunnel
```

В `.env`: `KARGO_DB_HOST=<GW>`, `KARGO_DB_PORT=3307`, перезапустить бэкенд, повторить проверку выше.

## Шаг 4. Бэкап базы сайта

Обязательно перед первым импортом и перед включением обратного моста: Loko будет писать в `orders` сайта.

```bash
mkdir -p /srv/backups
docker run --rm mysql:8 mysqldump -h 176.126.165.65 -u user143204_kargoosh -p"$KARGO_DB_PASSWORD" \
  --single-transaction --quick user143204_kargoosh | gzip > /srv/backups/kargoosh-$(date +%F).sql.gz
ls -lh /srv/backups/
```

При туннеле: `-h <GW> -P 3307`. Дамп ≈ 30–60 МБ в gzip.

## Шаг 5. Первый импорт

Сначала прогон без записи со сверкой:

```bash
docker compose exec backend python manage.py import_kargoosh --dry-run
```

В блоке «Сверка» все пять строк должны быть ✓ (клиенты, заказы кол-во, Σ сом, Σ кг, кассы). Если есть ✗ — не продолжать, прислать вывод.

Затем реальный импорт (несколько минут на Postgres):

```bash
docker compose exec backend python manage.py import_kargoosh
```

Повторный запуск полного импорта безопасен (идемпотентен по `legacy_kargo_*`), но не нужен: дальше работает инкремент.

## Шаг 6. Cron

`crontab -e` под root на хосте:

```cron
*/5 * * * *  cd /opt/loko/infra && docker compose exec -T backend python manage.py import_kargoosh --incremental >> /var/log/loko-kargo-sync.log 2>&1
15 3 * * *   cd /opt/loko/infra && docker compose exec -T backend python manage.py import_kargoosh --rescan      >> /var/log/loko-kargo-sync.log 2>&1
```

Логротация: `/etc/logrotate.d/loko-kargo` с `weekly, rotate 8, compress`.

## Шаг 7. Проверить мост в обе стороны

**Kargoosh → Loko.** Зарегистрировать тестового клиента на kargoosh.kg (или взять существующего), через ≤ 5 мин найти его в Loko: «Клиенты» → поиск по телефону. В логе `/var/log/loko-kargo-sync.log` строка `клиенты: +1 новых`.

**Loko → Kargoosh.** В Loko (панель, роль кассир/админ): «Склад» → создать заявку с кодом этого клиента → оприходовать с весом (складовщик или админ). Затем в MySQL сайта:

```bash
docker compose exec backend python - <<'PY'
import pymysql, os
c = pymysql.connect(host=os.environ["KARGO_DB_HOST"], port=int(os.environ["KARGO_DB_PORT"]),
    user=os.environ["KARGO_DB_USER"], password=os.environ["KARGO_DB_PASSWORD"], database=os.environ["KARGO_DB_NAME"])
cur = c.cursor(pymysql.cursors.DictCursor)
cur.execute("SELECT pk_i_id, s_user_code, s_tracking_number, i_weight, i_price, i_status, dt_arrival FROM orders ORDER BY pk_i_id DESC LIMIT 3")
for r in cur.fetchall(): print(r)
PY
```

Ожидается строка с кодом клиента, `i_status=2`, весом и суммой; трек `LOKO-<id>`, если складовщик его не вводил. Клиент видит её в кабинете сайта во вкладке «Складда». После выдачи заявки в Loko статус станет 3.

Состояние синхронизации через API (нужен токен):

```bash
curl -s -H "X-Kargo-Token: $KARGO_API_TOKEN" https://api.lokobooking.com/api/kargo/sync/ | python3 -m json.tool
```

`last.ok=true`, `stats.reconciled=true`, `stats.pushed` — счётчики обратного моста.

## Шаг 8 (опционально). Домены kargoosh.kg для сотрудников

Чтобы сотрудники и директор заходили через `panel.kargoosh.kg`, а API отвечал на `api.kargoosh.kg`: конфиги в `infra/nginx/*.kargoosh.kg.conf` (инструкции в шапке файлов: symlink в `sites-enabled`, `certbot --nginx`, отдельная сборка SPA в `/srv/www/kargoosh-panel`). DNS A-записи на `157.250.205.157` заводятся у hoster.kg. `panel.` закрыть от индексации (`X-Robots-Tag: noindex` в nginx).

## Эксплуатация

- **Мониторинг**: раз в день `tail -50 /var/log/loko-kargo-sync.log` (искать ✗ и Traceback); в Loko таблица «Синхронизации Kargo» (`express.KargoSync`, Django admin) или `GET /api/kargo/sync/`.
- **Выключить мост** (например, при инциденте на хостинге): `KARGO_PUSH_IMMEDIATE=0` в `.env` + перезапуск бэкенда, закомментировать cron. Loko продолжает работать сам по себе; непереданные продажи копятся с флагом и уйдут после включения (`manage.py push_kargoosh`).
- **Откат данных сайта**: восстановить дамп из шага 4. Строки, записанные Loko, отличаются треком `LOKO-…` или `fk_i_admin_id` из `KARGO_DEFAULT_ADMIN_ID` и `fk_i_transaction_id IS NULL`.
- **Что не синхронизируется**: правки в PHP-админке по заказам, созданным в Loko (для них Loko главный); журнал денежных операций Kargoosh (`transactions`) — остаток касс в Loko считается по модели отчёта, не по факту; клиенты, зарегистрированные в Loko по QR только по телефону, на сайт не попадают (там нужны e-mail и пароль).
- **Секреты**: `infra/.env` не коммитить; пароль хостинга, который был в переписке, сменить в ISPmanager.
