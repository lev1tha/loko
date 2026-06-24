#!/bin/sh
set -e

echo "▸ Applying migrations…"
python manage.py migrate --noinput

echo "▸ Collecting static files…"
python manage.py collectstatic --noinput

# First-run bootstrap: create admin/kassir + default accounts.
# Set SEED_ON_START=0 in infra/.env after the first successful start.
if [ "${SEED_ON_START:-0}" = "1" ]; then
  echo "▸ Seeding initial data…"
  python manage.py seed
fi

exec "$@"
