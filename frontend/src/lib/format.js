// Formatting helpers for money / numbers / dates (ru-RU).

export const CURRENCY_SYMBOL = { KGS: 'с', CNY: '¥' }

function fmt(value, digits = 2) {
  const n = Number(value || 0)
  return n.toLocaleString('ru-RU', {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  })
}

// Money in a given currency (default сом).
export function money(value, currency = 'KGS') {
  const sym = CURRENCY_SYMBOL[currency] || CURRENCY_SYMBOL.KGS
  return `${fmt(value)} ${sym}`
}

// Backwards-compatible сом formatter.
export function som(value) {
  return money(value, 'KGS')
}

export function num(value, digits = 2) {
  return fmt(value, digits)
}

export function kg(value) {
  // Вес показываем с 2 знаками после запятой (0,00 кг).
  return fmt(value, 2) + ' кг'
}

export function dateRu(value) {
  if (!value) return '—'
  const d = new Date(value)
  if (Number.isNaN(d.getTime())) return value
  return d.toLocaleDateString('ru-RU', { day: '2-digit', month: '2-digit', year: 'numeric' })
}

// Local YYYY-MM-DD (avoids the UTC shift of toISOString in +/- timezones).
function localISO(d) {
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${y}-${m}-${day}`
}

export function today() {
  return localISO(new Date())
}

export function firstOfMonth() {
  const d = new Date()
  return localISO(new Date(d.getFullYear(), d.getMonth(), 1))
}

// sign-aware css class for amounts
export function signClass(value) {
  const n = Number(value || 0)
  if (n > 0) return 'pos'
  if (n < 0) return 'neg'
  return ''
}
