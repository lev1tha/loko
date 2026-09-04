#!/bin/zsh
# Демо-сценарий PHP-фасада kargoosh.kg → Loko (локально). Использование: kargo_demo.sh <TOKEN>
T=$1; B=http://127.0.0.1:8009/api/kargo
j() { curl -s -H "X-Kargo-Token: $T" -H "Content-Type: application/json" "$@"; echo; }
echo "1) регистрация клиента (kargoosh.kg → форма регистрации)"
j -X POST $B/auth/register/ -d '{"name":"Демо Клиент","phone":"+996 700 55 44 33","email":"demo-client@example.com","password":"demo123","region":"Ош"}'
echo "2) вход (e-mail или телефон + пароль)"
j -X POST $B/auth/login/ -H "X-Kargo-Client-IP: 10.0.0.5" -d '{"login":"0700554433","password":"demo123"}'
CODE=$(curl -s -H "X-Kargo-Token: $T" -H "Content-Type: application/json" -X POST $B/auth/login/ -d '{"login":"demo-client@example.com","password":"demo123"}' | python3 -c 'import sys,json;d=json.load(sys.stdin);print(d["client"]["code"])')
CID=$(curl -s -H "X-Kargo-Token: $T" -H "Content-Type: application/json" -X POST $B/auth/login/ -d '{"login":"demo-client@example.com","password":"demo123"}' | python3 -c 'import sys,json;d=json.load(sys.stdin);print(d["client"]["id"])')
echo "   код клиента: $CODE (id $CID)"
echo "3) админка Kargo: отгрузка из Китая (Excel-импорт) — 2 трека"
j -X POST $B/orders/shipments/ -d "{\"region\":\"Ош\",\"shipment_date\":\"2026-09-01\",\"items\":[{\"tracking_number\":\"DEMO-TRK-1\",\"client_code\":\"$CODE\"},{\"tracking_number\":\"DEMO-TRK-2\",\"client_code\":\"$CODE\"}]}"
echo "4) трекинг на главной kargoosh.kg"
j "$B/track/?number=DEMO-TRK-1"
echo "5) склад: поступило, вес 3.2 кг (сумма = вес × цена/кг)"
j -X POST $B/orders/arrive/ -d "{\"client_code\":\"$CODE\",\"tracking_numbers\":[\"DEMO-TRK-1\",\"DEMO-TRK-2\"],\"weight_kg\":\"3.2\",\"region\":\"Ош\"}"
echo "6) кабинет клиента: заказы «на складе»"
j "$B/clients/$CID/orders/?status=2"
echo "7) выдача: оплата на счёт (id первого сомового счёта Express)"
ACC=$(curl -s -H "X-Kargo-Token: $T" $B/branches/ >/dev/null; cd backend && ./venv/bin/python manage.py shell -c "from finance.models import Account; print(Account.objects.filter(module='EXPRESS',currency='KGS',is_active=True).order_by('id').first().id)" 2>/dev/null | tail -1)
j -X POST $B/orders/pickup/ -d "{\"client_code\":\"$CODE\",\"arrival_date\":\"$(date +%F)\",\"account\":$ACC}"
echo "8) трекинг после выдачи"
j "$B/track/?number=DEMO-TRK-1"
