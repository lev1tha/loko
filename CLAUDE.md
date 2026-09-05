# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

**Loko ERP** — financial/accounting + operations system for logistics company Loko, two independent directions:
- **Loko Express** — cargo China→Kyrgyzstan: multi-branch sales (`Sale`), a **warehouse module** (заявка → позиции → оприходование), клиенты по QR, weight-or-direct pricing, dynamic cost, margin.
- **Loko Business** — multi-currency procurement (сом→юань→Chinese suppliers): deposits, currency conversion, debts.

Plus an **integration with kargoosh.kg** (the PHP client-facing site of Kargo Osh): Loko is the single source of truth, the site is the client's face. See `INTEGRATION-KARGOOSH.md`, `KARGO-API.md`, `infra/KARGOOSH-DEPLOY.md`.

Django 4.2→**6.0** backend (DRF + SimpleJWT) · React 18 + Vite SPA · SQLite (dev) / PostgreSQL (prod).

## Environment & commands

**Backend** uses the existing virtualenv at the repo root: `/Users/azatmurzaev/Documents/loko/.venv` (Python 3.13). Do NOT create a new venv. Django 6.0 needs **Python 3.12+**.

```bash
VENV=/Users/azatmurzaev/Documents/loko/.venv/bin
cd backend
$VENV/pip install -r requirements.txt                  # после git pull — venv отстаёт (segno, PyMySQL)
$VENV/python manage.py migrate                         # ⚠ см. «грабли dev-БД» ниже
$VENV/python manage.py runserver 127.0.0.1:8009        # frontend proxies /api → 8009 (see frontend/.env)
$VENV/python manage.py check
$VENV/python manage.py test                            # 150 тестов, все должны проходить
$VENV/python manage.py spectacular --validate --fail-on-warn   # OpenAPI schema MUST stay 0-warning
$VENV/python manage.py seed                            # admin/kassir + default accounts (passwords via env)
```

**Грабли локальной dev-БД:** после `git pull` `backend/db.sqlite3` отстаёт на миграции (локальный `runserver --noreload` их не накатывает; прод накатывает через entrypoint). Симптом — `no such table` / `no such column` на любом запросе. Всегда проверять `showmigrations` при странных ошибках. Перед `migrate` копировать `db.sqlite3` в скратчпад.

**Frontend** (Vite on :5174 via `.claude/launch.json` config `loko-frontend`; proxies `/api`→8009):
```bash
cd frontend
npm ci
npm run dev      # or use preview_start with config name "loko-frontend"
npm run build    # vite build → dist/
npm run lint     # oxlint
```

**Real-data importers** (idempotent — they delete+recreate their own data):
```bash
$VENV/python manage.py import_business                                   # hardcoded from «Баяман.xlsx» — no file arg
$VENV/python manage.py import_express_journal --path "<…Локо…xlsx>"      # sheet «4. Журнал операций»
$VENV/python manage.py import_kargoosh --dry-run                         # мост Kargo Osh (MySQL) → Loko, со сверкой
$VENV/python manage.py import_kargoosh --incremental | --rescan          # cron: инкремент / ночная сверка
$VENV/python manage.py push_kargoosh                                     # добор обратного моста Loko → Kargoosh
$VENV/python manage.py assign_client_orders --dry-run                    # закрепить QR-заявки за сотрудниками (разово)
$VENV/python manage.py merge_duplicate_clients --dry-run                  # склеить клиентов-дублей по телефону (разово)
```

## Architecture — the big picture

Backend apps: `accounts` (custom User, 5 ролей, JWT), `finance` (core: Account, **Branch**, Expense, Transfer, AppSettings singleton, **`reports.py`** engine, **`bonuses.py`**), `express` (Sale, **склад**, Client, **kargo-мост**, `workflow.py`), `business` (Deposit, Debt). API mounted under `/api/` (`loko/urls.py`); public endpoints are login, `/api/public/…` (QR) and `/api/kargo/…` (token-gated).

### `finance/reports.py` is the heart — key invariants

- **Accrual vs cash separation.** P&L (ОПиУ, `build_pnl`) is computed by **accrual** (`Sale.price_som`/`Expense.amount` on `date`). Cash Flow (ОДДС, `build_cashflow`) by **actual payment** (`paid_som`/`paid_amount` on `payment_date`). The difference = receivables/payables.

- **Multi-currency consolidation.** Accounts are KGS or CNY. All report sums consolidate to сом via `to_kgs()` using `AppSettings.cny_to_kgs_rate` (production = **13.1**).

- **Dual profit tax by payment channel** (editable in Settings): cash `cash_tax_rate` (6%), non-cash `noncash_tax_rate` (4%), applied to **pre-tax profit**. `build_pnl` factors the pre-tax computation into `_pnl_base(payment)`; for `payment="all"` it taxes each channel's pre-tax profit at its own rate and sums. `?tax_rate=` is a flat override. Deposits are split by account kind (CASH/BANK) so per-channel sub-P&Ls add up — do not break this.

- **3-section cash flow.** `build_cashflow` groups outflows into **Operating** (OPEX/COGS/SUPPLIER/OTHER), **Investing** (`ExpenseCategory.INVEST`), **Financing** (`OWNER` + `FINANCING`). Capex and financing do NOT hit the P&L — only the cash flow.

- **Deposits are not revenue automatically** (`business/models.py`): created `HELD` → become revenue only via `recognize_as_revenue()` (`RECOGNIZED`), or forwarded to a supplier (creates a `SUPPLIER` expense, `SENT_SUPPLIER`).

- **Sale pricing** (`express/models.py::_apply_pricing`): two modes — WEIGHT (`weight × price_per_kg_usd × usd_rate_som`, либо индивидуальная `ClientPrice` за кг) или DIRECT (manual `price_som`). Params snapshotted at save. Weight optional. Cost dynamic from weight unless `cost_is_manual`. Margin = price − cost.

- **Expense articles** (`ExpenseArticle`) детализируют категорию внутри раздела ОДДС: операционные / инвестиционные (`PURCHASE`, `INVEST_OTHER`, …) / финансовые (`SINGLE_TAX`, займы, вклад собственника). `COMMENT_REQUIRED_ARTICLES` — «прочее» без комментария не принимается.

- **Drill-down**: `GET /api/reports/breakdown/?line=…&basis=accrual|cash` returns the individual operations behind any report line.

- **Unified journal**: `GET /api/reports/journal/?module=EXPRESS|BUSINESS` — ALL operations in one chronological feed with an `effect` tag plus totals that **reconcile to the dashboard P&L by construction** (`Journal.jsx`). Capped at 1000 rows (`_JOURNAL_CAP`); totals over all.

- **Фильтр источника** (`?source=loko|kargo|all`, добавлено 05.09.2026): после переноса 171k заказов Kargo сводные отчёты смешивали текущую работу Loko с чужой историей (выручка Express: 10.7 млн → 255.8 млн). **Дефолт — `loko`**, поэтому дашборд ведёт себя как до импорта; история доступна явным выбором. Признак истории — `Sale.legacy_kargo_id` / `Account.legacy_kargo_card_id` (`_by_source` / `_accounts_by_source`). Под «loko» понимается всё, что родилось в Loko, **включая заказы Kargo-цикла через `/api/kargo/…`** — это текущая работа, а не история. Фильтровать нужно только `Sale` и `Account`: импорт больше ничего не создавал. Себестоимость Express (55%) считается от ОТФИЛЬТРОВАННОЙ выручки. Тесты — `finance/tests_source_filter.py`, ключевой инвариант: `loko + kargo == all`.

- **Multi-currency in lists**: `ExpenseSerializer`/`DepositSerializer` expose `amount_kgs` (+ `account_currency`). Reuse this for any new list summing money across CNY/KGS accounts (don't sum raw `amount`).

### Warehouse module (Loko Express) — двухэтапный учёт

`WarehouseOrder` (заявка филиала, 1–50 кодов) → `WarehouseItem` (одна позиция = один код клиента). **Финансовый инвариант: продажа существует только у позиций `FOUND`/`DELIVERED`** (`WarehouseItem.FINANCIAL`). Оператор создаёт заявку — денег ещё нет; складовщик оприходует поштучно (`WarehouseItem.receive(weight, account)` → создаёт `Sale` по тарифу, и только тогда позиция попадает в ОПиУ/ОДДС/кассу), либо `mark_not_found()` (продажа НЕ создаётся), либо `send_to_evening()` (вечерний допоиск). Заявка ведётся по статусам через `WarehouseOrder.TRANSITIONS` — переходы валидируются, не изобретать свои.

**Ожидаемые посылки** (`express/kargo_expected.py`, добавлено 05.09.2026): как только сайт узнаёт трек-номер, импорт создаёт продажу `delivery_status=TRANSIT`, а `sync_expected()` (вызывается из `import_kargoosh`) делает из неё заявку `origin=KARGO` с позицией `WarehouseItem.Status.EXPECTED` — складовщик заранее видит, что должно приехать. При оприходовании **обновляется та же продажа**, дублей не возникает. Филиал выбирается по `Branch.legacy_kargo_region` — точка Loko того же региона, где есть складовщик; **без заполненного региона ожидаемые уходят на служебные филиалы «Kargo · …» и склад их не видит** (см. `infra/KARGOOSH-DEPLOY.md` шаг 5а). Отправленное больше 60 дней назад (`STALE_DAYS`) с доски убирается, в отчётах остаётся.

`WarehouseOrder.origin`: `OPERATOR` (создал сотрудник) · `CLIENT` (QR) · `KARGO` (мост завёл из заказов сайта). `EXPECTED`-позиции не считаются работой сотрудников — `workflow.py` их исключает из счётчиков.

**Атрибуция продажи**: `WarehouseOrder.created_by` — сотрудник, которому засчитывается продажа. Заявка от клиента по QR закрепляется автоматически, если в филиале ровно один сотрудник (`resolve_operator`), иначе выбор делает складовщик при оприходовании.

`express/workflow.py` — движок «Процесс работы» (кто что сделал за период + живая доска) и остаток склада (`WarehouseStock`: приход вводит директор, расход считается из веса продаж филиала).

### Роли и рабочие места

| Роль | Что видит | Фронтенд |
|---|---|---|
| `ADMIN` | всё; пользователи, счета, настройки, филиалы | полное приложение (`Layout`) |
| `MANAGER` (кассир) | все операции + отчёты | полное приложение |
| `DIRECTOR` | отчёты ОПиУ/ОДДС, процесс работы, остаток склада; **вносит доходы/расходы, удаляет только свои** | `DirectorLayout` |
| `OPERATOR` (сотрудник) | только своя продажа + «Мои продажи»; финансов не видит | `OperatorLayout` |
| `WAREHOUSE` (складовщик) | доска сборки своего филиала | `WarehouseLayout` |

Права — в `accounts/permissions.py` (`SalesAccess`, `WarehouseAccess`, `DirectorEntryAccess`, `DenyOperatorOrDirector`, …) плюс `get_permissions` вьюсетов. Директор по умолчанию видит своё направление (`user.module`), `?module=all` — сводно (`finance/views.py::_scoped_module`). У каждой роли отдельное SPA в `App.jsx` — не смешивать.

**Филиалы** (`finance.Branch`): операции тегируются филиалом, `Branch.resolve_default()` подставляет дефолтный. У филиала свой `price_per_kg_som` (для Kargo-заказов) и QR-код на клиентскую страницу (`segno`, эндпоинт в `BranchViewSet`).

**Бонусы** (`finance/bonuses.py`, `EmployeeBonus`): месячный KPI из 7 частей — оклад, дисциплина, тайный клиент, оборот кг филиала, звёзды клиентов, стаж, отзывы. Оборот и стаж считаются из данных, остальное ручное; звёзды авто-подтягиваются из `EmployeeRating` (ручное значение переопределяет). Пороговые тарифы — `tier_bonus()`.

### Клиенты и публичная QR-страница

`express.Client` — узнаётся по **телефону**. `normalize_phone()` приводит киргизские номера к **9 цифрам** без «996» и ведущего «0» — как хранит kargoosh.kg, чтобы «+996 700 12 34 56», «0700123456» и «700123456» были одним клиентом. Записи, созданные до унификации, склеивает разовая команда `merge_duplicate_clients` (приоритет у аккаунта с сайта; заявки и оценки переносятся). Публичная страница `/track?b=<branch>` (`frontend/src/client/ClientApp.jsx`, вне `AuthProvider`) — самозапись кодов, трекинг, бонус (за каждые 20 кг — 0.5 кг бесплатно), оценка сотрудника звёздами. Эндпоинты `/api/public/{branches,intake,track,rate}/` — `AllowAny`, но **под троттлингом** (`loko/throttling.py`): `public_track` отдаёт имя и посылки по любому телефону, per-IP лимит — единственное, что мешает массовому перебору номеров.

### Интеграция с kargoosh.kg

- **`/api/kargo/…`** (`express/kargo_urls.py`, `kargo_views.py`) — API для PHP-сайта: вход/регистрация/кабинет клиента, трекинг, отгрузка/прибытие/выдача заказов. Доступ по сервисному токену `X-Kargo-Token` (constant-time, **fail closed** при пустом `KARGO_API_TOKEN`), троттлинг `kargo` / `kargo_login` (последний — по `X-Kargo-Client-IP`, т.е. по конечному посетителю).
- **Пароли клиентов Kargo** — PHP-схема `md5(md5(strrev(pw)) + "test_ort")`, принимаются как есть и прозрачно апгрейдятся до Django-хеша при первом входе (`express/kargo.py::check_client_password`). Сброс паролей не нужен.
- **Цена за кг Kargo-заказа** (`kargo.py::unit_price_som`): скидка клиента → `ClientPrice` → цена филиала → Настройки. Не путать с `Sale._apply_pricing` (там своя цепочка для продаж Loko).
- **Статусы Kargo** `1/2/3` (в пути / на складе / отдан) ↔ `express.DeliveryStatus`. Заказы Kargo-цикла — всегда `AmountMode.DIRECT`, чтобы `save()` не пересчитал историческую цену.
- **Обратный мост** (`express/kargo_push.py`): `post_save` на `Sale`/`WarehouseItem`/`WarehouseOrder` помечает продажу `kargo_sync_pending` и (при `KARGO_PUSH_IMMEDIATE`) шлёт её в MySQL сайта по `on_commit`. Недошедшее добирает `push_kargoosh`. Ответный `pk_i_id` пишется в `Sale.legacy_kargo_id` — импорт видит ту же строку и не перезаписывает её.
- **`legacy_kargo_*` поля** (`Client`, `Sale`, `Account.legacy_kargo_card_id`, `Branch.legacy_kargo_region`) дают идемпотентность и прослеживаемость. Не удалять.
- Журнал синхронизаций — `express.KargoSync` (+ `GET /api/kargo/sync/`).

**Безопасность**: анти-брутфорс входа (`LoginRateThrottle`, 10/мин на реальный IP), политика паролей (`AUTH_PASSWORD_VALIDATORS`, применяется в `accounts/serializers.py`), blacklist JWT (`BLACKLIST_AFTER_ROTATION`). Реальный IP берётся из `CF-Connecting-IP`/`X-Real-IP` — это безопасно **только** потому, что бэкенд не смотрит наружу (см. докстринг `loko/throttling.py`).

API docs: drf-spectacular at `/api/schema/`, `/api/docs/`, `/api/redoc/` — **auth-gated**. Keep schema generation warning-free (`@extend_schema`).

**Frontend**: `api/client.js` (axios, attaches JWT, one-shot refresh on 401), `lib/hooks.js::useFetch`, `auth/AuthContext`, `lib/dialogs.jsx` (`confirm`/`prompt` + `DialogHost` — модалки вместо системных диалогов браузера; новые подтверждения делать через них). Сайдбар (`Layout.jsx`): Общее (Сводка / Сверка / История операций) · Loko Express (Продажи, Клиенты, Процесс работы, Остаток на складе, Цены клиентов, Прочий доход, Расходы, Переводы, Счета, Аналитика) · Loko Business (Счета, Заказы, Обмен, Депозиты, Поступления, Расходы, Задолженности, Калькулятор, Аналитика) · Финансы (Расходы, Аналитика, Бонусы) · Администрирование · Справка. Money in lists is shown in the account's native currency with a сом-equivalent. На «Аналитике» (`Reports.jsx`) переключатель **«Источник»** (Loko / История Kargo / Всё) — только для Express; в Business его нет, там истории Kargo не бывает.

## Source data & reconciliation

Two Excel files drove the model (under `~/Documents`, not in git):
- **«Локо Бизнес 2.0.xlsx»** / source **«Баяман.xlsx»** → Business. `import_business` is a faithful, hardcoded transcription. Control totals (must reconcile to the kopeck): выручка **520 605**, себестоимость **475 304.30**, прибыль до налогов **34 820.70**, итоговый остаток **926 265.83**.
- **«Финансовый учет карго компании Локо.xlsx»** → Express. Позже Express **пересобран из банковских выписок** (МБанк/Оптима PDF + наличка): выручка **3 170 489.17**, себестоимость **1 743 769.04** (55%), ЧП **1 299 900.56**, деньги на счетах **503 769.15**.

**Kargo Osh перенесён 04.09.2026** (`import_kargoosh` из дампа — прямого доступа к MySQL сайта нет, hoster.kg держит 3306 и 22 закрытыми): 9 672 клиента, 171 414 заказов на **245 072 209.99 сом** и **154 186.14 кг**, 8 касс на **226 448 052.90 сом**, 6 филиалов из регионов. Выручка Express стала **255 758 451.92** = 10 686 241.93 (своя) + 245 072 209.99 (импорт). Финжурнал (`transactions`, 42 529) НЕ перенесён — деньги легли начальными остатками касс, ОДДС по истории Kargo не строится. Числа источника меняются ежедневно, поэтому эталон сверки — прогон счётчиков по импортируемому дампу, а не цифры в документах (`infra/KARGOOSH-DEPLOY.md` §5.2, `INTEGRATION-KARGOOSH.md` §6).

To move verified dev data into prod, dump a fixture and `loaddata`. Do NOT commit client-data fixtures to git.

## Deployment (production is LIVE)

VPS (Ubuntu, IP **157.250.205.157**, repo at `/opt/loko`) running **Docker** (Django+gunicorn, postgres:17 db `loko`/user `lokobooking`/port **5434**) behind **host nginx + Cloudflare**. Domains: `lokobooking.com`+`www` → SPA (`/srv/www/lokobooking`), `api.lokobooking.com` → backend. Переезд под `kargoosh.kg` — поддомены `panel.` (сотрудники) и `api.` (API), конфиги в `infra/nginx/*.kargoosh.kg.conf`. TLS via **Cloudflare Origin Certificate** + mode **Full (strict)** for lokobooking; для kargoosh-поддоменов DNS прямой → `certbot --nginx`. All config in `infra/`. `infra/.env` is gitignored.

Redeploy: `cd /opt/loko && git pull && cd infra && docker compose up -d --build backend && docker compose --profile build run --rm --build frontend` (migrations run via entrypoint).

Запуск моста Kargoosh на проде — пошаговый рунбук в **`infra/KARGOOSH-DEPLOY.md`** (переменные `KARGO_*`, проверка доступа к MySQL, бэкап, первый импорт, cron, проверка в обе стороны).

**Gotchas learned in production:**
- **Перед деплоем сверить, что реально стоит на проде** (`git log -1`, `showmigrations`) — счёт миграций в рунбуках устаревает, а откаты случались (22.07.2026 прод откатывали на `f0a24f3`). Снимать `pg_dump` ДО миграций (`infra/KARGOOSH-DEPLOY.md` шаг 0). На 04.09.2026 прод на `99a1f0f`, миграции все применены.
- **Бэкенд отдельно от фронта**: `up -d --build backend` → проверить логи → и только потом собирать SPA. `docker compose up -d backend` пересоздаёт контейнер ТОЛЬКО если конфигурация изменилась — если в выводе `Running`, а не `Started`/`Recreated`, значит `.env` не менялся и новые переменные не подхватились.
- **Плейсхолдеры в `.env`**: значение вида `<openssl rand -hex 32>` дважды попадало в `KARGO_API_TOKEN` буквально. Непустой угадываемый токен ОТКРЫВАЕТ `/api/kargo/…` (проверка — простое сравнение), тогда как пустой закрывает всё. Писать только командой: `sed -i "s|^KARGO_API_TOKEN=.*|KARGO_API_TOKEN=$(openssl rand -hex 32)|" .env`.
- DNS A-records must point to the **real VPS IP** (a wrong IP → Cloudflare 526; looks like TLS but it's DNS).
- nginx vhosts must be symlinked into `sites-enabled`.
- `ufw allow 'Nginx Full'` only works **after** nginx is installed.
- `settings.py` fails closed: with `DEBUG=False` it raises if `SECRET_KEY` is missing/insecure.
- Keep `SEED_ON_START=0` in prod. In production `seed` creates users WITHOUT a usable password unless `SEED_ADMIN_PASSWORD`/`SEED_KASSIR_PASSWORD` are set.
- Behind the reverse proxy, `USE_CLOUDFLARE=True` enables `SECURE_PROXY_SSL_HEADER` + secure cookies; backend Docker CMD overrides gunicorn to `-b 0.0.0.0:8000 --forwarded-allow-ips=*`.
- `pg_dump` в контейнере требует `-p 5434`: `docker compose exec -T db pg_dump -U lokobooking -p 5434 loko`. В пайпе с gzip ошибка не рвёт `&&`-цепочку — всегда проверять размер файла.
- Бэкенд НАДО пересобрать (`up -d --build backend`) — иначе в памяти старый код отчётов.

## Conventions

- Money is `Decimal`, quantized to 2 places (`finance.models`, `express.models._money`); вес — 3 знака. Reports return plain dicts (not serializers) — annotated for drf-spectacular with `@extend_schema(responses=OpenApiTypes.OBJECT)`.
- UI/copy is Russian; commit messages in this repo are Russian.
- Новая логика — с тестами: `express/tests*.py` (склад, атрибуция, kargo, kargo_push, workflow), `finance/tests*.py`. Держать `manage.py test` зелёным и схему без warning'ов.
