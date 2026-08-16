import { useCallback, useEffect, useState } from 'react'
import api, { errorMessage } from '../api/client'
import { som, kg } from '../lib/format'
import { Alert } from '../components/ui'
import { LoadingTruck } from '../components/states'

// Позиции найдены и оприходованы складом (в чеке клиента, с суммой).
const FOUND = new Set(['FOUND', 'DELIVERED'])

// Страница роли «Сотрудник»: свои позиции (коды) за текущий месяц с подсветкой
// статуса склада. 🟢 найдено (вес + сумма) · 🔴 не найдено (можно убрать из чека
// крестиком → вечерний допоиск) · ⚪ в поиске · вечерний допоиск (убрано из чека).
export default function OperatorMySales() {
  const [data, setData] = useState({ count: 0, results: [] })
  const [loading, setLoading] = useState(true)
  const [busyId, setBusyId] = useState(null)
  const [error, setError] = useState('')

  const load = useCallback(() => {
    setLoading(true)
    api
      .get('/warehouse-items/mine/')
      .then((res) => setData(res.data))
      .catch((err) => {
        setError(errorMessage(err))
        setData({ count: 0, results: [] })
      })
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => {
    load()
  }, [load])

  // Крестик: убрать не найденную позицию из чека клиента → вечерний допоиск склада.
  async function dismiss(item) {
    setBusyId(item.id)
    setError('')
    try {
      await api.post(`/warehouse-items/${item.id}/to-evening/`)
      load()
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setBusyId(null)
    }
  }

  if (loading) return <LoadingTruck />

  const rows = data.results || []
  // Сумма к оплате клиентом = только найденное (оприходованное).
  const totalFound = rows
    .filter((r) => FOUND.has(r.status))
    .reduce((sum, r) => sum + (parseFloat(r.price_som) || 0), 0)

  return (
    <div className="operator-card card">
      <div className="operator-sales-head">
        <div>
          <h2 className="card-title">Мои продажи</h2>
          <p className="muted operator-sales-sub">
            За текущий месяц
            {rows.length > 0 && ` · ${rows.length} позиций · к оплате ${som(totalFound)}`}
          </p>
        </div>
      </div>

      {error && <Alert kind="error">{error}</Alert>}

      {!rows.length ? (
        <p className="muted" style={{ margin: 0 }}>В этом месяце заявок пока нет.</p>
      ) : (
        <div className="operator-sales">
          {rows.map((s) => {
            const found = FOUND.has(s.status)
            return (
              <div key={s.id} className={`operator-sales-row wh-row-${s.status.toLowerCase()}`}>
                <div className="operator-sales-main">
                  <span className="operator-sales-code">{s.client_code}</span>
                  <span className="operator-sales-meta">
                    {found
                      ? `оприходовано${s.weight_kg ? ` · ${kg(s.weight_kg)}` : ''}`
                      : s.status === 'NOT_FOUND'
                        ? `не найдено${s.reason ? ` · ${s.reason}` : ''}`
                        : s.status === 'EVENING'
                          ? 'убрано из чека · вечерний допоиск'
                          : 'в поиске'}
                  </span>
                </div>

                {found && <span className="operator-sales-sum">{som(s.price_som)}</span>}

                {s.status === 'NOT_FOUND' && (
                  <button
                    type="button"
                    className="btn btn-icon wh-remove"
                    title="Убрать из чека (в вечерний допоиск)"
                    disabled={busyId === s.id}
                    onClick={() => dismiss(s)}
                  >
                    ✕
                  </button>
                )}
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
