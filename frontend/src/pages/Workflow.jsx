import { useEffect, useMemo, useState } from 'react'
import { useFetch, asList } from '../lib/hooks'
import { useAuth } from '../auth/AuthContext'
import { som, num, today, firstOfMonth, dateTimeRu } from '../lib/format'
import { Alert, Segmented, Spinner } from '../components/ui'
import '../director.css'

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
const kg1 = (v) => `${num(v, Number(v) % 1 ? 1 : 0)} кг`

// «Процесс работы» — прозрачность склада для директора (read-only): кто из
// сотрудников что сделал за период, что сейчас в работе и что осталось на
// вечерний допоиск. Обновляется автоматически.
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
    <div className="dir-page">
      <div className="dir-page-head">
        <div>
          <p className="dir-page-sub">
            Кто что обрабатывает, сколько кг и сом, что осталось на вечерний допоиск.
            {isDirector ? ' Только просмотр, ' : ' '}обновляется каждые 15 секунд.
          </p>
        </div>
        <div className="dir-controls">
          <Segmented value={period} onChange={setPeriod} options={PERIODS} />
          {period === 'custom' && (
            <>
              <input className="input" type="date" value={from} onChange={(e) => setFrom(e.target.value)} aria-label="С даты" />
              <input className="input" type="date" value={to} onChange={(e) => setTo(e.target.value)} aria-label="По дату" />
            </>
          )}
          <select className="select" value={branch} onChange={(e) => setBranch(e.target.value)} aria-label="Филиал">
            <option value="">Все филиалы</option>
            {branches.map((b) => <option key={b.id} value={b.id}>{shortBranch(b.name)}</option>)}
          </select>
        </div>
      </div>

      {req.error && <Alert kind="error">Не удалось загрузить данные. Обновите страницу.</Alert>}
      {req.loading && !d ? <Spinner full /> : t && (
        <>
          <div className="dir-stats">
            <div className="dir-stat"><span className="label">Заявок за период</span><span className="value">{t.orders_created}</span><span className="sub">{t.items_created} кодов</span></div>
            <div className="dir-stat"><span className="label">Оприходовано</span><span className="value ledger">{t.items_found}</span><span className="sub">{kg1(t.kg_found)} · {som(t.som_found)}</span></div>
            <div className="dir-stat"><span className="label">Не найдено</span><span className={`value ${t.items_not_found ? 'signal' : ''}`}>{t.items_not_found}</span><span className="sub">за период</span></div>
            <div className="dir-stat"><span className="label">В работе сейчас</span><span className="value">{t.active_orders_now}</span><span className="sub">{t.in_search_now} кодов в поиске</span></div>
            <div className="dir-stat"><span className="label">Вечерний допоиск</span><span className={`value ${t.evening_now ? 'signal' : 'ledger'}`}>{t.evening_now}</span><span className="sub">{t.evening_now ? 'ждут перепроверки' : 'пусто, отказов нет'}</span></div>
          </div>

          <div className="dir-tabs" role="tablist">
            <button className={`dir-tab ${tab === 'employees' ? 'active' : ''}`} onClick={() => setTab('employees')}>Сотрудники</button>
            <button className={`dir-tab ${tab === 'active' ? 'active' : ''}`} onClick={() => setTab('active')}>
              В работе сейчас {active.length > 0 && <span className="dir-nav-count">{active.length}</span>}
            </button>
            <button className={`dir-tab ${tab === 'evening' ? 'active' : ''}`} onClick={() => setTab('evening')}>
              Вечерний допоиск {evening.length > 0 && <span className="dir-nav-count">{evening.length}</span>}
            </button>
          </div>

          {tab === 'employees' && (
            <section className="dir-panel">
              {!employees.length ? (
                <div className="empty">За этот период сотрудники ничего не обрабатывали.</div>
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
                          <td className="num">{e.items_found ? num(e.kg_found, 1) : '—'}</td>
                          <td className="num">{e.items_found ? som(e.som_found) : '—'}</td>
                          <td className={`num ${e.items_not_found ? 'negative' : ''}`}>{e.items_not_found || '—'}</td>
                          <td className="num">{e.items_evening || '—'}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </section>
          )}

          {tab === 'active' && (
            !active.length ? (
              <section className="dir-panel"><div className="empty">Сейчас нет заявок в работе, всё оприходовано.</div></section>
            ) : (
              <div className="dir-orders">
                {active.map((o) => (
                  <section key={o.id} className="dir-panel dir-order">
                    <div className="dir-order-head">
                      <span className="id">#{o.id}</span>
                      {o.branch_name && <span>{shortBranch(o.branch_name)}</span>}
                      {o.created_by_name && <span>создал {o.created_by_name}</span>}
                      {o.assigned_to_name && <span>собирает {o.assigned_to_name}</span>}
                      <span className="when">{dateTimeRu(o.created_at)}</span>
                    </div>
                    <div className="dir-items">
                      {(o.items || []).map((it) => <ItemRow key={it.id} item={it} />)}
                    </div>
                  </section>
                ))}
                {d.active_truncated && <p className="dir-note">Показаны первые {active.length} заявок.</p>}
              </div>
            )
          )}

          {tab === 'evening' && (
            !evening.length ? (
              <section className="dir-panel"><div className="empty">Вечерний допоиск пуст, отказов нет.</div></section>
            ) : (
              <section className="dir-panel">
                <div className="dir-panel-head"><h3>Осталось на вечерний допоиск</h3><span>склад перепроверяет в конце смены</span></div>
                <div className="dir-items">
                  {evening.map((it) => <ItemRow key={it.id} item={it} showMeta />)}
                </div>
              </section>
            )
          )}
        </>
      )}
    </div>
  )
}

function ItemRow({ item, showMeta }) {
  const found = item.status === 'FOUND' || item.status === 'DELIVERED'
  return (
    <div className="dir-item">
      <div className="dir-item-main">
        <span className="dir-code">{item.client_code}</span>
        <span className={`dir-chip ${item.status.toLowerCase()}`}>{item.status_display}</span>
        {showMeta && item.branch_name && <span className="dir-chip">{shortBranch(item.branch_name)}</span>}
        {showMeta && item.created_by_name && <span className="reason">оператор {item.created_by_name}</span>}
        {item.reason && <span className="reason">{item.reason}</span>}
      </div>
      {found ? (
        <span className="fin"><small>{kg1(item.weight_kg)}</small><strong>{som(item.price_som)}</strong></span>
      ) : (
        <span className="reason">{dateTimeRu(item.updated_at)}</span>
      )}
    </div>
  )
}
