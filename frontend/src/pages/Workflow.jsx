import { useEffect, useMemo, useState } from 'react'
import { useFetch, asList } from '../lib/hooks'
import { useAuth } from '../auth/AuthContext'
import { som, kg, num, today, firstOfMonth, dateTimeRu } from '../lib/format'
import { Alert, EmptyState, Segmented, Spinner, Stat } from '../components/ui'

const POLL_MS = 15000

const PERIODS = [
  { value: 'today', label: 'Сегодня' },
  { value: 'month', label: 'Месяц' },
  { value: 'custom', label: 'Период' },
]

function shortBranch(name) {
  if (!name) return ''
  const tail = String(name).includes('—') ? String(name).split('—').slice(1).join('—') : name
  return tail.replace('улица,', '').replace(/\s+/g, ' ').trim()
}

// «Процесс работы» — полная прозрачность склада для директора (read-only):
// кто из сотрудников что сделал за период, что сейчас в работе и что осталось
// на вечерний допоиск. Обновляется автоматически.
export default function Workflow() {
  const { isDirector } = useAuth()
  const [period, setPeriod] = useState('today')
  const [from, setFrom] = useState(firstOfMonth())
  const [to, setTo] = useState(today())
  const [branch, setBranch] = useState('')
  const [tab, setTab] = useState('employees')

  const params = useMemo(() => {
    const p = {}
    if (period === 'today') { p.from = today(); p.to = today() }
    else if (period === 'month') { p.from = firstOfMonth(); p.to = today() }
    else { p.from = from; p.to = to }
    if (branch) p.branch = branch
    return p
  }, [period, from, to, branch])

  const req = useFetch('/reports/workflow/', params)
  const branches = asList(useFetch('/warehouse-stock/branches/').data)

  useEffect(() => {
    const t = setInterval(() => req.reload(), POLL_MS)
    return () => clearInterval(t)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [req.reload])

  const d = req.data
  const t = d?.totals
  const employees = d?.employees || []
  const active = d?.active_orders || []
  const evening = d?.evening || []

  return (
    <div className="wh-page">
      <div className="wh-head">
        <div>
          <h2 className="card-title">Процесс работы · склад</h2>
          <p className="muted" style={{ margin: '2px 0 0' }}>
            Кто что обрабатывает, сколько кг и сом, что осталось на вечерний допоиск · обновляется автоматически
          </p>
        </div>
        <div className="row gap-sm wh-head-actions" style={{ flexWrap: 'wrap' }}>
          <Segmented value={period} onChange={setPeriod} options={PERIODS} />
          {period === 'custom' && (
            <>
              <input className="input" type="date" value={from} onChange={(e) => setFrom(e.target.value)} />
              <input className="input" type="date" value={to} onChange={(e) => setTo(e.target.value)} />
            </>
          )}
          <select className="select" value={branch} onChange={(e) => setBranch(e.target.value)}>
            <option value="">Все филиалы</option>
            {branches.map((b) => <option key={b.id} value={b.id}>{shortBranch(b.name)}</option>)}
          </select>
        </div>
      </div>

      {req.error && <Alert kind="error">Не удалось загрузить данные.</Alert>}
      {req.loading && !d ? <Spinner full /> : t && (
        <>
          <div className="grid" style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(min(100%, 170px), 1fr))' }}>
            <Stat label="Заявок за период" value={t.orders_created} sub={`${t.items_created} кодов`} />
            <Stat label="Оприходовано" value={t.items_found} sub={`${kg(t.kg_found)} · ${som(t.som_found)}`} tone="positive" />
            <Stat label="Не найдено" value={t.items_not_found} tone={t.items_not_found ? 'negative' : ''} />
            <Stat label="Сейчас в работе" value={t.active_orders_now} sub={`${t.in_search_now} кодов в поиске`} />
            <Stat
              label="Вечерний допоиск"
              value={t.evening_now}
              sub={t.evening_now ? 'ждут перепроверки' : 'пусто — отказов нет'}
              tone={t.evening_now ? 'negative' : 'positive'}
            />
          </div>

          <div className="wh-tabs">
            <button className={`wh-tab ${tab === 'employees' ? 'active' : ''}`} onClick={() => setTab('employees')}>
              Сотрудники
            </button>
            <button className={`wh-tab ${tab === 'active' ? 'active' : ''}`} onClick={() => setTab('active')}>
              В работе сейчас
              {active.length > 0 && <span className="wh-tab-badge">{active.length}</span>}
            </button>
            <button className={`wh-tab ${tab === 'evening' ? 'active' : ''}`} onClick={() => setTab('evening')}>
              Вечерний допоиск
              {evening.length > 0 && <span className="wh-tab-badge">{evening.length}</span>}
            </button>
          </div>

          {tab === 'employees' && (
            <div className="card">
              {!employees.length ? (
                <EmptyState>За период сотрудники ничего не обрабатывали.</EmptyState>
              ) : (
                <div className="table-wrap">
                  <table className="table">
                    <thead>
                      <tr>
                        <th>Сотрудник</th><th>Роль</th><th>Филиал</th>
                        <th className="num">Заявок</th><th className="num">Кодов</th>
                        <th className="num">Оприходовал</th><th className="num">Кг</th><th className="num">Сом</th>
                        <th className="num">Не найдено</th><th className="num">В вечерний</th>
                      </tr>
                    </thead>
                    <tbody>
                      {employees.map((e) => (
                        <tr key={e.id}>
                          <td><strong>{e.name}</strong></td>
                          <td className="muted">{e.role_display}</td>
                          <td className="muted">{shortBranch(e.branch_name) || '—'}</td>
                          <td className="num">{e.orders_created || '—'}</td>
                          <td className="num">{e.items_created || '—'}</td>
                          <td className="num">{e.items_found || '—'}</td>
                          <td className="num">{e.items_found ? num(e.kg_found, 3) : '—'}</td>
                          <td className="num">{e.items_found ? som(e.som_found) : '—'}</td>
                          <td className={`num ${e.items_not_found ? 'negative' : ''}`}>{e.items_not_found || '—'}</td>
                          <td className="num">{e.items_evening || '—'}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          )}

          {tab === 'active' && (
            !active.length ? (
              <div className="wh-empty-box">Сейчас нет заявок в работе — всё оприходовано.</div>
            ) : (
              <div className="wh-orders">
                {active.map((o) => (
                  <div key={o.id} className="card wh-order">
                    <div className="wh-order-head">
                      <span className="wh-order-id">#{o.id}</span>
                      {o.branch_name && <span className="wh-item-branch">{shortBranch(o.branch_name)}</span>}
                      {o.created_by_name && <span className="muted">🧑 {o.created_by_name}</span>}
                      {o.assigned_to_name && <span className="muted">📦 {o.assigned_to_name}</span>}
                      <span className="muted" style={{ marginLeft: 'auto' }}>{dateTimeRu(o.created_at)}</span>
                    </div>
                    <div className="wh-items">
                      {(o.items || []).map((it) => <ItemRow key={it.id} item={it} />)}
                    </div>
                  </div>
                ))}
                {d.active_truncated && <p className="muted">Показаны первые {active.length} заявок.</p>}
              </div>
            )
          )}

          {tab === 'evening' && (
            !evening.length ? (
              <div className="wh-empty-box">Вечерний допоиск пуст — отказов нет.</div>
            ) : (
              <div className="card wh-order">
                <div className="wh-order-head">
                  <strong>Осталось на вечерний допоиск</strong>
                  <span className="muted">коды, от которых отказались днём — склад перепроверяет в конце смены</span>
                </div>
                <div className="wh-items">
                  {evening.map((it) => <ItemRow key={it.id} item={it} showMeta />)}
                </div>
              </div>
            )
          )}
          {isDirector && <p className="caption muted">Только просмотр.</p>}
        </>
      )}
    </div>
  )
}

function ItemRow({ item, showMeta }) {
  const found = item.status === 'FOUND' || item.status === 'DELIVERED'
  return (
    <div className={`wh-item wh-row-${item.status.toLowerCase()}`}>
      <div className="wh-item-main">
        <span className="wh-code">{item.client_code}</span>
        <span className={`wh-status wh-status-${item.status.toLowerCase()}`}>{item.status_display}</span>
        {showMeta && item.branch_name && <span className="wh-item-branch">{shortBranch(item.branch_name)}</span>}
        {showMeta && item.created_by_name && <span className="muted">🧑 {item.created_by_name}</span>}
        {item.reason && <span className="wh-item-reason">💬 {item.reason}</span>}
      </div>
      {found ? (
        <div className="wh-item-fin">
          {item.weight_kg && <span className="muted">{kg(item.weight_kg)}</span>}
          <strong>{som(item.price_som)}</strong>
        </div>
      ) : (
        <span className="muted">{dateTimeRu(item.updated_at)}</span>
      )}
    </div>
  )
}
