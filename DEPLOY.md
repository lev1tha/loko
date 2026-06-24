# Деплой Loko ERP в Cloudflare

Полное руководство: фронтенд → **Cloudflare Pages**, бэкенд (Django) → **Cloudflare Tunnel**,
медиа → **R2**, защита → **WAF/Rate Limiting**. Всё в рамках Free Tier.

> Домены в примерах: `app.loko.kg` (фронтенд), `api.loko.kg` (бэкенд), `media.loko.kg` (R2).
> Замените на свои. Используйте **один** домен/зону для всего, чтобы SSL и DNS были едины.

```
Пользователь
   │  https://app.loko.kg            https://api.loko.kg
   ▼                                        ▼
Cloudflare Pages (dist/)  ──fetch──►  Cloudflare (WAF/Cache)
                                            │  Tunnel (cloudflared)
                                            ▼
                                   VPS: gunicorn → Django :8000
                                            │
                                   PostgreSQL   +   R2 (media.loko.kg)
```

---

## 0. Привязка домена к Cloudflare (DNS / NS)

1. Cloudflare Dashboard → **Add a site** → введите ваш домен (`loko.kg`) → план **Free**.
2. Cloudflare покажет **2 NS-сервера** (напр. `nina.ns.cloudflare.com`, `rob.ns.cloudflare.com`).
3. В панели вашего регистратора домена замените NS-серверы на эти два. Распространение — до 24ч.
4. Когда зона станет **Active**, включите **SSL/TLS → Overview → Full (strict)**.

DNS-записи, которые мы создадим ниже (итог):

| Тип | Имя | Значение | Proxy |
|-----|-----|----------|-------|
| CNAME | `app` | `loko-erp.pages.dev` | 🟧 Proxied |
| CNAME | `api` | `<TUNNEL_ID>.cfargotunnel.com` | 🟧 Proxied (создаётся командой `tunnel route dns`) |
| CNAME | `media` | публичный хост R2-бакета | 🟧 Proxied |

---

## 1. Фронтенд → Cloudflare Pages

Файлы уже готовы: `frontend/wrangler.toml`, `frontend/.env.production`,
`frontend/public/_redirects` (SPA), `frontend/public/_headers` (безопасность).

### Вариант CLI (быстро)
```bash
# 1. Укажите боевой адрес API
#    frontend/.env.production → VITE_API_BASE_URL=https://api.loko.kg/api

# 2. Залогиньтесь и задеплойте
cd frontend
npx wrangler login                       # откроет браузер
./../deploy/deploy-frontend.sh           # npm ci → build → wrangler pages deploy dist
```
Скрипт создаст проект `loko-erp` и выдаст URL `https://loko-erp.pages.dev`.

### Вариант Git (CI/CD автодеплой)
Pages → **Create application → Connect to Git** → выберите репозиторий →
- **Framework preset:** Vite
- **Build command:** `npm run build`
- **Build output directory:** `dist`
- **Root directory:** `frontend`
- **Environment variables:** `VITE_API_BASE_URL=https://api.loko.kg/api`, `NODE_VERSION=20`

Каждый `git push` → автоматическая пересборка и деплой.

### Вариант CI/CD — GitHub Actions (автодеплой по push)
Готовый workflow: [`.github/workflows/deploy-frontend.yml`](.github/workflows/deploy-frontend.yml).
Каждый `git push` в `main` (с изменениями в `frontend/`) → сборка и деплой в Pages.

Однократная настройка (всё на твоей стороне — токен я не вижу):
1. Cloudflare → **My Profile → API Tokens → Create Token** → шаблон «Edit Cloudflare Pages» →
   скопируй токен. Узнай **Account ID** (Cloudflare → Overview, справа).
2. GitHub → репозиторий → **Settings → Secrets and variables → Actions**:
   - **Secrets:** `CLOUDFLARE_API_TOKEN`, `CLOUDFLARE_ACCOUNT_ID`
   - **Variables:** `VITE_API_BASE_URL = https://api.<твой-домен>/api`
3. `git push` — деплой пойдёт сам (вкладка **Actions**).

### Кастомный домен + SSL
> ⚠️ Домен должен быть **зарегистрирован на тебя** (купи свободный у регистратора; `loko.com`
> скорее всего занят). Без покупки система всё равно работает на бесплатном `loko-erp.pages.dev`.

Pages → проект → **Custom domains → Set up a custom domain** → `app.<твой-домен>`.
Cloudflare сам создаст CNAME и **выпустит SSL-сертификат автоматически** (1–2 мин).

---

## 2. Бэкенд (Django) → Cloudflare Tunnel  *(Вариант А — рекомендуется)*

Django — «тяжёлый» Python-бэкенд, на Workers (V8/JS) не запускается. Поэтому он живёт на
любом VPS/ВМ (даже без белого IP), а наружу выходит через зашифрованный туннель.

### 2.1. Подготовка сервера
```bash
# на VPS (Ubuntu/Debian), скопируйте проект в /srv/loko
sudo bash deploy/setup-backend.sh        # ставит python, postgres, cloudflared, зависимости
sudo cp /srv/loko/backend/.env.example /srv/loko/backend/.env
sudo nano /srv/loko/backend/.env         # заполните SECRET_KEY, домены, POSTGRES_*, R2_*
```
Ключевые переменные `.env` (см. `backend/.env.example`):
```
DEBUG=False
USE_CLOUDFLARE=True
ALLOWED_HOSTS=api.loko.kg,localhost,127.0.0.1
CORS_ALLOWED_ORIGINS=https://app.loko.kg
CSRF_TRUSTED_ORIGINS=https://app.loko.kg,https://api.loko.kg
POSTGRES_DB=loko ...
```

### 2.2. Запуск Django (gunicorn) как сервис
```bash
sudo cp deploy/loko-backend.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now loko-backend     # gunicorn слушает 127.0.0.1:8000
```

### 2.3. Туннель (cloudflared)
```bash
cloudflared tunnel login                      # авторизация в вашей зоне
cloudflared tunnel create loko-api            # создаст <TUNNEL_ID>.json
sudo cp deploy/cloudflared-config.yml /etc/cloudflared/config.yml
sudo nano /etc/cloudflared/config.yml         # впишите <TUNNEL_ID> в credentials-file
cloudflared tunnel route dns loko-api api.loko.kg   # создаёт CNAME api → туннель
sudo cloudflared service install
sudo systemctl enable --now cloudflared
```
Готово: `https://api.loko.kg/api/...` идёт через Cloudflare → туннель → gunicorn.
Порты наружу **не открыты**, TLS терминируется на Cloudflare.

Проверка:
```bash
curl -X POST https://api.loko.kg/api/auth/login/ \
  -H "Content-Type: application/json" -d '{"username":"admin","password":"admin123"}'
```

---

## 3. Медиа-файлы → Cloudflare R2 (django-storages)

Настройки уже в `backend/loko/settings.py` (блок R2, активируется переменной `R2_BUCKET`).

1. Cloudflare → **R2 → Create bucket** → `loko-media`.
2. **R2 → Manage API Tokens → Create** (Object Read & Write) → получите `Access Key ID` / `Secret`.
3. Узнайте endpoint: `https://<ACCOUNT_ID>.r2.cloudflarestorage.com`.
4. Бакет → **Settings → Public access → Connect a domain** → `media.loko.kg` (Cloudflare создаст CNAME + SSL).
5. Заполните в `.env`:
   ```
   R2_BUCKET=loko-media
   R2_ACCESS_KEY_ID=...
   R2_SECRET_ACCESS_KEY=...
   R2_ENDPOINT_URL=https://<ACCOUNT_ID>.r2.cloudflarestorage.com
   R2_PUBLIC_DOMAIN=media.loko.kg
   ```
6. `systemctl restart loko-backend`. Теперь `FileField`/`ImageField` (чеки, фото товаров)
   грузятся в R2, а отдаются с `https://media.loko.kg/...` — **исходящий трафик бесплатен**.

Первые 10 ГБ хранилища и весь egress — бесплатно.

---

## 4. Защита: WAF, Rate Limiting, Cache Rules

> Наш эндпоинт авторизации — **`/api/auth/login/`** (в ТЗ упоминался `/api/token/`; у нас он
> называется иначе — защищаем реальный путь).

### 4.1. Rate Limiting на логин (защита от брутфорса)
Cloudflare → домен → **Security → WAF → Rate limiting rules → Create**:
- **If incoming requests match:** `URI Path` `equals` `/api/auth/login/`
- **When rate exceeds:** `10` requests per `1 minute` per **client IP**
- **Then:** `Block` (или Managed Challenge) на `10 minutes`

### 4.2. WAF Custom Rules (базовая защита API)
**Security → WAF → Custom rules → Create**:
- Правило «block non-API noise»:
  `(http.host eq "api.loko.kg" and not starts_with(http.request.uri.path, "/api/") and not starts_with(http.request.uri.path, "/admin/"))` → **Block**
- Включите **Managed Rules** (OWASP) и **Bot Fight Mode** (Security → Bots) — бесплатно.

### 4.3. DDoS
L3/L4/L7 DDoS-защита включена **по умолчанию** на всех проксируемых (🟧) записях — отдельной
настройки не требует. Убедитесь, что `app`/`api`/`media` стоят в режиме **Proxied**.

### 4.4. Cache Rules для аналитики (снижение нагрузки на бэкенд)
Отчёты ООПИУ/ОДДС читаются часто и меняются редко — закешируем их на Edge.
**Caching → Cache Rules → Create**:
- **If:** `(http.host eq "api.loko.kg" and starts_with(http.request.uri.path, "/api/reports/"))`
- **Then:** *Eligible for cache* → **Edge TTL: 60s**, *Cache key* → include header `Authorization`
  (чтобы кэш был раздельным по пользователю).

> Важно: кэшируйте только **GET /api/reports/**. Логин, продажи, расходы (POST/PUT) — `Bypass cache`.

---

## 5. Финальный чек-лист

- [ ] Домен Active в Cloudflare, SSL **Full (strict)**.
- [ ] Pages: `app.loko.kg` открывается, логин работает (запросы идут на `api.loko.kg`).
- [ ] Tunnel: `https://api.loko.kg/api/auth/login/` → 200, порты на VPS закрыты (`ufw`).
- [ ] R2: загрузка файла в админке → URL `media.loko.kg`.
- [ ] WAF: rate-limit на `/api/auth/login/`, Cache Rule на `/api/reports/`.
- [ ] `DEBUG=False`, `SECRET_KEY` из `.env`, `ALLOWED_HOSTS` без `*`.

---

## Приложение: Вариант Б (Workers + D1) — почему НЕ рекомендуется сейчас

Перенос расчётов ООПИУ/ОДДС на Cloudflare Workers + D1 потребовал бы **переписать всю
бизнес-логику** (`finance/reports.py`: мультивалюта, начисление/оплата, дебиторка/кредиторка,
конвертации) с Python на JS/TS и отказаться от Django ORM, миграций, админки и JWT-стека.
Это дублирование на сотни строк с риском рассинхрона цифр.

**Рекомендация:** оставить Django как единый источник правды (Вариант А, Tunnel), а Workers/D1
рассматривать позже только для отдельного «read-only» кэш-слоя витрины отчётов, если понадобится
глобально-низкая задержка. Cache Rules (п. 4.4) уже дают 90% этого эффекта без переписывания.
