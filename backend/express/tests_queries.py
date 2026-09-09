"""Число запросов к базе не должно расти вместе с числом позиций.

Доска склада и экран сотрудника опрашивают бэкенд по таймеру и открыты весь
рабочий день, а прод крутится на одном ядре. N+1 на позициях превращал один
опрос в сотни запросов: очередь занимала ядро, и в ней застревал даже вход
(хеш пароля — самый дорогой по процессору запрос приложения).
"""
from django.contrib.auth import get_user_model
from django.db import connection
from django.test.utils import CaptureQueriesContext
from rest_framework.test import APITestCase

from finance.models import Branch
from .models import WarehouseItem, WarehouseOrder

User = get_user_model()


class QueryCountTests(APITestCase):
    def setUp(self):
        self.branch = Branch.objects.create(name="Филиал", is_default=True)
        self.op = User.objects.create_user(
            "op_q", password="pass1234", role=User.Role.OPERATOR, branch=self.branch
        )
        self.wh = User.objects.create_user(
            "wh_q", password="pass1234", role=User.Role.WAREHOUSE, branch=self.branch
        )
        self.order = WarehouseOrder.objects.create(
            branch=self.branch, created_by=self.op, client_codes=[]
        )
        self._add_items(2, "S")

    def _add_items(self, count, prefix):
        """Позиции «найдено» — с найдено-кем и принято-кем: именно эти две связи
        сериализатор дёргал по одной на каждую строку."""
        for i in range(count):
            WarehouseItem.objects.create(
                order=self.order,
                client_code=f"{prefix}{i}",
                status=WarehouseItem.Status.LOCATED,
                found_by=self.wh,
                received_by=self.wh,
            )

    def _count(self, user, url):
        self.client.force_authenticate(user)
        with CaptureQueriesContext(connection) as ctx:
            response = self.client.get(url)
        self.assertEqual(response.status_code, 200, response.data)
        return len(ctx.captured_queries)

    def test_warehouse_board_query_count_is_flat(self):
        url = "/api/warehouse-orders/?active_items=1"
        small = self._count(self.wh, url)
        self._add_items(20, "B")
        big = self._count(self.wh, url)
        self.assertEqual(big, small, f"доска склада: {small} → {big} запросов на +20 позиций")

    def test_operator_items_query_count_is_flat(self):
        url = "/api/warehouse-items/mine/"
        small = self._count(self.op, url)
        self._add_items(20, "B")
        big = self._count(self.op, url)
        self.assertEqual(big, small, f"«Мои продажи»: {small} → {big} запросов на +20 позиций")
        self.assertLess(big, 10, f"«Мои продажи»: {big} запросов на один опрос — многовато")

    def test_evening_list_query_count_is_flat(self):
        self.order.items.update(status=WarehouseItem.Status.NOT_FOUND)
        url = "/api/warehouse-items/?status=NOT_FOUND,EVENING"
        small = self._count(self.wh, url)
        self._add_items(20, "B")
        self.order.items.update(status=WarehouseItem.Status.NOT_FOUND)
        big = self._count(self.wh, url)
        self.assertEqual(big, small, f"вечерний допоиск: {small} → {big} запросов на +20 позиций")
