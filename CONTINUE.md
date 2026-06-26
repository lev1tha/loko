# Loko ERP — состояние проекта и как продолжить

> Это файл-передача для продолжения работы в новой сессии. Кратко: что сделано,
> как запустить, что в проде, что осталось, и где грабли.

## 1. Что это
ERP для логистической компании **Loko**. Два направления:
- **Loko Express** — карго Китай→КР (продажи, расходы, маржа).
- **Loko Business** — мультивалютные закупки (сом↔юань), депозиты, долги, заказы/маржа.

Стек: **Django 4.2 + DRF + SimpleJWT** (backend) · **React 18 + Vite** (frontend) · дизайн Cal.com.
Репозиторий: `github.com/lev1tha/loko` (монорепо: `backend/` + `frontend/`, чистый).

## 2. Запуск локально
> На этой машине порты **8000 и 5173 заняты** сторонними процессами → используем **8009 / 5174**.
> `frontend/.env` уже содержит `VITE_BACKEND_URL=http://127.0.0.1:8009`.

```bash
# Backend (порт 8009)
cd backend && source venv/bin/activate && python manage.py runserver 127.0.0.1:8009

# Frontend (порт 5174) — в другом терминале
cd frontend && npm run dev -- --port 5174 --strictPort
```
Открыть **http://localhost:5174** · логины: `admin / admin123`, `kassir / kassir123`.

## 3. Данные (реальные, из Excel заказчика)
- **Express**: 2224 продажи + расходы. Импорт из «Финансовый_учет_Локо…xlsx» (есть метод оплаты:
  Оптима/Мбанк/Наличные/Банк не указан). Выручка ≈ 4.42 млн сом.
  Веса проставлены (вес = цена/270); себестоимость Express = 0 (cost не считали от веса).
- **Business**: импорт из «Локо Бизнес 2.0.xlsx» (проверен против исходника «Баяман.xlsx»).
  Сходится до копейки: выручка **520 605**, себестоимость **475 304.30**, остаток **926 265.83** сом.
  Курс юаня **13.1**, налог на прибыль **4%**.

### Команды импорта (если надо перезалить)
```bash
python manage.py seed                       # пользователи, счета, настройки
python manage.py import_express  --path "<…Финансовый_учет_Локо…xlsx>"   # старый файл, с методом оплаты
python manage.py import_express_journal --path "<…Локо1.xlsx>"           # формат «журнал», чистит «?»/битые даты
python manage.py import_business            # Business из «Локо Бизнес 2.0» (пути зашиты в команде)
```
Файлы заказчика лежат в `~/Downloads/`.

## 4. Что уже сделано (фичи)
- CRUD продаж и расходов (создание/**редактирование**/удаление), дата оплаты по умолчанию = сегодня.
- Цена ↔ вес: режим «по весу» (вес×3$×90) и «прямая сумма».
- ОПиУ (многоуровневый: валовая маржа %, опер.прибыль, налог, чистая рентаб.) и ОДДС (остаток
  начало/конец, секции, «Свод оплат» по счетам). Фильтр **направления** (Всё/Express/Business).
- **Расшифровка строк отчёта**: клик по «Выручка»/«Расходы»/строке → модалка с операциями
  (№, дата, назначение, счёт, сумма). Эндпоинт `/api/reports/breakdown/?line=…&basis=accrual|cash`.
- **Заказы Business** (маржа по клиентам) + раскрытие в детальные операции (даты/номера D-/E-).
- Депозиты (признать выручку / отправить поставщику), Долги (ДЗ/КЗ), Конвертация валют.
- Пагинация: списки отдают весь период через `?page_size=10000`.
- Фиксы: таймзона дат (`format.js` localISO), выравнивание таблиц (`.table th.num`), грид.

## 5. Деплой / Cloudflare
**Фронтенд — ЖИВ:** https://loko.up1mepdev.workers.dev (Worker static assets, отдаёт `dist/`).
Залит вручную: `cd frontend && npm run build && npx wrangler deploy`.
Аккаунт Cloudflare: `up1mepdev@gmail.com`, Account ID `a66b528c955eeb2752d91fda40bcca83`.
Wrangler авторизован локально (`wrangler login` уже сделан).

> ⚠️ **ГЛАВНАЯ ГРАБЛЯ:** в дашборде Cloudflare остался **сломанный Git-автодеплой** (тип «Workers
> Builds / Static»). На каждый `git push` он **перезаливает исходники** `frontend/` (не собирая) —
> и прод ломается (`/src/main.jsx`, ошибка `text/jsx`). 
> **Решение:** отключить автосборку (проект `loko` → Settings → Builds → Disconnect), а деплоить
> только командой `cd frontend && npm run build && npx wrangler deploy`. Пока не отключён — после
> любого пуша надо передеплоить вручную этой командой.

**Бэкенд — НЕ задеплоен публично.** Крутится только локально на Маке (8009). Поэтому **вход на
живом фронте пока не работает** (нужен публичный API). Варианты:
1. Временный туннель с Мака: `cloudflared tunnel --url http://localhost:8009` → `*.trycloudflare.com`
   (cloudflared НЕ установлен; ставить `brew install cloudflared`). Потом вписать адрес в
   `frontend/.env.production` → `VITE_API_BASE_URL` → пересобрать+передеплоить фронт.
2. VPS (постоянно): см. `DEPLOY.md` (gunicorn + cloudflared tunnel + R2 + WAF).

Готовое для деплоя: `DEPLOY.md`, `deploy/*`, `.github/workflows/deploy-frontend.yml`,
прод-настройки в `backend/loko/settings.py` (R2/Postgres/WhiteNoise — под env-флагами).

## 6. Открытые вопросы (спросить пользователя)
- **Себестоимость Express от веса?** Сейчас Express cost=0 (маржа 100%). Предложено считать
  `вес × 150` или `× 190` сом/кг (в «Локо1» закуп = 190/кг). Ставку не подтвердили.
- **Ограничить edit/delete только админом?** Сейчас может любой вошедший (и кассир).
- **Отключить сломанный Cloudflare Git-автодеплой** (см. грабля выше).
- Бэкенд в прод: туннель с Мака или VPS — пользователь не решил (нужен ли 24/7).

## 7. Грабли/важное
- **SQLite F-деление целочисленное** (`200/270=0`). Для арифметики в обновлениях — Python `Decimal`.
- Ценообразование: цена = `вес × price_per_kg_usd(3) × usd_rate_som(90)` = вес×270. Снимок ставок
  хранится в каждой `Sale`. Себестоимость база 150/кг (реально 190). Юань 13.1.
- ОПиУ — по **начислению** и **дате операции**; ОДДС — по **оплате** и **дате оплаты**.
- Все суммы консолидируются в сомы; CNY→KGS по `cny_to_kgs_rate` из настроек.
- Данные датированы **июнь 2026**; системная дата машины — 2026-06-24.
- Серверы запускаются как фоновые bash-процессы; при «killed» — перезапустить командами из п.2.
- `backend/.env`, `db.sqlite3`, `venv`, `node_modules`, `dist` — в `.gitignore` (в репо не коммитятся).

## 8. Структура
```
backend/  loko(settings,urls) · accounts(User+роли,JWT,seed) · finance(Account,Expense,Transfer,
          AppSettings, reports.py — ВСЯ логика отчётов/разбивки) · express(Sale) · business(Deposit,Debt)
frontend/ src/pages(Sales,Expenses,Accounts,Transfers,Deposits,Debts,BusinessOrders,Reports,Settings,Users,Login)
          src/components(Layout,ui,icons) · src/api/client.js(axios+JWT) · src/lib(format,hooks)
DEPLOY.md · CONTINUE.md(этот файл) · deploy/ · .github/workflows/
```
Главный файл логики: **`backend/finance/reports.py`** (ОПиУ, ОДДС, balances, debts, business_orders, breakdown).
