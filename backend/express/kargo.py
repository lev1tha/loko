"""Доменные помощники интеграции с Kargo Osh (PHP-сайт kargoosh.kg).

Loko — единственный источник правды; PHP-фасад ходит сюда через
``/api/kargo/…`` (см. ``kargo_views``). Здесь — то, что должно совпадать с
логикой PHP один-в-один, чтобы клиенты ничего не заметили:

* проверка пароля по схеме PHP ``md5(md5(strrev(pw)) . "test_ort")``
  (``inc/functions.inc.php::don_get_md5_password``) с прозрачным апгрейдом
  до хеша Django после первого успешного входа;
* префикс кода клиента по региону (``inc/helpers/hUsers.php::getCodePrefix``);
* цена за кг: скидка клиента → филиал → Настройки (``getShippingPrice``);
* нормализация телефона: в Kargo хранится 9 цифр без «996».
"""
import hashlib
import hmac
import secrets
from decimal import Decimal, InvalidOperation

from django.contrib.auth.hashers import check_password as dj_check_password, make_password

from finance.models import AppSettings

LEGACY_SALT = "test_ort"

# Регион Kargo → префикс кода клиента и число цифр (как в PHP).
CODE_PREFIXES = {
    "Кара-суу": ("OS-", 4),
    "Бишкек": ("GAA-", 5),
    "Ош-район": ("TRL-", 5),
}
DEFAULT_PREFIX = ("AL-", 5)


def legacy_md5(raw_password: str) -> str:
    """Хеш пароля в схеме Kargo (PHP): md5(md5(strrev(pw)) . salt)."""
    inner = hashlib.md5(raw_password[::-1].encode("utf-8")).hexdigest()
    return hashlib.md5((inner + LEGACY_SALT).encode("utf-8")).hexdigest()


def is_legacy_hash(stored: str) -> bool:
    return len(stored) == 32 and all(c in "0123456789abcdef" for c in stored.lower())


def check_client_password(client, raw_password) -> bool:
    """True, если пароль верный. Legacy-MD5 при успехе апгрейдится до Django-хеша
    (сохраняется сразу, только это поле) — старые хеши постепенно исчезают."""
    stored = client.password_hash or ""
    raw_password = raw_password or ""
    if not stored or not raw_password:
        return False
    if is_legacy_hash(stored):
        if not hmac.compare_digest(stored.lower(), legacy_md5(raw_password)):
            return False
        client.password_hash = make_password(raw_password)
        client.save(update_fields=["password_hash", "updated_at"])
        return True
    return dj_check_password(raw_password, stored)


def code_prefix(region: str):
    """(префикс, число цифр) для региона Kargo (пустой/неизвестный → AL-, 5)."""
    return CODE_PREFIXES.get((region or "").strip(), DEFAULT_PREFIX)


def generate_client_code(branch):
    """Свободный код клиента в формате Kargo: <префикс региона><случайные цифры>."""
    from .models import Client

    prefix, digits = code_prefix(getattr(branch, "legacy_kargo_region", ""))
    lo, hi = 10 ** (digits - 1), 10 ** digits - 1
    for _ in range(200):
        code = f"{prefix}{secrets.randbelow(hi - lo + 1) + lo}"
        if not Client.objects.filter(code=code).exists():
            return code
    raise RuntimeError("Не удалось подобрать свободный код клиента")


def phone_candidates(raw) -> list[str]:
    """Варианты канонического телефона для поиска клиента.

    Kargo хранит 9 цифр («700123456»), Loko-QR — как ввёл клиент (часто с 996).
    Ищем по всем формам, чтобы «+996 700 123 456», «0700123456» и «700123456»
    находили одного и того же клиента.
    """
    from .models import Client

    digits = Client.normalize_phone(raw)
    if not digits:
        return []
    out = [digits]
    if digits.startswith("996") and len(digits) == 12:
        out.append(digits[3:])
    elif digits.startswith("0") and len(digits) == 10:
        out.append(digits[1:])
    if len(digits) == 9:
        out.append("996" + digits)
    return list(dict.fromkeys(out))


def canonical_phone(raw) -> str:
    """Телефон для хранения — в формате Kargo (9 цифр без «996»/«0»), если это
    киргизский номер; иначе просто цифры."""
    cands = phone_candidates(raw)
    if not cands:
        return ""
    nine = [c for c in cands if len(c) == 9]
    return nine[0] if nine else cands[0]


def find_client_by_phone(raw):
    from .models import Client

    cands = phone_candidates(raw)
    if not cands:
        return None
    by_phone = {c.phone: c for c in Client.objects.filter(phone__in=cands)}
    for p in cands:
        if p in by_phone:
            return by_phone[p]
    return None


def find_client_by_login(login: str):
    """Клиент по e-mail (если похоже на e-mail) или по телефону — как login_post в PHP."""
    from .models import Client

    login = (login or "").strip()
    if not login:
        return None
    if "@" in login:
        return Client.objects.filter(email__iexact=login).first()
    return find_client_by_phone(login)


def _decimal(v):
    try:
        d = Decimal(str(v).strip().replace(",", "."))
    except (InvalidOperation, ValueError):
        return None
    return d if d > 0 else None


def unit_price_som(client, branch) -> Decimal:
    """Цена за 1 кг для Kargo-заказа: скидочная цена клиента (``discount``, как в
    PHP ``s_discount_price``) → индивидуальная ``ClientPrice`` → цена филиала →
    Настройки (цена_$ × курс)."""
    from .models import ClientPrice

    q = Decimal("0.01")
    if client is not None:
        d = _decimal(client.discount)
        if d is not None:
            return d.quantize(q)
        if client.code:
            cp = ClientPrice.objects.filter(client_code=client.code).values_list("price_per_kg_som", flat=True).first()
            if cp:
                return Decimal(cp).quantize(q)
    if branch is not None and branch.price_per_kg_som:
        return Decimal(branch.price_per_kg_som).quantize(q)
    cfg = AppSettings.load()
    return (Decimal(cfg.price_per_kg_usd) * Decimal(cfg.usd_rate_som)).quantize(q)


def make_pass_code() -> str:
    """Код восстановления пароля (в PHP — md5 от случайной строки)."""
    return secrets.token_hex(16)
