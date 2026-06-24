# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

**Loko ERP** — financial/accounting system for logistics company Loko, two independent directions:
- **Loko Express** — cargo China→Kyrgyzstan: sales (`Sale`), weight-or-direct pricing, dynamic cost, margin.
- **Loko Business** — multi-currency procurement (сом→юань→Chinese suppliers): deposits, currency conversion, debts.

Django 4.2→**6.0** backend (DRF + SimpleJWT) · React 18 + Vite SPA · SQLite (dev) / PostgreSQL (prod).

## Environment & commands

**Backend** uses the existing virtualenv at the repo root: `/Users/azatmurzaev/Documents/loko/.venv` (Python 3.13). Do NOT create a new venv. Django 6.0 needs **Python 3.12+**.

```bash
VENV=/Users/azatmurzaev/Documents/loko/.venv/bin
cd backend
$VENV/python manage.py runserver 127.0.0.1:8009   # frontend proxies /api → 8009 (see frontend/.env)
$VENV/python manage.py migrate
$VENV/python manage.py check
$VENV/python manage.py test                        # tests.py files are currently empty stubs
$VENV/python manage.py spectacular --validate --fail-on-warn   # OpenAPI schema MUST stay 0-warning
$VENV/python manage.py seed                        # admin/kassir + default accounts (passwords via env, see below)
```

**Frontend** (Vite on :5174 via `.claude/launch.json` config `loko-frontend`; proxies `/api`→8009):
```bash
cd frontend
npm ci
npm run dev      # or use preview_start with config name "loko-frontend"
npm run build    # vite build → dist/
npm run lint     # oxlint
```

**Real-data importers** (load the source Excel files; idempotent — they delete+recreate their own data):
```bash
$VENV/python manage.py import_business                                   # hardcoded from «Баяман.xlsx» — no file arg
$VENV/python manage.py import_express_journal --path "<…Локо…xlsx>"      # reads sheet «4. Журнал операций»
```

## Architecture — the big picture

Backend apps: `accounts` (custom User, ADMIN/MANAGER roles, JWT), `finance` (core: Account, Expense, Transfer, AppSettings singleton, **`reports.py`** engine), `express` (Sale), `business` (Deposit, Debt). API mounted under `/api/` (`loko/urls.py`); login is the only public endpoint.

**`finance/reports.py` is the heart** — read it to understand the system. Key invariants:

- **Accrual vs cash separation.** P&L (ОПиУ, `build_pnl`) is computed by **accrual** (`Sale.price_som`/`Expense.amount` on `date`). Cash Flow (ОДДС, `build_cashflow`) by **actual payment** (`paid_som`/`paid_amount` on `payment_date`). The difference = receivables/payables. Sale/Expense carry both an accrued amount + a paid amount and two dates.

- **Multi-currency consolidation.** Accounts are KGS or CNY. All report sums consolidate to сом via `to_kgs()` using `AppSettings.cny_to_kgs_rate` (production = **13.1**).

- **Dual profit tax by payment channel** (editable in Settings): cash `cash_tax_rate` (6%), non-cash `noncash_tax_rate` (4%), applied to **pre-tax profit**. `build_pnl` factors the pre-tax computation into `_pnl_base(payment)`; for `payment="all"` it taxes each channel's pre-tax profit at its own rate and sums. `?tax_rate=` is a flat override. Deposits are split by account kind (CASH/BANK) so per-channel sub-P&Ls add up to the total — do not break this.

- **3-section cash flow.** `build_cashflow` groups outflows into **Operating** (OPEX/COGS/SUPPLIER/OTHER), **Investing** (`ExpenseCategory.INVEST`), **Financing** (`OWNER` + `FINANCING`). Capex (INVEST) and financing do NOT hit the P&L — only the cash flow.

- **Deposits are not revenue automatically** (`business/models.py`): created `HELD` → become revenue only via `recognize_as_revenue()` (`RECOGNIZED`), or forwarded to a supplier (creates a `SUPPLIER` expense, `SENT_SUPPLIER`). Client prepayments stay as advances until the order closes.

- **Sale pricing** (`express/models.py::_apply_pricing`): two modes — WEIGHT (`weight × price_per_kg_usd × usd_rate_som`) or DIRECT (manual `price_som`). Pricing params are snapshotted at save. Weight is **optional**. Cost is dynamic from weight unless `cost_is_manual=True` (then `cost_som` is taken as entered). Margin = price − cost.

- **Drill-down**: `GET /api/reports/breakdown/?line=…&basis=accrual|cash` (`reports.py::breakdown`) returns the individual operations behind any report line; the Reports UI makes lines clickable.

API docs: drf-spectacular at `/api/schema/`, `/api/docs/`, `/api/redoc/` — **auth-gated** (`SERVE_PERMISSIONS=IsAuthenticated`). Keep schema generation warning-free (annotate views with `@extend_schema`).

**Frontend**: `api/client.js` (axios, attaches JWT, one-shot refresh on 401), `lib/hooks.js::useFetch`, `auth/AuthContext`. Pages map 1:1 to the sidebar groups (Express / Business / Финансы / Админ). Reports/Sales/Expenses are the richest pages.

## Source data & reconciliation

Two Excel files drove the model (under `~/Documents`, not in git):
- **«Локо Бизнес 2.0.xlsx»** / its source **«Баяман.xlsx»** → Business. `import_business` is a faithful, hardcoded transcription. Control totals (must reconcile to the kopeck): выручка **520 605**, себестоимость **475 304.30**, прибыль до налогов **34 820.70**, итоговый остаток **926 265.83**. Client приходы 920 605 = 520 605 recognized + 400 000 advances (Авенир, Азамжон).
- **«Финансовый учет карго компании Локо.xlsx»** → Express. The file is a broken template (~940 formula errors); real per-row amounts live in column **AJ «Сумма по тетради»**, which `import_express_journal` reads (cleans `?`/`/` amounts, fixes broken dates like `16.06.20226`). ≈2206 sales / 163 expenses, revenue ≈4.42M.

To move the verified dev data into prod, dump a fixture and `loaddata` (clear operations+accounts first, then load): `dumpdata finance.Account finance.AppSettings express.Sale finance.Expense finance.Transfer business.Deposit business.Debt`. Do NOT commit client-data fixtures to git.

## Deployment (production is LIVE)

VPS (Ubuntu, IP **157.250.205.157**, repo at `/opt/loko`) running **Docker** (Django+gunicorn, postgres:17 db `loko`/user `lokobooking`/port **5434**) behind **host nginx + Cloudflare**. Domains: `lokobooking.com`+`www` → SPA (`/srv/www/lokobooking`), `api.lokobooking.com` → backend. TLS via **Cloudflare Origin Certificate** + SSL/TLS mode **Full (strict)** (records are Proxied/orange; certbot is NOT used). All config in `infra/` (Dockerfiles, docker-compose.yml, .env.example, README.md). `infra/.env` is gitignored.

Redeploy: `cd /opt/loko && git pull && cd infra && docker compose up -d --build backend && docker compose --profile build run --rm --build frontend` (migrations run via entrypoint).

**Gotchas learned in production:**
- DNS A-records must point to the **real VPS IP** (a wrong IP → Cloudflare 526; symptoms look like a TLS/origin problem but it's DNS).
- nginx vhosts must be symlinked into `sites-enabled` (without it only the default site loads → no :443).
- `ufw allow 'Nginx Full'` only works **after** nginx is installed (the profile ships with the package).
- `settings.py` fails closed: with `DEBUG=False` it raises if `SECRET_KEY` is missing/insecure.
- Keep `SEED_ON_START=0` in prod so container restarts don't reseed over real data. In production (`DEBUG=False`) `seed` creates users WITHOUT a usable password unless `SEED_ADMIN_PASSWORD`/`SEED_KASSIR_PASSWORD` are set.
- Behind the reverse proxy, `USE_CLOUDFLARE=True` enables `SECURE_PROXY_SSL_HEADER` + secure cookies; the backend Docker CMD overrides gunicorn to `-b 0.0.0.0:8000 --forwarded-allow-ips=*`.

## Conventions

- Money is `Decimal`, quantized to 2 places (`finance.models`, `express.models._money`). Reports return plain dicts (not serializers) — annotated for drf-spectacular with `@extend_schema(responses=OpenApiTypes.OBJECT)`.
- Roles: ADMIN manages users/accounts/settings; MANAGER (kassir) records all operations + reads reports (see each viewset's `get_permissions`).
- UI/copy is Russian; commit messages in this repo are Russian.
