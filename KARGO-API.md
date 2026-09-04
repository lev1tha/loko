# API Loko для kargoosh.kg (`/api/kargo/…`)

Loko — единственный источник правды по клиентам, заказам и деньгам. Сайт
kargoosh.kg (PHP) остаётся публичным «лицом» и кабинетом клиента и ходит в
Loko сервер-к-серверу. Интерактивная документация со схемами: `/api/docs/`
(тег **kargo**, нужен вход сотрудника).

## Доступ

| Заголовок | Значение |
|---|---|
| `X-Kargo-Token` | сервисный токен = `KARGO_API_TOKEN` в `.env` Loko (обязателен на всех эндпоинтах) |
| `X-Kargo-Client-IP` | IP посетителя сайта (для лимита попыток входа: 10/мин на IP) |
| `Content-Type` | `application/json` |

Ошибки — обычный DRF: `400 {"поле": ["текст"]}`, `401`/`403` на входе, `404`
для неизвестного клиента. База: `https://api.kargoosh.kg/api/kargo/`.

## Клиент (кабинет)

| Метод и путь | Тело / параметры | Ответ |
|---|---|---|
| `POST auth/login/` | `login` (e-mail или телефон), `password` | `200 {ok, client}`; `401` неверный пароль; `403` отключён |
| `POST auth/register/` | `name, last_name?, phone, email, password, branch` (id) или `region` («Ош», «Кара-суу»…) | `201 {ok, client}` — код клиента сгенерирован по префиксу региона |
| `POST auth/change-password/` | `client_id, current_password, new_password` | `200 {ok}` |
| `POST auth/recovery/` | `login, code` (код клиента) | `200 {pass_code, expires_at}` — доставку ссылки делает PHP |
| `POST auth/reset-password/` | `pass_code, password` | `200 {ok, client}` |
| `GET clients/{id}/` | — | профиль |
| `PATCH clients/{id}/` | `name, last_name, phone, email, code, tg_id` (любые) | профиль; `400` если телефон/e-mail/код заняты |
| `GET clients/{id}/orders/?status=1\|2\|3&limit=100` | — | `{orders: [...], totals: {TRANSIT, ARRIVED, DELIVERED: {count, weight_kg, price_som}}}` |
| `GET track/?number=<трек>` | — | `{found, status_code 1/2/3, status_label, date}` |
| `GET branches/` | — | `[{id, name, region, code_prefix, price_per_kg_som}]` для формы «Выберите карго» |

Пароли клиентов из Kargo (MD5-схема PHP) принимаются как есть и при первом
входе прозрачно переводятся на хеш Django — сброс паролей не нужен.

## Заказы (PHP-админка / склад)

Статусы как в Kargo: **1** в пути (отгружен из Китая), **2** на складе
(прибыл, вес и сумма посчитаны), **3** отдан (оплачен на счёт).

| Метод и путь | Тело | Что делает |
|---|---|---|
| `POST orders/shipments/` | `branch` или `region`, `shipment_date?`, `items: [{tracking_number, client_code, shipment_date?}]` (до 2000) | Импорт Excel: создаёт заказы «в пути»; существующий трек — обновляет код/дату (как `ON DUPLICATE KEY UPDATE`) |
| `POST orders/arrive/` | `client_code, tracking_numbers[], weight_kg, branch\|region, account?` | «Поступил»: вес и сумма (вес × цена/кг) на первый трек, остальные 0; заказы без отгрузки создаются. Цена/кг: скидка клиента → индивидуальная цена → цена филиала → Настройки |
| `POST orders/pickup/` | `client_code, arrival_date, account, pickup_date?` | «Отдан»: все заказы кода «на складе» за дату прибытия → оплачены на счёт (приток ОДДС) |
| `GET sync/` | — | последняя синхронизация моста `import_kargoosh` |

`account` — id счёта Loko (`GET /api/accounts/` сотрудником); перенесённые
кассы Kargo помечены `legacy_kargo_card_id`.

## Переходный период

1. **Мост** (сейчас, в обе стороны): PHP пишет в свой MySQL, Loko забирает
   изменения cron-ом (`import_kargoosh --incremental` каждые 5 мин, `--rescan`
   ночью); всё, что сотрудники делают в Loko (оприходование, выдача, прямые
   продажи), сразу пишется в `orders` сайта (`express/kargo_push.py`), и клиент
   видит это в кабинете kargoosh.kg. Складовщик может указать трек-номер при
   оприходовании; без него строка получает трек `LOKO-<id>`.
2. **Переключение**: PHP переводится на эндпоинты выше (вход/регистрация/кабинет,
   отгрузка/прибытие/выдача), cron выключается. Собственную таблицу `orders`/`user`
   PHP больше не пишет.
3. Клиентские страницы постепенно заменяются React-страницами Loko под тем же
   доменом; публичная SEO-часть может оставаться на PHP сколько угодно.
