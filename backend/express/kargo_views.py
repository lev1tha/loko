"""API для PHP-фасада kargoosh.kg (``/api/kargo/…``).

Loko — источник правды по клиентам, заказам и деньгам; сайт kargoosh.kg
остаётся «лицом» для клиентов (SEO, привычный кабинет) и ходит сюда
сервер-к-серверу. Доступ: заголовок ``X-Kargo-Token`` = ``KARGO_API_TOKEN``
(fail closed — без токена в настройках всё закрыто). Конечный пользователь
здесь не аутентифицируется JWT-ом: сессию ведёт PHP, а ограничение попыток
входа считается по ``X-Kargo-Client-IP``, который PHP пробрасывает.

Статусы заказа (как ``orders.i_status`` в Kargo): 1 — в пути (есть отгрузка),
2 — на складе (есть прибытие, не оплачен), 3 — отдан (оплачен).
"""
import hmac
from decimal import Decimal

from django.conf import settings
from django.db import transaction
from django.db.models import F, Sum
from django.utils import timezone
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import serializers, status
from rest_framework.decorators import api_view, authentication_classes, permission_classes, throttle_classes
from rest_framework.exceptions import NotFound, PermissionDenied
from rest_framework.permissions import BasePermission
from rest_framework.response import Response

from finance.models import Account, Branch
from loko.throttling import KargoLoginThrottle, KargoServiceThrottle

from . import kargo
from .kargo_serializers import (
    ArriveSerializer,
    ChangePasswordSerializer,
    ClientOutSerializer,
    ClientUpdateSerializer,
    KargoOrderSerializer,
    LoginSerializer,
    PickupSerializer,
    RecoverySerializer,
    RegisterSerializer,
    ResetPasswordSerializer,
    ShipmentsSerializer,
    STATUS_CODE,
    parse_status,
)
from .models import Client, DeliveryStatus, KargoSync, Sale

ZERO = Decimal("0.00")
TAG = ["kargo"]


class HasKargoToken(BasePermission):
    """Сервисный токен PHP-бэкенда. Сравнение constant-time; пустой токен в
    настройках закрывает всё."""

    message = "Нет доступа: неверный или отсутствующий X-Kargo-Token."

    def has_permission(self, request, view):
        expected = settings.KARGO_API_TOKEN or ""
        given = request.META.get("HTTP_X_KARGO_TOKEN", "")
        return bool(expected) and bool(given) and hmac.compare_digest(given, expected)


def kargo_view(methods, *, login_throttle=False, **schema):
    """Декоратор: схема + api_view + без JWT + токен + троттлинг."""

    def deco(fn):
        throttles = [KargoServiceThrottle] + ([KargoLoginThrottle] if login_throttle else [])
        fn = throttle_classes(throttles)(fn)
        fn = permission_classes([HasKargoToken])(fn)
        fn = authentication_classes([])(fn)
        fn = api_view(methods)(fn)
        return extend_schema(tags=TAG, **schema)(fn)

    return deco


def _client_ip(request) -> str:
    return (request.META.get("HTTP_X_KARGO_CLIENT_IP") or "").strip()[:45]


def _get_client(pk) -> Client:
    try:
        return Client.objects.select_related("branch").get(pk=pk)
    except Client.DoesNotExist:
        raise NotFound("Клиент не найден.")


def _default_account():
    """Счёт для заказа без оплаты (нужен из-за NOT NULL): первый активный
    сомовый счёт Express, предпочтительно перенесённая касса Kargo."""
    acc = (
        Account.objects.filter(module="EXPRESS", currency="KGS", is_active=True)
        .order_by(F("legacy_kargo_card_id").asc(nulls_last=True), "id").first()
    )
    if acc is None:
        raise serializers.ValidationError({"account": "Нет активного сомового счёта Express."})
    return acc


def _canon_code(code: str, branch) -> str:
    """Код клиента в верхнем регистре; префикс региона добавляем, если его нет
    (как ``import`` в PHP-админке)."""
    code = (code or "").strip().upper()
    if branch is not None and code:
        prefix, _ = kargo.code_prefix(branch.legacy_kargo_region)
        if "-" not in code:
            code = prefix + code
    return code


def _phone_taken(phone_raw, exclude_id=None):
    c = kargo.find_client_by_phone(phone_raw)
    return c is not None and c.id != exclude_id


# ---------------------------------------------------------------------------
# Auth клиента
# ---------------------------------------------------------------------------

@kargo_view(["POST"], login_throttle=True, request=LoginSerializer, responses=OpenApiTypes.OBJECT)
def login(request):
    """Вход клиента: e-mail или телефон + пароль (схема пароля PHP поддержана).
    Успех → профиль; PHP заводит свою сессию."""
    ser = LoginSerializer(data=request.data)
    ser.is_valid(raise_exception=True)
    client = kargo.find_client_by_login(ser.validated_data["login"])
    if client is None or not client.check_password(ser.validated_data["password"]):
        return Response({"ok": False, "detail": "Неверный логин или пароль."}, status=status.HTTP_401_UNAUTHORIZED)
    if not client.is_enabled:
        return Response({"ok": False, "detail": "Учётная запись отключена."}, status=status.HTTP_403_FORBIDDEN)
    client.access_date = timezone.now()
    client.access_ip = _client_ip(request)
    client.save(update_fields=["access_date", "access_ip", "updated_at"])
    return Response({"ok": True, "client": ClientOutSerializer(client).data})


@kargo_view(["POST"], login_throttle=True, request=RegisterSerializer, responses=OpenApiTypes.OBJECT)
def register(request):
    """Регистрация клиента (форма kargoosh.kg): код генерируется по префиксу
    региона филиала. Телефон, уже сданный по QR без e-mail/пароля, «дозаполняется»."""
    ser = RegisterSerializer(data=request.data)
    ser.is_valid(raise_exception=True)
    d = ser.validated_data
    email = d["email"].lower()
    if Client.objects.filter(email__iexact=email).exists():
        raise serializers.ValidationError({"email": "Этот e-mail уже зарегистрирован."})
    existing = kargo.find_client_by_phone(d["phone"])
    if existing is not None and (existing.password_hash or existing.email):
        raise serializers.ValidationError({"phone": "Этот телефон уже зарегистрирован."})
    with transaction.atomic():
        client = existing or Client(phone=kargo.canonical_phone(d["phone"]))
        client.name = d["name"].strip()
        client.last_name = d["last_name"].strip()
        client.email = email
        client.branch = d["branch"]
        client.set_password(d["password"])
        if not client.code:
            client.code = kargo.generate_client_code(d["branch"])
        client.reg_date = client.reg_date or timezone.now()
        client.access_date = timezone.now()
        client.access_ip = _client_ip(request)
        client.save()
    return Response({"ok": True, "client": ClientOutSerializer(client).data}, status=status.HTTP_201_CREATED)


@kargo_view(["POST"], login_throttle=True, request=ChangePasswordSerializer, responses=OpenApiTypes.OBJECT)
def change_password(request):
    """Смена пароля в кабинете (нужен текущий пароль)."""
    ser = ChangePasswordSerializer(data=request.data)
    ser.is_valid(raise_exception=True)
    d = ser.validated_data
    client = _get_client(d["client_id"])
    if not client.check_password(d["current_password"]):
        raise serializers.ValidationError({"current_password": "Текущий пароль неверный."})
    client.set_password(d["new_password"])
    client.save(update_fields=["password_hash", "updated_at"])
    return Response({"ok": True})


@kargo_view(["POST"], login_throttle=True, request=RecoverySerializer, responses=OpenApiTypes.OBJECT)
def recovery(request):
    """Запрос восстановления: логин + код клиента → одноразовый ``pass_code`` на
    15 минут. Доставку (ссылка на странице/e-mail) делает PHP, как раньше."""
    ser = RecoverySerializer(data=request.data)
    ser.is_valid(raise_exception=True)
    d = ser.validated_data
    client = kargo.find_client_by_login(d["login"])
    if client is None or (client.code or "").upper() != d["code"].strip().upper():
        raise serializers.ValidationError({"code": "Клиент не найден или код не совпадает."})
    client.pass_code = kargo.make_pass_code()
    client.pass_date = timezone.now() + timezone.timedelta(minutes=15)
    client.save(update_fields=["pass_code", "pass_date", "updated_at"])
    return Response({"ok": True, "client_id": client.id, "pass_code": client.pass_code, "expires_at": client.pass_date})


@kargo_view(["POST"], login_throttle=True, request=ResetPasswordSerializer, responses=OpenApiTypes.OBJECT)
def reset_password(request):
    """Новый пароль по действующему ``pass_code``."""
    ser = ResetPasswordSerializer(data=request.data)
    ser.is_valid(raise_exception=True)
    d = ser.validated_data
    client = Client.objects.filter(pass_code=d["pass_code"]).exclude(pass_code="").first()
    if client is None or client.pass_date is None or client.pass_date < timezone.now():
        raise serializers.ValidationError({"pass_code": "Ссылка недействительна или устарела."})
    client.set_password(d["password"])
    client.pass_code = ""
    client.pass_date = None
    client.save(update_fields=["password_hash", "pass_code", "pass_date", "updated_at"])
    return Response({"ok": True, "client": ClientOutSerializer(client).data})


# ---------------------------------------------------------------------------
# Кабинет клиента
# ---------------------------------------------------------------------------

@kargo_view(["GET", "PATCH"], request=ClientUpdateSerializer, responses=ClientOutSerializer)
def client_detail(request, pk):
    """Профиль клиента; PATCH — правка контактов/кода с проверкой уникальности
    (update_post в PHP)."""
    client = _get_client(pk)
    if request.method == "GET":
        return Response(ClientOutSerializer(client).data)
    ser = ClientUpdateSerializer(data=request.data)
    ser.is_valid(raise_exception=True)
    d = ser.validated_data
    errors = {}
    if "phone" in d:
        if len(Client.normalize_phone(d["phone"])) < 9:
            errors["phone"] = "Укажите корректный номер телефона."
        elif _phone_taken(d["phone"], exclude_id=client.id):
            errors["phone"] = "Этот телефон уже занят."
        else:
            client.phone = kargo.canonical_phone(d["phone"])
    if "email" in d:
        email = d["email"].lower()
        if Client.objects.filter(email__iexact=email).exclude(pk=client.pk).exists():
            errors["email"] = "Этот e-mail уже занят."
        else:
            client.email = email
    if "code" in d:
        code = d["code"].strip().upper()
        if Client.objects.filter(code=code).exclude(pk=client.pk).exists():
            errors["code"] = "Этот код уже занят."
        else:
            client.code = code
    if errors:
        raise serializers.ValidationError(errors)
    for f in ("name", "last_name", "tg_id"):
        if f in d:
            setattr(client, f, d[f].strip())
    client.save()
    return Response(ClientOutSerializer(client).data)


def _orders_payload(qs):
    rows = KargoOrderSerializer(qs, many=True).data
    totals = {}
    for st in DeliveryStatus.values:
        agg = qs.filter(delivery_status=st).aggregate(n=Sum(1), kg=Sum("weight_kg"), som=Sum("price_som"))
        totals[st] = {
            "code": STATUS_CODE[st], "count": agg["n"] or 0,
            "weight_kg": str(Decimal(agg["kg"] or 0).quantize(Decimal("0.001"))),
            "price_som": str(Decimal(agg["som"] or 0).quantize(Decimal("0.01"))),
        }
    return {"orders": rows, "totals": totals}


@kargo_view(
    ["GET"],
    parameters=[OpenApiParameter("status", OpenApiTypes.STR, description="1|2|3 или TRANSIT|ARRIVED|DELIVERED"),
                OpenApiParameter("limit", OpenApiTypes.INT, description="Макс. строк (по умолчанию 100, как в PHP)")],
    responses=OpenApiTypes.OBJECT,
)
def client_orders(request, pk):
    """Заказы клиента по его коду (кабинет: «в пути / на складе / отданные») +
    итоги по статусам (кг, сом)."""
    client = _get_client(pk)
    if not client.code:
        return Response({"orders": [], "totals": {}})
    qs = Sale.objects.filter(client_code=client.code, delivery_status__isnull=False).select_related("branch")
    st = parse_status(request.query_params.get("status"))
    if st:
        qs = qs.filter(delivery_status=st)
    payload = _orders_payload(qs.order_by("-id"))
    try:
        limit = max(1, min(int(request.query_params.get("limit", 100)), 1000))
    except ValueError:
        limit = 100
    payload["orders"] = payload["orders"][:limit]
    return Response(payload)


@kargo_view(
    ["GET"],
    parameters=[OpenApiParameter("number", OpenApiTypes.STR, description="Трек-номер", required=True)],
    responses=OpenApiTypes.OBJECT,
)
def track(request):
    """Публичный трекинг по номеру (форма на главной kargoosh.kg): статус + дата."""
    number = (request.query_params.get("number") or "").strip()
    if not number:
        return Response({"found": False})
    s = Sale.objects.filter(tracking_number=number, delivery_status__isnull=False).first()
    if s is None:
        return Response({"found": False})
    date = {DeliveryStatus.TRANSIT: s.shipment_date, DeliveryStatus.ARRIVED: s.arrival_date,
            DeliveryStatus.DELIVERED: s.payment_date}[s.delivery_status]
    return Response({
        "found": True, "tracking_number": s.tracking_number, "status": s.delivery_status,
        "status_code": STATUS_CODE[s.delivery_status], "status_label": s.get_delivery_status_display(),
        "date": date,
    })


@kargo_view(["GET"], responses=OpenApiTypes.OBJECT)
def branches(request):
    """Филиалы для формы регистрации («Выберите карго»): регион Kargo, префикс
    кода и цена за кг."""
    out = []
    for b in Branch.objects.filter(is_active=True).order_by("name"):
        prefix, _ = kargo.code_prefix(b.legacy_kargo_region)
        out.append({
            "id": b.id, "name": b.name, "region": b.legacy_kargo_region, "code_prefix": prefix,
            "price_per_kg_som": str(kargo.unit_price_som(None, b)),
        })
    return Response(out)


# ---------------------------------------------------------------------------
# Операции по заказам (PHP-админка: отгрузка / прибытие / выдача)
# ---------------------------------------------------------------------------

@kargo_view(["POST"], request=ShipmentsSerializer, responses=OpenApiTypes.OBJECT)
def shipments(request):
    """Пакет «отправлено из Китая» (импорт Excel): создаёт заказы «в пути»;
    существующий трек — обновляет код клиента и дату отгрузки (как ON DUPLICATE
    KEY UPDATE в PHP)."""
    ser = ShipmentsSerializer(data=request.data)
    ser.is_valid(raise_exception=True)
    d = ser.validated_data
    branch = d["branch"]
    default_date = d.get("shipment_date") or timezone.localdate()
    account = _default_account()
    created = updated = 0
    with transaction.atomic():
        for it in d["items"]:
            track_no = it["tracking_number"].strip()
            code = _canon_code(it["client_code"], branch)
            sdate = it.get("shipment_date") or default_date
            if not track_no or not code:
                continue
            s = Sale.objects.filter(tracking_number=track_no).first()
            if s is not None:
                s.client_code = code
                s.shipment_date = sdate
                if s.delivery_status == DeliveryStatus.TRANSIT:
                    s.date = sdate
                s.save()
                updated += 1
                continue
            Sale.objects.create(
                client_code=code, amount_mode=Sale.AmountMode.DIRECT, weight_kg=None, places=1,
                account=account, branch=branch, price_som=ZERO, paid_som=ZERO,
                date=sdate, shipment_date=sdate, tracking_number=track_no,
                delivery_status=DeliveryStatus.TRANSIT,
            )
            created += 1
    return Response({"ok": True, "created": created, "updated": updated}, status=status.HTTP_201_CREATED)


@kargo_view(["POST"], request=ArriveSerializer, responses=OpenApiTypes.OBJECT)
def arrive(request):
    """«Поступил на склад» (add_post в PHP): по каждому треку — заказ клиента
    переводится «на склад» (или создаётся, если отгрузки не было). Вес и сумма
    (вес × цена за кг) пишутся на ПЕРВЫЙ трек, остальные — 0, как в Kargo."""
    ser = ArriveSerializer(data=request.data)
    ser.is_valid(raise_exception=True)
    d = ser.validated_data
    branch = d["branch"]
    code = _canon_code(d["client_code"], branch)
    client = Client.objects.filter(code=code).first()
    unit = kargo.unit_price_som(client, branch)
    account = d.get("account") or _default_account()
    today = timezone.localdate()
    updated, created, conflicts = 0, 0, []
    with transaction.atomic():
        for i, track_no in enumerate(d["tracking_numbers"]):
            w = Decimal(d["weight_kg"]) if i == 0 else Decimal("0")
            price = (w * unit).quantize(Decimal("0.01"))
            s = Sale.objects.filter(tracking_number=track_no).first()
            if s is not None and s.client_code != code:
                conflicts.append({"tracking_number": track_no, "client_code": s.client_code})
                continue
            if s is not None:
                if s.delivery_status == DeliveryStatus.DELIVERED:
                    conflicts.append({"tracking_number": track_no, "client_code": code, "detail": "уже отдан"})
                    continue
                s.weight_kg, s.price_som, s.paid_som = w, price, ZERO
                s.arrival_date, s.date = today, today
                s.delivery_status = DeliveryStatus.ARRIVED
                if branch is not None:
                    s.branch = branch
                s.save()
                updated += 1
            else:
                Sale.objects.create(
                    client_code=code, amount_mode=Sale.AmountMode.DIRECT, weight_kg=w, places=1,
                    account=account, branch=branch, price_som=price, paid_som=ZERO,
                    date=today, arrival_date=today, tracking_number=track_no,
                    delivery_status=DeliveryStatus.ARRIVED,
                )
                created += 1
    return Response({
        "ok": True, "updated": updated, "created": created, "conflicts": conflicts,
        "unit_price_som": str(unit), "client_found": client is not None,
    })


@kargo_view(["POST"], request=PickupSerializer, responses=OpenApiTypes.OBJECT)
def pickup(request):
    """«Отдан» (markAsPickup в PHP): все заказы кода «на складе» за дату прибытия
    → оплачены на выбранный счёт (приток ОДДС), статус «отдан»."""
    ser = PickupSerializer(data=request.data)
    ser.is_valid(raise_exception=True)
    d = ser.validated_data
    code = d["client_code"].strip().upper()
    pdate = d.get("pickup_date") or timezone.localdate()
    qs = Sale.objects.filter(client_code=code, delivery_status=DeliveryStatus.ARRIVED, arrival_date=d["arrival_date"])
    total, n = ZERO, 0
    with transaction.atomic():
        for s in qs.select_for_update():
            s.paid_som = s.price_som
            s.payment_date = pdate
            s.account = d["account"]
            s.delivery_status = DeliveryStatus.DELIVERED
            s.save()
            total += s.price_som
            n += 1
    if n == 0:
        raise serializers.ValidationError({"client_code": "Нет заказов на складе за эту дату."})
    return Response({"ok": True, "count": n, "sum_som": str(total), "pickup_date": pdate})


@kargo_view(["GET"], responses=OpenApiTypes.OBJECT)
def sync_status(request):
    """Последняя синхронизация Kargo → Loko (мост на время переходного периода)."""
    last = KargoSync.objects.first()
    ok = KargoSync.last_successful()
    return Response({
        "last": None if last is None else {
            "mode": last.mode, "started_at": last.started_at, "finished_at": last.finished_at,
            "ok": last.ok, "dry_run": last.dry_run, "stats": last.stats, "error": last.error,
        },
        "last_successful_at": ok.finished_at if ok else None,
    })
