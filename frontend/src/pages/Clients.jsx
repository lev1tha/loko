import { useCallback, useEffect, useState } from 'react'
import api, { errorMessage } from '../api/client'
import { som, dateRu } from '../lib/format'
import { Alert, EmptyState, Spinner } from '../components/ui'

const fmtKg = (v) => new Intl.NumberFormat('ru-RU').format(parseFloat(v) || 0)
// Бонус за вес: за каждые 20 кг — 0,5 кг бесплатно.
const freeKg = (v) => Math.floor((parseFloat(v) || 0) / 20) * 0.5

// Канонический телефон (только цифры) → читаемый вид.
function fmtPhone(d) {
  const s = String(d || '')
  if (s.length === 12) return `+${s.slice(0, 3)} ${s.slice(3, 6)} ${s.slice(6, 9)} ${s.slice(9)}`
  return s ? `+${s}` : '—'
}

// Экран «Клиенты» (CRM, кассир/админ). Клиенты регистрируются по телефону на
// QR-странице; здесь видно имя, историю (заказов, вес, сумму) и накопленный бонус.
export default function Clients() {
  const [search, setSearch] = useState('')
  const [rows, setRows] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const load = useCallback((q) => {
    setLoading(true)
    api
      .get('/clients/', { params: q.trim() ? { search: q.trim() } : {} })
      .then((r) => setRows(r.data.results || r.data || []))
      .catch((e) => { setError(errorMessage(e)); setRows([]) })
      .finally(() => setLoading(false))
  }, [])

  // Поиск с небольшой задержкой (debounce).
  useEffect(() => {
    const t = setTimeout(() => load(search), 250)
    return () => clearTimeout(t)
  }, [load, search])

  const totalSom = rows.reduce((s, c) => s + (parseFloat(c.total_som) || 0), 0)

  return (
    <>
      {error && <Alert kind="error">{error}</Alert>}
      <div className="card">
        <div className="card-header">
          <span className="card-title">
            Клиенты{rows.length > 0 && <span className="muted"> · {rows.length}</span>}
          </span>
          <input
            className="input"
            placeholder="Поиск по имени или телефону…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            style={{ maxWidth: 260 }}
          />
        </div>

        <p className="muted" style={{ margin: '0 0 12px' }}>
          Клиенты регистрируются по телефону на QR-странице. «Всего» — только по
          оприходованным (найденным) позициям. Бонус: за каждые 20 кг — 0,5 кг бесплатно.
        </p>

        {loading ? (
          <Spinner />
        ) : !rows.length ? (
          <EmptyState>{search ? 'Никого не нашли.' : 'Клиентов пока нет — появятся после регистрации по QR.'}</EmptyState>
        ) : (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>Клиент</th>
                  <th className="num">Заказов</th>
                  <th className="num">Всего, кг</th>
                  <th className="num">Бонус</th>
                  <th className="num">Сумма</th>
                  <th>Регистрация</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((c) => {
                  const free = freeKg(c.total_kg)
                  return (
                    <tr key={c.id}>
                      <td>
                        <strong>{c.name || '— без имени —'}</strong>
                        <div className="caption muted" style={{ fontFamily: 'ui-monospace, Menlo, monospace' }}>
                          {fmtPhone(c.phone)}
                        </div>
                      </td>
                      <td className="num">{c.orders_count}</td>
                      <td className="num">{fmtKg(c.total_kg)} кг</td>
                      <td className="num">{free > 0 ? <span className="part-hint">+{fmtKg(free)} кг</span> : '—'}</td>
                      <td className="num"><strong>{som(c.total_som)}</strong></td>
                      <td className="muted">{dateRu(c.created_at)}</td>
                    </tr>
                  )
                })}
              </tbody>
              <tfoot>
                <tr>
                  <td colSpan={4} className="num"><strong>Итого выручка по клиентам</strong></td>
                  <td className="num"><strong>{som(totalSom)}</strong></td>
                  <td></td>
                </tr>
              </tfoot>
            </table>
          </div>
        )}
      </div>
    </>
  )
}
