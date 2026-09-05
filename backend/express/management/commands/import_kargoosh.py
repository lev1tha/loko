"""Импорт/синхронизация данных Kargo Osh (MySQL) → Loko ERP.

Источник правды после интеграции — Loko. Команда переносит оперативные данные
Kargo (регионы→филиалы, кассы→счета, клиенты, заказы) в модели Loko с
СОХРАНЕНИЕМ исторических значений и идемпотентностью по ``legacy_kargo_*``.
Финансовый журнал (`transactions`) — отдельным проходом (см. TODO ниже).

Режимы:
    python manage.py import_kargoosh --dry-run          # полный прогон со сверкой, без записи
    python manage.py import_kargoosh                    # ПОЛНЫЙ импорт: legacy-строки удаляются и создаются заново
    python manage.py import_kargoosh --incremental      # МОСТ (cron): upsert новых/изменённых, ничего не удаляет
    python manage.py import_kargoosh --incremental --since 2026-09-01   # окно вручную
    python manage.py import_kargoosh --rescan           # upsert ВСЕХ заказов/клиентов (ночная сверка), без удаления

Инкремент: клиенты и кассы — все (дёшево, ~10k строк; изменения без
timestamp'ов в источнике); заказы — новые (``pk_i_id`` > max перенесённого)
плюс те, у кого ``dt_shipment/dt_arrival/dt_pickup`` ≥ ``since``. Нижняя
граница = старт последней успешной синхронизации минус 2 суток (перекрытие —
правки в PHP-админке не имеют своей даты). Правки «задним числом» ловит
``--rescan``. Каждый запуск пишется в ``express.KargoSync`` (виден в
``GET /api/kargo/sync/``).

Кассы → счета: ``initial_balance`` = баланс кассы − оплаты перенесённых заказов
этого счёта (баланс кассы уже включает эти оплаты, а Loko считает их притоком
ОДДС — иначе двойной счёт). Итог: остаток счёта в Loko = балансу кассы Kargo.

Пароли: хеш из Kargo (MD5) переносится как есть; если в Loko хеш уже
обновлён до формата Django (клиент входил через API) — не трогаем.

Источник настраивается через env (для прод — реальная БД Kargo):
    KARGO_DB_HOST (localhost) KARGO_DB_PORT (3306) KARGO_DB_USER (root)
    KARGO_DB_PASSWORD ('')    KARGO_DB_NAME (kargoosh_tmp)

Дисциплина «без потери данных»: считаем те же количества и суммы, что и в
источнике, и печатаем сверку; расхождения — сигнал не переключаться.
"""
import os
import traceback
from datetime import date as _date, datetime, timedelta
from decimal import Decimal

import pymysql
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Count, Sum
from django.utils import timezone

from django.db.models import Q

from express.kargo import is_legacy_hash
from express.kargo_expected import sync_expected
from express.models import Client, DeliveryStatus, KargoSync, Sale, WarehouseItem
from finance.models import Account, Branch

# Строки, которыми владеет Loko: отправленные мостом либо оприходованные складом Loko
# ожидаемые посылки. Импорт их не перезаписывает и не удаляет.
_LOKO_OWNED_Q = Q(kargo_pushed_at__isnull=False) | Q(warehouse_item__status__in=list(WarehouseItem.FINANCIAL))

ZERO = Decimal("0.00")
_FALLBACK_DATE = _date(2000, 1, 1)
OVERLAP = timedelta(days=2)
STATUS = {1: DeliveryStatus.TRANSIT, 2: DeliveryStatus.ARRIVED, 3: DeliveryStatus.DELIVERED}
SALE_FIELDS = (
    "client_code", "weight_kg", "places", "account", "branch", "price_som", "paid_som",
    "margin_som", "date", "payment_date", "shipment_date", "arrival_date", "delivery_status",
    "tracking_number",
)
CLIENT_FIELDS = (
    "name", "last_name", "email", "code", "password_hash", "pass_code", "pass_date", "tg_id",
    "discount", "is_enabled", "reg_date", "access_date", "access_ip", "branch",
)


def _dt(v):
    """Наивную дату/время из MySQL делаем aware (USE_TZ=True) — не искажаем и без варнингов."""
    if v is None:
        return None
    return timezone.make_aware(v, timezone.get_current_timezone()) if timezone.is_naive(v) else v


class _Rollback(Exception):
    """Служебное исключение — откат транзакции в режиме --dry-run."""


def _src_conn():
    from django.conf import settings
    return pymysql.connect(
        host=settings.KARGO_DB_HOST or os.environ.get("KARGO_DB_HOST", "localhost"),
        port=settings.KARGO_DB_PORT,
        user=settings.KARGO_DB_USER,
        password=settings.KARGO_DB_PASSWORD,
        database=settings.KARGO_DB_NAME,
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
    )


def _d(v):
    return Decimal(str(v)) if v is not None else ZERO


class Command(BaseCommand):
    help = "Импорт/синхронизация Kargo Osh (MySQL) → Loko ERP (регионы, кассы, клиенты, заказы) со сверкой."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="Прогон со сверкой, без записи (откат).")
        parser.add_argument("--limit", type=int, default=0, help="Ограничить число заказов (для отладки).")
        parser.add_argument("--batch", type=int, default=2000, help="Размер пачки bulk_create/bulk_update.")
        parser.add_argument("--incremental", action="store_true", help="Мост: upsert новых/изменённых, без удаления.")
        parser.add_argument("--rescan", action="store_true", help="Upsert всех заказов и клиентов, без удаления.")
        parser.add_argument("--since", type=str, default="", help="Нижняя граница окна инкремента (YYYY-MM-DD).")

    # ------------------------------------------------------------------ main
    def handle(self, *args, **opts):
        self.dry = opts["dry_run"]
        self.limit = opts["limit"]
        self.batch = opts["batch"]
        if opts["incremental"] and opts["rescan"]:
            raise CommandError("--incremental и --rescan взаимоисключающие.")
        mode = KargoSync.Mode.INCREMENTAL if opts["incremental"] else (
            KargoSync.Mode.RESCAN if opts["rescan"] else KargoSync.Mode.FULL)
        since = self._resolve_since(opts["since"]) if mode == KargoSync.Mode.INCREMENTAL else None

        self.stdout.write(self.style.WARNING(
            f"Источник: {os.environ.get('KARGO_DB_NAME', 'kargoosh_tmp')} · режим: {mode}"
            f"{' с ' + since.strftime('%Y-%m-%d %H:%M') if since else ''}"
            f" · {'DRY-RUN (откат)' if self.dry else 'ЗАПИСЬ'}"
        ))
        # Журнал пишется ВНЕ транзакции импорта — чтобы упавший/dry-run прогон тоже был виден.
        log = KargoSync.objects.create(mode=mode, since=since, dry_run=self.dry)
        self.stats = {}
        self.src = _src_conn()
        try:
            base = self._baseline()
            try:
                with transaction.atomic():
                    if mode == KargoSync.Mode.FULL:
                        self._run_full()
                    else:
                        self._run_upsert(since if mode == KargoSync.Mode.INCREMENTAL else None)
                    self.stats["reconciled"] = self._reconcile(base)
                    if self.dry:
                        raise _Rollback()
            except _Rollback:
                self.stdout.write(self.style.WARNING("DRY-RUN — изменения откачены."))
            log.ok = True
        except Exception as exc:  # noqa: BLE001 — журналируем любой сбой
            log.error = f"{exc}\n{traceback.format_exc()}"[:4000]
            raise
        finally:
            self.src.close()
            log.finished_at = timezone.now()
            log.stats = self.stats
            log.save()

    def _resolve_since(self, raw):
        if raw:
            try:
                return timezone.make_aware(datetime.strptime(raw, "%Y-%m-%d"))
            except ValueError:
                raise CommandError("--since ожидает дату YYYY-MM-DD.")
        last = KargoSync.last_successful()
        if last is None:
            raise CommandError("Нет успешной синхронизации — сначала полный импорт или --since.")
        return last.started_at - OVERLAP

    # --------------------------------------------------------------- source
    def _q(self, sql, params=None):
        with self.src.cursor() as c:
            c.execute(sql, params)
            return c.fetchall()

    def _one(self, sql, params=None):
        with self.src.cursor() as c:
            c.execute(sql, params)
            return c.fetchone()

    def _baseline(self):
        self.stdout.write("→ Читаю baseline источника…")
        return {
            "users": self._one("SELECT COUNT(*) n FROM user")["n"],
            "orders": self._one("SELECT COUNT(*) n FROM orders")["n"],
            "orders_som": self._one("SELECT COALESCE(SUM(i_price),0) s FROM orders")["s"],
            "orders_kg": self._one("SELECT COALESCE(SUM(i_weight),0) s FROM orders")["s"],
            "transactions": self._one("SELECT COUNT(*) n FROM transactions")["n"],
            "cards_kargo": self._one("SELECT COALESCE(SUM(i_amount),0) s FROM cards WHERE s_for='kargo'")["s"],
        }

    # ------------------------------------------------------------ full mode
    def _run_full(self):
        self._wipe_legacy()
        regions, admin_branch = self._import_branches()
        card_acc = self._import_accounts(create_only=False)
        self._upsert_clients(regions)
        self._import_orders_full(admin_branch, card_acc)
        self._settle_accounts(card_acc.values())
        self.stats["expected"] = sync_expected(self.stdout)

    def _wipe_legacy(self):
        """Удаляем только перенесённые продажи и клиентов. Счета и филиалы Kargo
        оставляем: на них уже могут ссылаться продажи, созданные в Loko через
        /api/kargo/ (FK PROTECT), а импорт всё равно переиспользует их по
        legacy-ключам и заново сводит начальные остатки."""
        n_s = Sale.objects.filter(legacy_kargo_id__isnull=False, kargo_pushed_at__isnull=True) \
            .exclude(warehouse_item__status__in=list(WarehouseItem.FINANCIAL)).delete()[0]
        n_c = Client.objects.filter(legacy_kargo_id__isnull=False).delete()[0]
        self.stdout.write(f"  очищены прежние legacy-строки: sale={n_s} client={n_c}")

    # ---------------------------------------------------------- upsert mode
    def _run_upsert(self, since):
        # Сначала обратный мост: продажи Loko → Kargoosh (их строки потом придут
        # назад тем же импортом, но перезаписываться не будут — Loko главный).
        from express import kargo_push
        pushed = kargo_push.push_pending(conn=self.src)
        self.stats["pushed"] = pushed
        self.stdout.write(f"  Loko → Kargoosh: {pushed}")
        regions, admin_branch = self._import_branches()
        card_acc = self._import_accounts(create_only=True)
        self._upsert_clients(regions)
        self._upsert_orders(admin_branch, card_acc, since)
        # Начальный остаток фиксируем только у счетов, созданных в этом прогоне:
        # у прежних он заморожен на момент полного импорта, а новые оплаты — уже
        # настоящие притоки.
        self._settle_accounts(self.new_accounts)
        self.stats["expected"] = sync_expected(self.stdout)

    # ---------------------------------------------------------------- layers
    def _import_branches(self):
        rows = self._q("SELECT DISTINCT s_region r FROM user WHERE s_region IS NOT NULL AND s_region<>'' "
                       "UNION SELECT DISTINCT s_region FROM admin WHERE s_region IS NOT NULL AND s_region<>''")
        # Цена за кг по региону: settings.price_<регион без пробелов>; базовая — settings.price.
        prices = {r["s_name"]: r["s_value"] for r in self._q("SELECT s_name, s_value FROM settings WHERE s_name LIKE 'price%%'")}
        base_price = prices.get("price")
        regions = {}
        for row in rows:
            r = row["r"].strip()
            if not r:
                continue
            b = Branch.objects.filter(legacy_kargo_region=r).order_by("-is_active", "id").first()
            if b is None:
                b = Branch.objects.create(legacy_kargo_region=r, name=f"Kargo · {r}", is_active=True)
            rp = prices.get("price_" + r.replace(" ", ""))
            price = _d(rp) if rp not in (None, "") and rp != base_price else None
            if b.price_per_kg_som != price:
                b.price_per_kg_som = price
                b.save(update_fields=["price_per_kg_som"])
            regions[r] = b
        admin_branch = {}
        for a in self._q("SELECT pk_i_id, s_region FROM admin"):
            admin_branch[a["pk_i_id"]] = regions.get((a["s_region"] or "").strip())
        self.stdout.write(f"  филиалы из регионов: {len(regions)}")
        self.stats["branches"] = len(regions)
        return regions, admin_branch

    def _import_accounts(self, create_only):
        """Кассы → счета. В upsert-режимах только создаём недостающие: initial_balance
        (= cards.i_amount на момент полного импорта) не трогаем — оплаты после него
        уже приходят в Loko через paid_som, иначе посчитали бы дважды."""
        card_acc = {a.legacy_kargo_card_id: a for a in Account.objects.filter(legacy_kargo_card_id__isnull=False)}
        created = 0
        self.new_accounts = []
        for c in self._q("SELECT pk_i_id, s_name, s_for, i_amount, s_currency FROM cards"):
            if c["pk_i_id"] in card_acc:
                continue
            module = "EXPRESS" if c["s_for"] == "kargo" else "BUSINESS"
            acc = Account.objects.create(
                name=f"{c['s_name']} (Kargo)", module=module,
                currency=c["s_currency"], kind=Account.Kind.BANK,
                initial_balance=_d(c["i_amount"]), legacy_kargo_card_id=c["pk_i_id"],
            )
            card_acc[c["pk_i_id"]] = acc
            self.new_accounts.append(acc)
            created += 1
        self.stdout.write(f"  счета из касс: {len(card_acc)} (+{created} новых)")
        self.stats["accounts_created"] = created
        return card_acc

    def _settle_accounts(self, accounts):
        """Начальный остаток счёта = баланс кассы Kargo − оплаты по перенесённым
        заказам этого счёта. Баланс кассы (``cards.i_amount``) УЖЕ содержит эти
        оплаты, а Loko считает их притоком ОДДС по ``paid_som`` — без вычета
        деньги считались бы дважды. После этого остаток счёта в Loko = текущему
        балансу кассы в Kargo."""
        accounts = list(accounts)
        if not accounts:
            return
        amounts = {c["pk_i_id"]: _d(c["i_amount"]) for c in self._q("SELECT pk_i_id, i_amount FROM cards")}
        # Продажи, рождённые в Loko и отправленные мостом, — деньги Loko, а не касс Kargo.
        paid = dict(
            Sale.objects.filter(legacy_kargo_id__isnull=False, kargo_pushed_at__isnull=True, account__in=accounts)
            .values_list("account_id").annotate(s=Sum("paid_som")).values_list("account_id", "s")
        )
        for acc in accounts:
            acc.initial_balance = amounts.get(acc.legacy_kargo_card_id, ZERO) - (paid.get(acc.id) or ZERO)
        Account.objects.bulk_update(accounts, ["initial_balance"])
        self.stdout.write(f"  начальные остатки счетов сведены с кассами: {len(accounts)}")

    def _client_fields(self, u, regions, phone_hint):
        code = (u["s_code"] or "").strip() or None
        email = (u["s_email"] or "").strip().lower() or None
        return dict(
            name=(u["s_name"] or "").strip(), last_name=(u["s_surname"] or "").strip(),
            email=email, code=code, password_hash=(u["s_password"] or ""),
            pass_code=(u["s_pass_code"] or ""), pass_date=_dt(u["s_pass_date"]),
            tg_id=(u["s_tg_id"] or ""), discount=(u["s_discount_price"] or ""),
            is_enabled=bool(u["b_enabled"]), reg_date=_dt(u["dt_reg_date"]),
            access_date=_dt(u["dt_access_date"]), access_ip=(u["s_access_ip"] or ""),
            branch=regions.get((u["s_region"] or "").strip()),
        )

    def _upsert_clients(self, regions):
        """Клиенты: по legacy_id → по телефону (клиент уже есть в Loko, напр. с QR) → новый.
        Дубли внутри источника (телефон/код/e-mail) пропускаем, как и раньше."""
        by_legacy = {c.legacy_kargo_id: c for c in Client.objects.filter(legacy_kargo_id__isnull=False)}
        by_phone = {c.phone: c for c in Client.objects.all()}
        taken_code = set(Client.objects.exclude(code=None).values_list("code", flat=True))
        taken_email = set(Client.objects.exclude(email=None).values_list("email", flat=True))
        new, updated, dups = [], 0, 0
        for u in self._q("SELECT * FROM user ORDER BY pk_i_id"):
            phone = Client.normalize_phone(u["s_phone"]) or f"nophone-{u['s_code']}"
            fields = self._client_fields(u, regions, phone)
            obj = by_legacy.get(u["pk_i_id"]) or by_phone.get(phone)
            # Уникальные код/e-mail заняты ДРУГИМ клиентом → дубль источника, пропускаем.
            for f in ("code", "email"):
                v = fields[f]
                if v and (obj is None or getattr(obj, f) != v) and v in (taken_code if f == "code" else taken_email):
                    fields[f] = None
            if obj is None and phone in {c.phone for c in new}:
                dups += 1
                continue
            if obj is not None:
                if obj.legacy_kargo_id not in (None, u["pk_i_id"]):
                    dups += 1  # телефон уже привязан к другому legacy-клиенту
                    continue
                # Хеш Django (клиент уже входил через API) не откатываем к MD5.
                if obj.password_hash and not is_legacy_hash(obj.password_hash):
                    fields["password_hash"] = obj.password_hash
                changed = obj.legacy_kargo_id != u["pk_i_id"]
                for k, v in fields.items():
                    if getattr(obj, k) != v:
                        setattr(obj, k, v)
                        changed = True
                if changed:
                    obj.legacy_kargo_id = u["pk_i_id"]
                    obj.save()
                    updated += 1
            else:
                new.append(Client(phone=phone, legacy_kargo_id=u["pk_i_id"], **fields))
            fields["code"] and taken_code.add(fields["code"])
            fields["email"] and taken_email.add(fields["email"])
        Client.objects.bulk_create(new, batch_size=self.batch)
        self.stdout.write(f"  клиенты: +{len(new)} новых, ~{updated} обновлено, {dups} дублей пропущено")
        self.stats.update(clients_created=len(new), clients_updated=updated, clients_dups=dups)

    # ---------------------------------------------------------------- orders
    def _sale_fields(self, o, admin_branch, card_acc, txn_card, default_acc):
        price, weight = _d(o["i_price"]), _d(o["i_weight"])
        is_pickup = o["dt_pickup"] is not None
        op_date = o["dt_arrival"] or o["dt_pickup"] or o["dt_shipment"]
        return dict(
            client_code=(o["s_user_code"] or "").strip(),
            # Вес переносим ТОЧНО как в источнике (включая 0 и редкие отрицательные
            # корректировки) — иначе Σ веса не сойдётся и это была бы потеря данных.
            weight_kg=weight,
            places=o["i_quantity"] or 1,
            account=card_acc.get(txn_card.get(o["fk_i_transaction_id"])) or default_acc,
            branch=admin_branch.get(o["fk_i_admin_id"]),
            price_som=price, paid_som=(price if is_pickup else ZERO), margin_som=price,
            date=(op_date.date() if op_date else None) or _FALLBACK_DATE,
            payment_date=(o["dt_pickup"].date() if is_pickup else None),
            shipment_date=(o["dt_shipment"].date() if o["dt_shipment"] else None),
            arrival_date=(o["dt_arrival"].date() if o["dt_arrival"] else None),
            delivery_status=STATUS.get(o["i_status"], DeliveryStatus.DELIVERED),
            tracking_number=(o["s_tracking_number"] or "").strip() or None,
        )

    @staticmethod
    def _const_fields():
        return dict(
            amount_mode=Sale.AmountMode.DIRECT, price_per_kg_usd=ZERO, usd_rate_som=ZERO,
            cost_per_kg_som=ZERO, cost_som=ZERO, cost_is_manual=True,
        )

    def _default_account(self):
        return (Account.objects.filter(legacy_kargo_card_id__isnull=False, module="EXPRESS", currency="KGS")
                .order_by("legacy_kargo_card_id").first())

    def _txn_cards(self, ids):
        ids = [i for i in ids if i]
        if not ids:
            return {}
        out = {}
        for i in range(0, len(ids), 5000):
            chunk = ids[i:i + 5000]
            ph = ",".join(["%s"] * len(chunk))
            for t in self._q(f"SELECT pk_i_id, fk_i_card_id FROM transactions WHERE pk_i_id IN ({ph})", chunk):
                out[t["pk_i_id"]] = t["fk_i_card_id"]
        return out

    def _import_orders_full(self, admin_branch, card_acc):
        txn_card = {t["pk_i_id"]: t["fk_i_card_id"] for t in self._q("SELECT pk_i_id, fk_i_card_id FROM transactions")}
        default_acc = self._default_account()
        sql = "SELECT * FROM orders" + (f" LIMIT {self.limit}" if self.limit else "")
        buf, total, seen_track = [], 0, set()
        const = self._const_fields()
        loko_owned = set(Sale.objects.filter(_LOKO_OWNED_Q).values_list("legacy_kargo_id", flat=True))
        for o in self._q(sql):
            if o["pk_i_id"] in loko_owned:
                total += 1  # строка есть в обеих системах, хозяин — Loko
                continue
            f = self._sale_fields(o, admin_branch, card_acc, txn_card, default_acc)
            if f["tracking_number"] and f["tracking_number"] in seen_track:
                f["tracking_number"] = None
            f["tracking_number"] and seen_track.add(f["tracking_number"])
            buf.append(Sale(legacy_kargo_id=o["pk_i_id"], **const, **f))
            if len(buf) >= self.batch:
                Sale.objects.bulk_create(buf, batch_size=self.batch)
                total += len(buf); buf = []
                self.stdout.write(f"    …заказы: {total}", ending="\r")
        if buf:
            Sale.objects.bulk_create(buf, batch_size=self.batch)
            total += len(buf)
        self.stdout.write(f"  заказы → продажи: {total}                 ")
        self.stats["orders_created"] = total
        # TODO(след. проход): финансовый журнал `transactions` → Expense/Transfer/
        # OtherIncome. Пока не переносим — балансы касс сведены через
        # initial_balance счёта (= cards.i_amount).

    def _upsert_orders(self, admin_branch, card_acc, since):
        default_acc = self._default_account()
        if since is not None:
            max_id = Sale.objects.filter(legacy_kargo_id__isnull=False).order_by("-legacy_kargo_id") \
                .values_list("legacy_kargo_id", flat=True).first() or 0
            s = timezone.localtime(since).replace(tzinfo=None)
            rows = self._q(
                "SELECT * FROM orders WHERE pk_i_id > %s OR dt_shipment >= %s OR dt_arrival >= %s OR dt_pickup >= %s "
                "ORDER BY pk_i_id", (max_id, s, s, s),
            )
        else:
            rows = self._q("SELECT * FROM orders ORDER BY pk_i_id" + (f" LIMIT {self.limit}" if self.limit else ""))
        txn_card = self._txn_cards([o["fk_i_transaction_id"] for o in rows])
        const = self._const_fields()
        created = updated = unchanged = 0
        for i in range(0, len(rows), self.batch):
            chunk = rows[i:i + self.batch]
            ids = [o["pk_i_id"] for o in chunk]
            tracks = [t for t in ((o["s_tracking_number"] or "").strip() for o in chunk) if t]
            by_legacy = {s.legacy_kargo_id: s for s in Sale.objects.filter(legacy_kargo_id__in=ids)}
            # Строки, рождённые в Loko и отправленные мостом, — Loko главный, пропускаем.
            loko_owned = set(Sale.objects.filter(_LOKO_OWNED_Q, legacy_kargo_id__in=ids).values_list("legacy_kargo_id", flat=True))
            # Кто уже держит трек в Loko: legacy id другого заказа → в источнике дубль
            # (номера отличались пробелами; в Kargo unique, после TRIM — нет) — второму
            # трек не даём, как и при полном импорте. Держатель без legacy id — заказ,
            # заведённый через /api/kargo/ до синка: привязываем, не дублируем.
            holders = {s.tracking_number: s for s in Sale.objects.filter(tracking_number__in=tracks)}
            seen_track = set()
            new, upd = [], []
            for o in chunk:
                if o["pk_i_id"] in loko_owned:
                    unchanged += 1
                    continue
                f = self._sale_fields(o, admin_branch, card_acc, txn_card, default_acc)
                t = f["tracking_number"]
                holder = holders.get(t) if t else None
                if t and ((holder is not None and holder.legacy_kargo_id not in (None, o["pk_i_id"])) or t in seen_track):
                    f["tracking_number"] = None
                    holder = None
                elif t:
                    seen_track.add(t)
                obj = by_legacy.get(o["pk_i_id"]) or (holder if holder is not None and holder.legacy_kargo_id is None else None)
                if obj is None:
                    new.append(Sale(legacy_kargo_id=o["pk_i_id"], **const, **f))
                    continue
                changed = obj.legacy_kargo_id != o["pk_i_id"]
                obj.legacy_kargo_id = o["pk_i_id"]
                for k, v in f.items():
                    if getattr(obj, k) != v:
                        setattr(obj, k, v)
                        changed = True
                if changed:
                    upd.append(obj)
                else:
                    unchanged += 1
            Sale.objects.bulk_create(new, batch_size=self.batch)
            Sale.objects.bulk_update(upd, list(SALE_FIELDS) + ["legacy_kargo_id"], batch_size=self.batch)
            created += len(new); updated += len(upd)
            self.stdout.write(f"    …заказы: +{created} ~{updated} ={unchanged}", ending="\r")
        self.stdout.write(f"  заказы: {len(rows)} в окне → +{created} новых, ~{updated} обновлено, ={unchanged} без изменений")
        self.stats.update(orders_window=len(rows), orders_created=created, orders_updated=updated, orders_unchanged=unchanged)

    # ------------------------------------------------------------- reconcile
    def _reconcile(self, base):
        # Сверяем только перенесённое ИЗ Kargo; строки, отправленные из Loko, есть в
        # обеих системах (источник их тоже считает), поэтому добавляем их число к n.
        imported = Sale.objects.filter(legacy_kargo_id__isnull=False, kargo_pushed_at__isnull=True)
        pushed = Sale.objects.filter(kargo_pushed_at__isnull=False, legacy_kargo_id__isnull=False)
        s = imported.aggregate(n=Count("id"), som=Sum("price_som"), kg=Sum("weight_kg"))
        s["n"] = (s["n"] or 0) + pushed.count()
        s["som"] = (s["som"] or ZERO) + (pushed.aggregate(v=Sum("price_som"))["v"] or ZERO)
        s["kg"] = (s["kg"] or ZERO) + (pushed.aggregate(v=Sum("weight_kg"))["v"] or ZERO)
        cl = Client.objects.filter(legacy_kargo_id__isnull=False).count()
        kargo_accs = Account.objects.filter(legacy_kargo_card_id__isnull=False, module="EXPRESS")
        acc_kargo = (kargo_accs.aggregate(s=Sum("initial_balance"))["s"] or ZERO) + (
            imported.filter(account__in=kargo_accs).aggregate(s=Sum("paid_som"))["s"] or ZERO)
        all_ok = True

        def line(name, src, dst, money=False):
            nonlocal all_ok
            ok = (Decimal(str(src)).quantize(Decimal("0.01")) == Decimal(str(dst)).quantize(Decimal("0.01"))) if money \
                else (int(src) == int(dst))
            all_ok &= ok
            mark = self.style.SUCCESS("✓") if ok else self.style.ERROR("✗")
            self.stdout.write(f"  {mark} {name:<26} источник={src}   Loko={dst}")
            self.stats.setdefault("reconcile", {})[name] = {"src": str(src), "loko": str(dst), "ok": ok}

        self.stdout.write(self.style.MIGRATE_HEADING("── Сверка ──"))
        line("клиенты", base["users"], cl)
        line("заказы (кол-во)", base["orders"], s["n"] or 0)
        line("заказы Σ сом", base["orders_som"], s["som"] or ZERO, money=True)
        line("заказы Σ кг", base["orders_kg"], s["kg"] or ZERO, money=True)
        line("кассы карго Σ баланс", base["cards_kargo"], acc_kargo, money=True)  # = нач. остаток + оплаты
        self.stdout.write(f"  ⧗ транзакции ({base['transactions']}) — финжурнал следующим проходом")
        return all_ok
