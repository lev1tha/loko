# Деплой Loko ERP — VPS (Ubuntu) · Docker + host nginx + certbot

Прод-стек: **Docker** (Django 6.0 + gunicorn, PostgreSQL) за **host-nginx** (TLS от **certbot**).
Фронтенд-SPA собирается одноразовым контейнером и отдаётся nginx'ом со статики.

```
                              ┌──────── VPS (Ubuntu) ─────────────────────────┐
  https://lokobooking.com     │  nginx (host)                                 │
  https://www.lokobooking.com │   ├─ @ / www  → /srv/www/lokobooking (SPA)    │
        │  443 (TLS, certbot)  │   └─ api      → 127.0.0.1:8000 ─┐            │
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

> Все три A-записи должны указывать на **публичный IP сервера**.
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

## 3. nginx + certbot

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

## 6. nginx: sites-available / sites-enabled

Создаём два конфига **на сервере** (HTTP; TLS добавит certbot на шаге 7).

**API** — `sudo nano /etc/nginx/sites-available/api.lokobooking.com`:

```nginx
server {
    listen 80;
    listen [::]:80;
    server_name api.lokobooking.com;

    client_max_body_size 25m;

    # Загрузки (Django media). Не нужно, если медиа в Cloudflare R2.
    location /media/ {
        alias /srv/loko/media/;
        access_log off;
        expires 7d;
    }

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Host              $host;
        proxy_set_header X-Real-IP         $remote_addr;
        proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;   # → Django SECURE_PROXY_SSL_HEADER
        proxy_read_timeout 65s;
    }
}
```

**SPA (сайт)** — `sudo nano /etc/nginx/sites-available/lokobooking.com`:

```nginx
server {
    listen 80;
    listen [::]:80;
    server_name lokobooking.com www.lokobooking.com;

    root /srv/www/lokobooking;
    index index.html;

    location /assets/ {
        expires 1y;
        add_header Cache-Control "public, immutable";
    }

    # SPA-фолбэк: неизвестные пути отдают index.html (React Router).
    location / {
        try_files $uri $uri/ /index.html;
    }
}
```

Включаем, проверяем, перезагружаем:

```bash
sudo ln -s /etc/nginx/sites-available/api.lokobooking.com  /etc/nginx/sites-enabled/
sudo ln -s /etc/nginx/sites-available/lokobooking.com      /etc/nginx/sites-enabled/
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t && sudo systemctl reload nginx
```

## 7. TLS (Let's Encrypt) для всех трёх доменов

A-записи `@`, `www`, `api` должны уже резолвиться на сервер, порты 80/443 открыты (шаг 3).
Проверка: `dig +short lokobooking.com www.lokobooking.com api.lokobooking.com` → IP сервера.

```bash
sudo certbot --nginx \
  -d lokobooking.com -d www.lokobooking.com -d api.lokobooking.com \
  --redirect --agree-tos -m you@example.com --no-eff-email
```

certbot впишет `listen 443 ssl`, пути к сертификатам и редирект 80→443 в оба конфига.
Автопродление уже включено системным таймером — проверка: `sudo certbot renew --dry-run`.

## 8. Проверка и первичная настройка

```bash
# TLS + проксирование API
curl -s -o /dev/null -w "api: HTTP %{http_code}\n" https://api.lokobooking.com/api/   # 401 — ок
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

- [ ] Заданы `SEED_ADMIN_PASSWORD`/`SEED_KASSIR_PASSWORD` (или пароли через `changepassword`); `SEED_ON_START=0`.
- [ ] `SECRET_KEY` — длинный случайный; `DEBUG=False`; `ALLOWED_HOSTS` без `*`.
- [ ] ufw: открыты только SSH и `Nginx Full`; БД (5434) и backend (8000) — на `127.0.0.1`.
- [ ] `infra/.env` не в гите (он в `.gitignore`).
- [ ] `certbot renew --dry-run` проходит.
