# Деплой Loko ERP — VPS (Ubuntu) · Docker + host nginx + TLS

Прод-стек: **Docker** (Django 6.0 + gunicorn, PostgreSQL) за **host-nginx**.
TLS — двумя путями: **Cloudflare Origin Certificate** (если домен проксируется через Cloudflare —
рекомендуется) или **certbot/Let's Encrypt** (если DNS указывает на сервер напрямую, без прокси).
Фронтенд-SPA собирается одноразовым контейнером и отдаётся nginx'ом со статики.

```
                              ┌──────── VPS (Ubuntu) ─────────────────────────┐
  https://lokobooking.com     │  nginx (host)                                 │
  https://www.lokobooking.com │   ├─ @ / www  → /srv/www/lokobooking (SPA)    │
        │  443 (TLS)          │   └─ api      → 127.0.0.1:8000 ─┐            │
        ▼                      │                                  ▼            │
  https://api.lokobooking.com  │            docker: backend (gunicorn) ──► db │
                              │                          (postgres :5434)     │
                              └────────────────────────────────────────────────┘
```

| Поддомен (A-запись) | Назначение | Куда идёт |
|---|---|---|
| `@` (lokobooking.com) | SPA | nginx → `/srv/www/lokobooking` |
| `www` | SPA | nginx → `/srv/www/lokobooking` |
| `api` | Backend API | nginx → `127.0.0.1:8000` (docker) |

> Все три A-записи должны указывать на **публичный IP именно этого сервера** (см. шаг 6).
> PostgreSQL (5434) и gunicorn (8000) слушают только `127.0.0.1` — наружу не открыты.
> Хосту нужен только Docker; Python 3.14 на сервере не используется (образы несут свой Python).

---

## 1. База сервера

```bash
sudo apt-get update && sudo apt-get -y upgrade
sudo timedatectl set-timezone Asia/Bishkek      # по желанию

# Файрвол: пока только SSH. Порты 80/443 откроем в шаге 3 — после установки nginx
# (профиль ufw «Nginx Full» поставляется пакетом nginx и до установки не существует).
sudo ufw allow OpenSSH
sudo ufw --force enable
```

## 2. Docker + Docker Compose

Официальный установщик (надёжен на свежих релизах Ubuntu, ставит и compose-плагин):

```bash
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker "$USER"        # затем перелогиньтесь (или: newgrp docker)
docker --version && docker compose version
```

<details><summary>Альтернатива — официальный apt-репозиторий Docker</summary>

```bash
sudo apt-get install -y ca-certificates curl
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] \
  https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
  | sudo tee /etc/apt/sources.list.d/docker.list >/dev/null
sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
```
Если для кодового имени вашего релиза репозиторий ещё пуст — используйте установщик `get.docker.com` выше.
</details>

> ⚠️ Если при `docker compose ... build/up` появляется `unauthenticated pull rate limit` —
> это лимит Docker Hub на IP. Лечится `docker login` (бесплатный аккаунт) либо зеркалом:
> `echo '{ "registry-mirrors": ["https://mirror.gcr.io"] }' | sudo tee /etc/docker/daemon.json && sudo systemctl restart docker`.

## 3. nginx (+ certbot — только для пути 7Б)

```bash
sudo apt-get install -y nginx certbot python3-certbot-nginx

# Профиль «Nginx Full» теперь существует — открываем 80/443:
sudo ufw allow 'Nginx Full'
sudo ufw status      # убедитесь, что 80/tcp и 443/tcp = ALLOW
```

## 4. Код и переменные окружения

```bash
sudo mkdir -p /opt/loko && sudo chown "$USER" /opt/loko
git clone git@github.com:lev1tha/loko.git /opt/loko      # ваш SSH-ключ уже на гите
cd /opt/loko/infra
cp .env.example .env
nano .env
```

Заполните в `infra/.env` (это **секреты — файл в .gitignore, не коммитится**):

- `SECRET_KEY` — длинная случайная строка (`python3 -c "import secrets;print(secrets.token_urlsafe(64))"`);
- `POSTGRES_PASSWORD` — ваш пароль БД;
- `SEED_ADMIN_PASSWORD` / `SEED_KASSIR_PASSWORD` — пароли админа/кассира;
- остальное (`POSTGRES_DB=loko`, `POSTGRES_USER=lokobooking`, `POSTGRES_PORT=5434`, домены) уже преднастроено.

## 5. Запуск стека и сборка SPA

```bash
sudo mkdir -p /srv/www/lokobooking /srv/loko/media
sudo chown -R "$USER" /srv/www/lokobooking /srv/loko/media

cd /opt/loko/infra
docker compose up -d --build                               # db + backend (миграции, collectstatic)
docker compose --profile build run --rm --build frontend   # сборка SPA → /srv/www/lokobooking

# Первичные данные (счета, настройки) + админ/кассир с ВАШИМИ паролями из .env:
docker compose exec backend python manage.py seed

docker compose ps
curl -s http://127.0.0.1:8000/api/ -o /dev/null -w "backend: HTTP %{http_code}\n"   # 401 = жив
```

> `seed` берёт пароли из `SEED_ADMIN_PASSWORD` / `SEED_KASSIR_PASSWORD` (`.env`). Дефолтных
> `admin123/kassir123` в проде нет — если переменные пусты, пользователи создаются **без пароля**;
> задайте его командой `changepassword` (шаг 8). `SEED_ON_START` оставьте `0`.

## 6. DNS — направить домены на ЭТОТ сервер

Все три записи (`@`, `www`, `api`) — тип **A**, значение = **публичный IP этого VPS**:

```bash
curl -4 -s ifconfig.me; echo        # ← именно этот IP должен стоять в A-записях
```

> 🛑 Частая ошибка: A-запись указывает на старый/чужой сервер → Cloudflare (или браузер) стучатся
> не туда и отдают `526`/timeout, хотя локально всё работает. **Сверьте** значение записей в DNS
> с выводом команды выше.

Дальше — два пути TLS:
- записи **Proxied** (оранжевое облако Cloudflare) → раздел **7А** (Origin Certificate, рекомендуется);
- записи **DNS only** (серое облако / без Cloudflare) → раздел **7Б** (certbot).

## 7А. nginx + TLS за Cloudflare (Origin Certificate)

Записи в Cloudflare — **Proxied** (оранжевые); **SSL/TLS → Overview → Full (strict)**.

**1) Origin-сертификат.** Cloudflare → **SSL/TLS → Origin Server → Create Certificate**
(хосты `lokobooking.com` и `*.lokobooking.com`, RSA) → сохраните на сервер:

```bash
sudo mkdir -p /etc/ssl/cloudflare
sudo nano /etc/ssl/cloudflare/lokobooking.pem   # ← Origin Certificate (-----BEGIN CERTIFICATE-----)
sudo nano /etc/ssl/cloudflare/lokobooking.key   # ← Private Key (-----BEGIN PRIVATE KEY-----, строки BEGIN/END обязательны)
sudo chmod 600 /etc/ssl/cloudflare/lokobooking.key
```

**2) vhost API** — `sudo nano /etc/nginx/sites-available/api.lokobooking.com`:

```nginx
server { listen 80; listen [::]:80; server_name api.lokobooking.com; return 301 https://$host$request_uri; }
server {
    listen 443 ssl; listen [::]:443 ssl; http2 on;
    server_name api.lokobooking.com;
    ssl_certificate     /etc/ssl/cloudflare/lokobooking.pem;
    ssl_certificate_key /etc/ssl/cloudflare/lokobooking.key;
    client_max_body_size 25m;
    location /media/ { alias /srv/loko/media/; access_log off; expires 7d; }
    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Host              $host;
        proxy_set_header X-Real-IP         $remote_addr;
        proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 65s;
    }
}
```

**3) vhost SPA** — `sudo nano /etc/nginx/sites-available/lokobooking.com`:

```nginx
server { listen 80; listen [::]:80; server_name lokobooking.com www.lokobooking.com; return 301 https://$host$request_uri; }
server {
    listen 443 ssl; listen [::]:443 ssl; http2 on;
    server_name lokobooking.com www.lokobooking.com;
    ssl_certificate     /etc/ssl/cloudflare/lokobooking.pem;
    ssl_certificate_key /etc/ssl/cloudflare/lokobooking.key;
    root /srv/www/lokobooking; index index.html;
    location /assets/ { expires 1y; add_header Cache-Control "public, immutable"; }
    location / { try_files $uri $uri/ /index.html; }
}
```

**4) Включить vhosts (ОБЯЗАТЕЛЬНО — иначе грузится только дефолтный сайт и :443 не поднимется) и перезапустить:**

```bash
sudo ln -sf /etc/nginx/sites-available/api.lokobooking.com /etc/nginx/sites-enabled/
sudo ln -sf /etc/nginx/sites-available/lokobooking.com     /etc/nginx/sites-enabled/
sudo rm -f  /etc/nginx/sites-enabled/default
sudo nginx -t && sudo systemctl restart nginx
sudo ss -tlnp | grep ':443'        # ПРОВЕРКА: nginx должен слушать :443 (иначе vhosts не подключены)
```

Origin-сертификат живёт 15 лет — certbot и продление не нужны.

## 7Б. nginx + TLS без Cloudflare (certbot, DNS only)

Если записи **DNS only** (серые) и резолвятся прямо на сервер. vhosts — как в 7А, но в каждом
оставьте **только блок `listen 80`** с `location`-ами (без `listen 443`/`ssl_*`), затем:

```bash
sudo ln -sf /etc/nginx/sites-available/api.lokobooking.com /etc/nginx/sites-enabled/
sudo ln -sf /etc/nginx/sites-available/lokobooking.com     /etc/nginx/sites-enabled/
sudo rm -f  /etc/nginx/sites-enabled/default
sudo nginx -t && sudo systemctl reload nginx

sudo certbot --nginx -d lokobooking.com -d www.lokobooking.com -d api.lokobooking.com \
  --redirect --agree-tos -m you@example.com --no-eff-email
```
certbot сам добавит `listen 443 ssl` + редирект 80→443. Продление: `sudo certbot renew --dry-run`.

## 8. Проверка и первичная настройка

```bash
# Локально + через интернет (для 7А — после Full strict)
curl -ki https://127.0.0.1/api/ -H 'Host: api.lokobooking.com' -o /dev/null -w "origin: %{http_code}\n"  # 401
curl -s  -o /dev/null -w "public api: %{http_code}\n" https://api.lokobooking.com/api/                    # 401
curl -s  -o /dev/null -w "public spa: %{http_code}\n" https://lokobooking.com/                            # 200

# Логин (пароль — тот, что вы задали в SEED_ADMIN_PASSWORD)
curl -s -X POST https://api.lokobooking.com/api/auth/login/ \
  -H 'Content-Type: application/json' -d '{"username":"admin","password":"ВАШ_ПАРОЛЬ"}'

# Задать/сменить пароль admin или завести ещё суперпользователя:
cd /opt/loko/infra
docker compose exec backend python manage.py changepassword admin
docker compose exec backend python manage.py createsuperuser
```

Откройте `https://lokobooking.com` — вход в систему.

> Документация API (`/api/schema/`, `/api/docs/`, `/api/redoc/`) **не публична** — отдаётся только
> с валидным токеном (`SERVE_PERMISSIONS=IsAuthenticated`). Для Swagger в браузере либо ограничьте
> эти пути по IP в nginx (`location /api/docs/ { allow <ваш-IP>; deny all; … }`), либо смотрите офлайн:
> `docker compose exec backend python manage.py spectacular`.

### Диагностика (если что-то не открывается)

| Симптом | Где смотреть |
|---|---|
| `526` через Cloudflare | A-запись на чужой IP (шаг 6); режим не `Full (strict)`; origin-серт не CF Origin |
| `521/522` | origin недоступен: backend не поднят, `443` не открыт (ufw/фаервол провайдера) |
| локально `:443` нет в `ss` | vhosts не включены в `sites-enabled` (шаг 7А.4) |
| `public spa: 404/403` | SPA не собрана: `ls /srv/www/lokobooking/` → пусто → пересоберите frontend (шаг 5) |

---

## Обновление (redeploy)

```bash
cd /opt/loko && git pull
cd infra
docker compose up -d --build backend                       # пересборка + миграции (entrypoint)
docker compose --profile build run --rm --build frontend   # пересборка SPA
```

## Эксплуатация

```bash
docker compose logs -f backend                  # логи
docker compose ps                               # статус
docker compose exec backend python manage.py migrate        # миграции вручную
docker compose exec db pg_dump -U lokobooking -p 5434 loko > ~/loko_$(date +%F).sql   # бэкап БД
docker compose down                             # стоп (данные в томе pgdata сохраняются)
```

## Безопасность (чек-лист)

- [ ] A-записи указывают на реальный IP сервера (`curl -4 ifconfig.me`).
- [ ] Заданы `SEED_ADMIN_PASSWORD`/`SEED_KASSIR_PASSWORD` (или пароли через `changepassword`); `SEED_ON_START=0`.
- [ ] `SECRET_KEY` — длинный случайный; `DEBUG=False`; `ALLOWED_HOSTS` без `*`.
- [ ] ufw: открыты только SSH и `Nginx Full`; БД (5434) и backend (8000) — на `127.0.0.1`.
- [ ] `infra/.env` не в гите (он в `.gitignore`).
- [ ] TLS: за Cloudflare — Origin Cert + **Full (strict)**; без Cloudflare — `certbot renew --dry-run` проходит.
- [ ] (опц.) origin закрыт от обхода Cloudflare: вход 80/443 только с [IP Cloudflare](https://www.cloudflare.com/ips/) или Authenticated Origin Pulls.
```
