import { useCallback, useEffect, useState } from 'react'
import api, { errorMessage } from '../api/client'
import { som } from '../lib/format'
import { Alert, Badge, Spinner } from '../components/ui'

// Текущий месяц в формате YYYY-MM.
function thisMonth() {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`
}

// Экран «Бонусы сотрудников за месяц» (админ/менеджер). Оборот и стаж считаются
// из данных; оклад/дисциплина/проверка/звёзды/отзывы — правятся вручную. Итог по
// тарифам. Звёзды пока ручные — подтянутся, когда подключим клиентскую оценку.
export default function Bonuses() {
  const [period, setPeriod] = useState(thisMonth())
  const [rows, setRows] = useState([])
  const [loading, setLoading] = useState(true)
  const [savingId, setSavingId] = useState(null)
  const [error, setError] = useState('')

  const load = useCallback((p) => {
    setLoading(true)
    api.get('/reports/bonuses/', { params: { period: p } })
      .then((res) => setRows(res.data.rows || []))
      .catch((err) => { setError(errorMessage(err)); setRows([]) })
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => { load(period) }, [load, period])

  // Локальная правка поля (для отзывчивости), сохранение — на blur/change.
  function edit(id, field, value) {
    setRows((rs) => rs.map((r) => (r.id === id ? { ...r, [field]: value } : r)))
  }
  async function save(id, field, value) {
    setSavingId(id)
    setError('')
    try {
      await api.patch(`/bonuses/${id}/`, { [field]: value === '' ? null : value })
      load(period) // пересчёт итога на сервере
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setSavingId(null)
    }
  }

  const grandTotal = rows.reduce((s, r) => s + Number(r.total || 0), 0)

  return (
    <>
      {error && <Alert kind="error">{error}</Alert>}
      <div className="card">
        <div className="card-header">
          <span className="card-title">Бонусы сотрудников за месяц</span>
          <div className="row gap-sm" style={{ alignItems: 'center' }}>
            <input
              className="input"
              type="month"
              value={period}
              max={thisMonth()}
              onChange={(e) => setPeriod(e.target.value || thisMonth())}
              style={{ maxWidth: 170 }}
            />
          </div>
        </div>

        <p className="muted" style={{ margin: '0 0 12px' }}>
          Оборот и стаж считаются из данных · оклад, дисциплина, проверка, звёзды и отзывы — правятся вручную.
          Звёзды подтянутся автоматически, когда подключим оценку клиентами.
        </p>

        {loading ? (
          <Spinner />
        ) : !rows.length ? (
          <p className="muted" style={{ margin: 0 }}>Нет сотрудников для расчёта.</p>
        ) : (
          <div className="table-wrap">
            <table className="table bonus-table">
              <thead>
                <tr>
                  <th>Сотрудник</th>
                  <th>Оклад</th>
                  <th>Дисц.<br /><span className="th-sub">+2000</span></th>
                  <th>Проверка<br /><span className="th-sub">1–5</span></th>
                  <th>Оборот<br /><span className="th-sub">кг · сом</span></th>
                  <th>Звёзды<br /><span className="th-sub">1–5</span></th>
                  <th>Стаж<br /><span className="th-sub">мес · сом</span></th>
                  <th>Отзывы<br /><span className="th-sub">×200</span></th>
                  <th className="num">Итого</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => {
                  const busy = savingId === r.id
                  return (
                    <tr key={r.id} className={busy ? 'row-busy' : ''}>
                      <td>
                        <strong>{r.employee_name}</strong>
                        <div className="caption muted">
                          {r.role_display}{r.branch_name ? ` · ${shortBranch(r.branch_name)}` : ''}
                        </div>
                      </td>
                      <td>
                        <input
                          className="input input-cell" type="number" min="0" step="500"
                          value={r.oklad ?? ''}
                          onChange={(e) => edit(r.id, 'oklad', e.target.value)}
                          onBlur={(e) => save(r.id, 'oklad', e.target.value)}
                        />
                      </td>
                      <td className="cell-center">
                        <input
                          type="checkbox" checked={!!r.discipline_ok}
                          onChange={(e) => save(r.id, 'discipline_ok', e.target.checked)}
                        />
                      </td>
                      <td>
                        <input
                          className="input input-cell" type="number" min="0" max="5" step="0.5"
                          value={r.inspection_score ?? ''} placeholder="—"
                          onChange={(e) => edit(r.id, 'inspection_score', e.target.value)}
                          onBlur={(e) => save(r.id, 'inspection_score', e.target.value)}
                        />
                        <PartHint value={r.parts?.inspection} />
                      </td>
                      <td>
                        <span className="cell-auto">{fmtKg(r.turnover_kg)} кг</span>
                        <PartHint value={r.parts?.turnover} />
                      </td>
                      <td>
                        <input
                          className="input input-cell" type="number" min="0" max="5" step="0.5"
                          value={r.stars ?? ''} placeholder="—"
                          onChange={(e) => edit(r.id, 'stars', e.target.value)}
                          onBlur={(e) => save(r.id, 'stars', e.target.value)}
                        />
                        <PartHint value={r.parts?.stars} />
                      </td>
                      <td>
                        <span className="cell-auto">{r.tenure_months} мес</span>
                        <PartHint value={r.parts?.tenure} />
                      </td>
                      <td>
                        <input
                          className="input input-cell" type="number" min="0" step="1"
                          value={r.reviews_count ?? 0}
                          onChange={(e) => edit(r.id, 'reviews_count', e.target.value)}
                          onBlur={(e) => save(r.id, 'reviews_count', e.target.value)}
                        />
                        <PartHint value={r.parts?.reviews} />
                      </td>
                      <td className="num"><strong>{som(r.total)}</strong></td>
                    </tr>
                  )
                })}
              </tbody>
              <tfoot>
                <tr>
                  <td colSpan={8} className="num"><strong>Фонд за месяц</strong></td>
                  <td className="num"><strong>{som(grandTotal)}</strong></td>
                </tr>
              </tfoot>
            </table>
          </div>
        )}
      </div>
    </>
  )
}

function PartHint({ value }) {
  const n = Number(value || 0)
  if (!n) return null
  return <div className="part-hint">+{som(n)}</div>
}

function fmtKg(v) {
  return new Intl.NumberFormat('ru-RU').format(Number(v || 0))
}
function shortBranch(name) {
  const tail = String(name).includes('—') ? String(name).split('—').slice(1).join('—') : name
  return tail.replace('улица,', '').replace(/\s+/g, ' ').trim()
}
