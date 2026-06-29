// Чистые помощники для таблицы продаж Express (выделены для юнит-тестов).

// Значение строки продажи для сортировки по выбранной колонке.
export function sortValue(r, key) {
  if (key === 'date') return r.date || ''
  if (key === 'client_code') return (r.client_code || '').toString()
  if (key === 'account') return r.account_name || ''
  if (key === 'weight') return Number(r.weight_kg ?? r.est_weight_kg ?? 0)
  return Number(r[key] || 0) // price_som, paid_som, receivable_som, margin_som
}

// Сравнение двух строк по ключу и направлению (asc/desc).
export function compareRows(a, b, key, dir) {
  const va = sortValue(a, key)
  const vb = sortValue(b, key)
  const c = typeof va === 'string' ? va.localeCompare(vb, 'ru') : va - vb
  return dir === 'asc' ? c : -c
}
