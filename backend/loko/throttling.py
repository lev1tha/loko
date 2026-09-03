"""Rate-limit throttles for the security-sensitive endpoints.

The app runs behind Cloudflare + host nginx with the backend bound to
127.0.0.1, so the socket peer (``REMOTE_ADDR``) is always the proxy — the same
value for every visitor. Throttling on that would lump all clients into one
bucket (one attacker could lock everyone out, and per-client limits wouldn't
work). We instead take the real client IP from the proxy-set headers.

Security note: these headers are only trustworthy because the backend is not
publicly reachable — nginx must set ``CF-Connecting-IP`` (Cloudflare already
overwrites it at its edge) and pass ``X-Forwarded-For``. If the backend is ever
exposed directly, a client could spoof them; keep it behind the proxy.
"""

from rest_framework.throttling import AnonRateThrottle, SimpleRateThrottle


def client_ip(request) -> str:
    """Real client IP: Cloudflare's header, then nginx's X-Real-IP (set to the
    true socket peer on the kargoosh.kg vhosts — not spoofable), then the first
    X-Forwarded-For hop, then the socket peer. See the module docstring for the
    trust assumptions."""
    meta = request.META
    cf = meta.get("HTTP_CF_CONNECTING_IP")
    if cf:
        return cf.strip()
    real = meta.get("HTTP_X_REAL_IP")
    if real:
        return real.strip()
    forwarded = meta.get("HTTP_X_FORWARDED_FOR")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return meta.get("REMOTE_ADDR", "")


class _ClientIPMixin:
    def get_ident(self, request):
        return client_ip(request) or super().get_ident(request)


class LoginRateThrottle(_ClientIPMixin, SimpleRateThrottle):
    """Per-client-IP cap on login attempts — slows password brute-force /
    credential stuffing. Applies to anonymous and authenticated callers alike."""

    scope = "login"

    def get_cache_key(self, request, view):
        return self.cache_format % {"scope": self.scope, "ident": self.get_ident(request)}


class PublicReadThrottle(_ClientIPMixin, AnonRateThrottle):
    """QR client read endpoints (tracking, branch list)."""

    scope = "public_read"


class PublicWriteThrottle(_ClientIPMixin, AnonRateThrottle):
    """QR client write endpoints (self-intake, rating) — creates data, tighter."""

    scope = "public_write"


class KargoServiceThrottle(_ClientIPMixin, SimpleRateThrottle):
    """Server-to-server calls from the kargoosh.kg PHP backend (token-authed).
    Generous — one upstream IP serves every visitor of the public site."""

    scope = "kargo"

    def get_cache_key(self, request, view):
        return self.cache_format % {"scope": self.scope, "ident": self.get_ident(request)}


class KargoLoginThrottle(SimpleRateThrottle):
    """Per END-USER cap on client login / password-reset attempts proxied by
    the PHP site. The PHP backend forwards the visitor's address in
    ``X-Kargo-Client-IP`` (its own IP would lump every visitor into one
    bucket); without the header we fall back to the upstream IP so the limit
    still applies."""

    scope = "kargo_login"

    def get_cache_key(self, request, view):
        ident = (request.META.get("HTTP_X_KARGO_CLIENT_IP") or "").strip() or client_ip(request)
        return self.cache_format % {"scope": self.scope, "ident": ident}
