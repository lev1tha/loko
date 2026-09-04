from django.apps import AppConfig


class ExpressConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'express'

    def ready(self):
        from . import kargo_push  # noqa: F401 — регистрирует сигналы моста Loko → Kargoosh
