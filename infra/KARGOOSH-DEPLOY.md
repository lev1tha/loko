# Kargoosh ↔ Loko на продакшене

Инструкция для DevOps. Цель: клиенты продолжают работать на kargoosh.kg (PHP,
hoster.kg), сотрудники — в Loko (lokobooking.com, наш VPS), данные живут в Loko.

## Статус на 04.09.2026 — что уже сделано

| Этап | Состояние |
|---|---|
| Выкат кода Loko (`52090fc` → `99a1f0f`, 8 миграций) | **готово** |
| Исторический импорт Kargo Osh в Loko | **готово** — из дампа, см. §5 |
| Прямой доступ к MySQL сайта (мост в обе стороны) | **заблокирован хостингом**, см. §3 |
| Переключение PHP-сайта на `/api/kargo/…` | не начато |
| Перенос финжурнала (`transactions`) | не начато, см. §5.3 |

Результат импорта (04.09.2026): 9 672 клиента, 171 414 заказов на
**245 072 209.99 сом** и **154 186.14 кг**, 8 касс с суммарным остатком
**226 448 052.90 сом**, 6 филиалов из регионов Kargo. Выручка Express в отчётах
Loko стала 255 758 451.92 = 10 686 241.93 (своя) + 245 072 209.99 (импорт).

Компоненты: Django-бэкенд в Docker (`/opt/loko`, compose-проект `loko`), Postgres 17, host nginx.

---

## Шаг 0. Бэкап Postgres — ДО всего

Точка отката. Снимать **после** `git pull`, но **до** миграций и импорта — иначе
откат вернёт и схему тоже.

```bash
mkdir -p /srv/backups && chmod 700 /srv/backups
cd /opt/loko/infra
docker compose exec -T db pg_dump -U lokobooking -p 5434 loko | gzip > /srv/backups/loko-$(date +%F-%H%M).sql.gz
ls -lh /srv/backups/
```

`-p 5434` обязателен — postgres слушает этот порт и внутри контейнера. **Всегда
проверять размер файла**: в пайпе `pg_dump | gzip` статус берётся от gzip, поэтому
ошибка дампа не прерывает `&&`-цепочку и молча оставляет валидный gzip с мусором.

## Шаг 1. Выкатить код

Сначала выяснить, что реально стоит на проде — от этого зависит объём миграций:

```bash
cd /opt/loko && git log -1 --oneline && git status --short
cd infra && docker compose exec -T backend python manage.py showmigrations accounts express finance
```

Затем бэкенд отдельно от фронта, чтобы не собирать SPA поверх упавшего бэкенда:

```bash
cd /opt/loko && git pull
cd infra && docker compose up -d --build backend && sleep 15 && docker compose logs --tail=60 backend
docker compose exec -T backend python manage.py showmigrations express finance | grep -c "\[ \]"   # должно быть 0
docker compose --profile build run --rm --build frontend
```

`--build` для бэкенда обязателен: с версии `0324359` в зависимостях появился
`PyMySQL`, без пересборки образа мост падает в рантайме. Миграции применяет
entrypoint — руками не мигрировать.

С `52090fc` применяются **восемь** миграций: `express` 0012–0016 и `finance`
0016–0018. Все аддитивные (`AddField`/`CreateModel`), data-миграций нет, новые
unique-колонки все `null=True` — на существующих строках коллизий не бывает.

## Шаг 2. Переменные окружения

В `/opt/loko/infra/.env` (образец — `infra/.env.example`):

```ini
KARGO_API_TOKEN=<сюда вставить ВЫВОД `openssl rand -hex 32`, а не эту строку>
KARGO_DB_HOST=176.126.165.65
KARGO_DB_PORT=3306
KARGO_DB_USER=user143204_kargoosh
KARGO_DB_PASSWORD=<из inc/db.inc.php проекта kargoosh>
KARGO_DB_NAME=user143204_kargoosh
KARGO_PUSH_IMMEDIATE=0
KARGO_DEFAULT_ADMIN_ID=2
```

**`KARGO_PUSH_IMMEDIATE=0` на этом шаге принципиально.** С единицей Loko начнёт
писать в таблицу `orders` живого сайта сразу после рестарта — то есть ДО того,
как снят бэкап чужой базы (шаг 4). Включать в `1` только после шага 4.

Чтобы не вставить плейсхолдер буквально (случалось дважды), токен пишется на
месте:

```bash
cd /opt/loko/infra
sed -i "s|^KARGO_API_TOKEN=.*|KARGO_API_TOKEN=$(openssl rand -hex 32)|" .env
grep -c '^KARGO_API_TOKEN=[0-9a-f]\{64\}$' .env      # должно быть 1
```

Пустой `KARGO_API_TOKEN` закрывает все `/api/kargo/` наглухо (fail closed).
Непустой, но угадываемый — хуже пустого: эндпоинты открываются по строке из
документации.

Проверить, что в `ALLOWED_HOSTS` / `CORS_ALLOWED_ORIGINS` / `CSRF_TRUSTED_ORIGINS`
есть `api.kargoosh.kg` и `panel.kargoosh.kg`. Перезапустить: `docker compose up -d backend`.

Компоса пересоздаёт контейнер только если конфигурация изменилась. Если в выводе
`Container loko-backend-1 Running` (а не `Started`/`Recreated`) — значит `.env`
не менялся и внутри остались старые значения.

## Шаг 3. Проверить доступ к MySQL сайта

Из контейнера бэкенда (важно: оттуда, а не с хоста):

```bash
cd /opt/loko/infra && docker compose exec -T backend python - <<'PY'
import pymysql, os
c = pymysql.connect(host=os.environ["KARGO_DB_HOST"], port=int(os.environ["KARGO_DB_PORT"]),
    user=os.environ["KARGO_DB_USER"], password=os.environ["KARGO_DB_PASSWORD"],
    database=os.environ["KARGO_DB_NAME"], connect_timeout=8)
cur = c.cursor(); cur.execute("SELECT COUNT(*) FROM orders"); print("orders:", cur.fetchone()[0])
PY
```

Ожидается число порядка 171 000.

### Факт на 04.09.2026: доступа нет

`TimeoutError` на `socket.create_connection`. Проверка портов с VPS
`157.250.205.157`:

| Хост | 443 | 22 | 3306 |
|---|---|---|---|
| `176.126.165.65` (MySQL) | открыт | **закрыт** | **закрыт** |
| `176.126.165.192` (сайт) | открыт | **закрыт** | **закрыт** |

Машины живы (443 отвечает, `curl https://kargoosh.kg/` → 200), но hoster.kg
режет наружу и 3306, и 22. **Вариант с SSH-туннелем поэтому неприменим** — он
требовал открытого 22.

Правильный способ проверить порт из bash — только connect, без чтения:

```bash
for h in 176.126.165.65 176.126.165.192 1.1.1.1; do for p in 443 22 3306; do
  timeout 5 bash -c "exec 3<>/dev/tcp/$h/$p" 2>/dev/null && echo "$h:$p открыт" || echo "$h:$p закрыт"
done; done
```

⚠️ Не использовать `cat < /dev/tcp/...`: на портах, где сервер молчит до запроса
клиента (443), `cat` виснет, `timeout` его убивает, и открытый порт выглядит
закрытым. Такая проверка даёт ложные «закрыт» даже для `1.1.1.1:443`.

Что делать: заявка в hoster.kg («разрешить 3306 с IP 157.250.205.157 для базы
`user143204_kargoosh`, либо дать SSH для аккаунта `user143204`»). Пока её не
решили — исторический импорт делается по §5 без всякого доступа, а
двусторонний мост просто не поднимается: он не на критическом пути, целевая
схема — PHP ходит в `/api/kargo/…` (см. `KARGO-API.md`).

## Шаг 4. Бэкап базы сайта

Обязателен, только если поднимается обратный мост (Loko пишет в `orders` сайта).
При импорте из дампа (§5) не нужен — дамп и есть бэкап.

```bash
docker run --rm mysql:8 mysqldump -h 176.126.165.65 -u user143204_kargoosh -p"$KARGO_DB_PASSWORD" \
  --single-transaction --quick user143204_kargoosh | gzip > /srv/backups/kargoosh-$(date +%F).sql.gz
```

После этого — и только после — `KARGO_PUSH_IMMEDIATE=1` + `docker compose up -d backend`.

## Шаг 5. Исторический импорт

### 5.1. Если прямой доступ есть

```bash
docker compose exec -T backend python manage.py import_kargoosh --dry-run   # сверка, откат
docker compose exec -T backend python manage.py import_kargoosh             # запись
```

### 5.2. Если доступа нет — импорт из дампа (так и сделано 04.09.2026)

Импортёру нужна не живая база, а **любой** MySQL с этими данными. Значит порты
открывать не обязательно: дамп забирается через веб-панель (443 открыт) и
поднимается локально на VPS.

**Выгрузка.** ISPmanager → Основное → Базы данных → у базы кнопка **phpMyAdmin**
→ вкладка **Экспорт**. База целиком ~28 МБ (в панели видно «Размер баз данных»),
поэтому выборочный экспорт не нужен — «Быстрый», формат SQL, при желании gzip.
Импортёр читает только шесть таблиц: `user`, `orders`, `transactions`, `cards`,
`admin`, `settings`; остальные (`slider`, `pages`, `popular_products`, `locale`,
`orders_unknown`, `orders_tez_biznes`, `salawat_counter`) не трогает.
Запасной путь, если phpMyAdmin не открывается — ISPmanager → Резервные копии.

**Проверка дампа перед заливкой** (обрыв экспорта — самая частая беда):

```bash
tail -3 файл.sql            # должно быть «-- Dump completed on …»
grep -c "^CREATE TABLE" файл.sql
```

**Временный MySQL в сети compose-проекта** — бэкенд обращается к нему по имени
контейнера:

```bash
docker run -d --name kargo-tmp --network loko_default \
  -e MYSQL_ROOT_PASSWORD=tmp-only-local -e MYSQL_DATABASE=user143204_kargoosh mysql:8
docker exec kargo-tmp mysqladmin -uroot -ptmp-only-local ping        # ждать «mysqld is alive»
docker exec -i kargo-tmp mysql -uroot -ptmp-only-local user143204_kargoosh < /srv/backups/user143204_kargoosh.sql
```

**Сверка источника** — до запуска импортёра:

```bash
docker exec -i kargo-tmp mysql -uroot -ptmp-only-local -N -e \
 "SELECT 'user',COUNT(*) FROM user UNION ALL SELECT 'orders',COUNT(*) FROM orders
  UNION ALL SELECT 'transactions',COUNT(*) FROM transactions UNION ALL SELECT 'cards',COUNT(*) FROM cards;
  SELECT i_status, COUNT(*), ROUND(SUM(i_price),2), ROUND(SUM(i_weight),2) FROM orders GROUP BY i_status;" \
 user143204_kargoosh
```

Числа источника меняются каждый день (склад работает), поэтому эталон — не
цифры из документации, а **этот прогон**: именно их обязан воспроизвести
импортёр. 04.09.2026 было 9 672 / 171 414 / 42 529 / 8, по статусам
1 → 14 254 · 2 → 2 380 (240 871.39 сом) · 3 → 154 780 (244 831 338.60 сом).

За сутки счётчик заказов может даже уменьшиться (03.09 было 171 449): в источнике
часть строк удаляется физически, а статусы переливаются тысячами в день. Это
нормально. Признак **испорченного** дампа — другое: обрыв файла или таблицы на
MyISAM (`SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='…' AND engine='MyISAM'`
должно быть 0, иначе снимок неконсистентен и дамп надо переснять).

**Переключить `.env` на временный контейнер** и перезапустить бэкенд:

```ini
KARGO_DB_HOST=kargo-tmp
KARGO_DB_PORT=3306
KARGO_DB_USER=root
KARGO_DB_PASSWORD=tmp-only-local
KARGO_DB_NAME=user143204_kargoosh
KARGO_PUSH_IMMEDIATE=0
```

`KARGO_PUSH_IMMEDIATE=0` критично: иначе Loko начнёт писать продажи в
базу-однодневку.

Дальше — `--dry-run`, сверка, боевой прогон (как в 5.1).

### 5.3. Что даёт импорт, а что нет

В блоке сверки пять ✓ и одна `⧗`:

```
✓ клиенты · ✓ заказы (кол-во) · ✓ заказы Σ сом · ✓ заказы Σ кг · ✓ кассы карго Σ баланс
⧗ транзакции (42 529) — финжурнал следующим проходом
```

**Транзакции не переносятся.** Деньги приходят как `initial_balance` счетов
(вариант Б из `INTEGRATION-KARGOOSH.md` §5.4): остаток каждой кассы сведён с
`cards.i_amount`, но истории движений нет. ОДДС по этим деньгам построить нельзя,
только текущий остаток. Перенос финжурнала — отдельная задача.

Импорт идемпотентен по `legacy_kargo_*`: повторный прогон сначала удаляет свои
прежние строки, потом создаёт заново.

### 5.4. Приборка после импорта из дампа

```bash
docker rm -f kargo-tmp
rm -f /srv/backups/user143204_kargoosh.sql && chmod 700 /srv/backups
```

В `.env` очистить `KARGO_DB_HOST` (пустым — это главный рубильник моста) и заодно
`KARGO_DB_USER` / `KARGO_DB_PASSWORD` / `KARGO_DB_NAME`, чтобы реквизиты
контейнера-однодневки не читались потом как боевые. `KARGO_API_TOKEN` оставить —
он нужен для `/api/kargo/…`. Перезапустить бэкенд.

**Cron из шага 7 не заводить**: синхронизировать с замороженным снимком нечего,
инкремент будет только затирать свежие данные.

Дамп содержит персональные данные ~9 700 клиентов и хеши их паролей — удалить и
с сервера, и с рабочей машины.

## Шаг 5а. Указать регион Kargoosh у точек Loko

Без этого ожидаемые посылки («в пути» с сайта) уйдут на служебные филиалы
«Kargo · …», и складовщики их не увидят. Админом: «Филиалы» → изменить точку →
поле «Регион в Kargoosh»: у обеих точек Оша — `Ош`, у Бишкека — `Бишкек`,
у Кара-суу — `Кара-суу`. Служебные филиалы «Kargo · …» после этого можно
отключить (снять «Активен»).

## Шаг 5б. Закрепить старые заявки клиентов за сотрудниками

Заявки, созданные клиентами по QR до выката, оставались без сотрудника, и их
продажи никому не засчитывались. Один раз после выката:

```bash
docker compose exec -T backend python manage.py assign_client_orders --dry-run
docker compose exec -T backend python manage.py assign_client_orders
```

Филиалы, где сотрудников несколько или нет, команда пропустит и перечислит:

```bash
docker compose exec -T backend python manage.py assign_client_orders --branch <id> --operator <логин>
```

## Шаг 5в. Склеить клиентов-дублей по телефону

Раньше QR-страница хранила номер как ввёл клиент («996700…»), а импорт с сайта —
9 цифр («700…»): один человек мог оказаться двумя клиентами. Один раз после выката:

```bash
docker compose exec -T backend python manage.py merge_duplicate_clients --dry-run
docker compose exec -T backend python manage.py merge_duplicate_clients
```

Приоритет у аккаунта с сайта; заявки и оценки переносятся, номера приводятся к
9 цифрам (`Client.normalize_phone`).

## Шаг 6. Проверка после импорта

```bash
cd /opt/loko/infra && docker compose exec -T backend python manage.py shell -c "
from finance.models import Account, Branch
from finance.reports import build_pnl
from express.models import Sale, Client
print('филиалы', Branch.objects.count(), '| счета', Account.objects.count(), '| клиенты', Client.objects.count(), '| продажи', Sale.objects.count())
print('из Kargo: продаж', Sale.objects.filter(legacy_kargo_id__isnull=False).count())
p = build_pnl(module='EXPRESS')
print('Express выручка', p['revenue'], '| себест', p['cogs'], '| ЧП', p['net_profit'])
"
```

Главная сверка: **выручка после импорта == выручка до импорта + Σ заказов
источника**, до копейки. 04.09.2026: 255 758 451.92 = 10 686 241.93 + 245 072 209.99.

В панели проверить «Клиенты» — поиск по телефону клиента Kargo. Телефоны там
хранятся девятизначными, без «996», нормализация — `express/kargo.py::phone_candidates`;
искать должно и с «+996», и без.

**Филиалов станет на 6 больше** (регионы Kargo), и они попадут во все выпадающие
списки, включая публичный `/api/public/branches/` на QR-странице. Если по этим
регионам QR-приём не планируется — снять у них «Активен» в разделе «Филиалы».

## Шаг 7. Cron (только при живом двустороннем мосте)

```cron
*/5 * * * *  cd /opt/loko/infra && docker compose exec -T backend python manage.py import_kargoosh --incremental >> /var/log/loko-kargo-sync.log 2>&1
15 3 * * *   cd /opt/loko/infra && docker compose exec -T backend python manage.py import_kargoosh --rescan      >> /var/log/loko-kargo-sync.log 2>&1
```

Логротация: `/etc/logrotate.d/loko-kargo` с `weekly, rotate 8, compress`.

## Шаг 8. Проверка моста в обе стороны (когда доступ откроют)

**Kargoosh → Loko.** Зарегистрировать клиента на kargoosh.kg, через ≤ 5 мин найти
его в Loko: «Клиенты» → поиск по телефону; в логе строка `клиенты: +1 новых`.

**Loko → Kargoosh.** В Loko создать заявку с кодом этого клиента и оприходовать с
весом. Затем в MySQL сайта:

```bash
docker compose exec -T backend python - <<'PY'
import pymysql, os
c = pymysql.connect(host=os.environ["KARGO_DB_HOST"], port=int(os.environ["KARGO_DB_PORT"]),
    user=os.environ["KARGO_DB_USER"], password=os.environ["KARGO_DB_PASSWORD"], database=os.environ["KARGO_DB_NAME"])
cur = c.cursor(pymysql.cursors.DictCursor)
cur.execute("SELECT pk_i_id, s_user_code, s_tracking_number, i_weight, i_price, i_status, dt_arrival FROM orders ORDER BY pk_i_id DESC LIMIT 3")
for r in cur.fetchall(): print(r)
PY
```

Ожидается строка с кодом клиента, `i_status=2`, весом и суммой; трек `LOKO-<id>`,
если складовщик его не вводил. После выдачи заявки статус станет 3.

Состояние синхронизации: `GET /api/kargo/sync/` с заголовком `X-Kargo-Token`.

## Шаг 9 (опционально). Домены kargoosh.kg для сотрудников

Конфиги в `infra/nginx/*.kargoosh.kg.conf` (инструкции в шапке файлов: symlink в
`sites-enabled`, `certbot --nginx`, отдельная сборка SPA в `/srv/www/kargoosh-panel`).
DNS A-записи на `157.250.205.157` заводятся у hoster.kg. `panel.` закрыть от
индексации (`X-Robots-Tag: noindex`).

## Эксплуатация

- **Мониторинг**: `tail -50 /var/log/loko-kargo-sync.log` (искать ✗ и Traceback);
  в Loko — таблица «Синхронизации Kargo» (`express.KargoSync`) или `GET /api/kargo/sync/`.
- **Выключить мост**: очистить `KARGO_DB_HOST` в `.env` + перезапуск бэкенда,
  закомментировать cron. Loko продолжает работать сам; непереданные продажи
  копятся с флагом `kargo_sync_pending` и уйдут после включения (`manage.py push_kargoosh`).
- **Откат данных Loko**: `/srv/backups/loko-*.sql.gz` (шаг 0). Импортированные
  строки помечены `legacy_kargo_id`, их можно снять и точечно.
- **Откат данных сайта**: дамп из шага 4. Строки, записанные Loko, отличаются
  треком `LOKO-…` или `fk_i_admin_id` из `KARGO_DEFAULT_ADMIN_ID` и `fk_i_transaction_id IS NULL`.
- **Что не синхронизируется**: правки в PHP-админке по заказам, созданным в Loko
  (для них Loko главный); финжурнал Kargoosh (`transactions`); клиенты,
  зарегистрированные в Loko по QR только по телефону (на сайте нужны e-mail и пароль).
- **Секреты**: `infra/.env` не коммитить. Пароль хостинга, который был в переписке,
  сменить в ISPmanager.
