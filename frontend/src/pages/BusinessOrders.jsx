import { Fragment, useState } from 'react'
import { useFetch } from '../lib/hooks'
import { firstOfMonth, today, money, dateRu, signClass } from '../lib/format'
import { Badge, EmptyState, Field, Spinner, Stat } from '../components/ui'

const STATUS_VARIANT = {
  'Заказ закрывается': 'badge-success',
  'Аванс/депозит — не признан': 'badge-manager',
  'Есть приход, закуп не отражён': 'badge-admin',
  'Есть закуп без прихода': 'badge-danger',
}

// Свод по клиентам + раскрытие в детальные операции (даты/номера).
export default function BusinessOrders() {
  const [from, setFrom] = useState(firstOfMonth())
  const [to, setTo] = useState(today())
  const [open, setOpen] = useState(() => new Set())
  const orders = useFetch('/reports/business-orders/', { from, to })

  if (orders.loading) return <Spinner full />
  const data = orders.data || { orders: [], totals: {} }
  const t = data.totals || {}

  const toggle = (client) =>
    setOpen((prev) => {
      const next = new Set(prev)
      next.has(client) ? next.delete(client) : next.add(client)
      return next
    })

  return (
    <>
      <div className="grid">
        <Stat label="Заказов (клиентов)" value={t.count || 0} />
        <Stat label="Выручка" value={money(t.revenue)} />
        <Stat label="Себестоимость (закуп)" value={money(t.cost)} />
        <Stat label="Маржа" value={money(t.margin)} tone={signClass(t.margin)} />
      </div>

      <div className="card">
        <div className="card-header">
          <span className="card-title">Заказы Business · маржа по клиентам</span>
          <div className="toolbar">
            <Field label="С даты">
              <input className="input" type="date" value={from} onChange={(e) => setFrom(e.target.value)} />
            </Field>
            <Field label="По дату">
              <input className="input" type="date" value={to} onChange={(e) => setTo(e.target.value)} />
            </Field>
          </div>
        </div>

        {data.orders.length === 0 ? (
          <EmptyState>Заказов за период нет.</EmptyState>
        ) : (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th style={{ width: 28 }}></th>
                  <th>Клиент</th>
                  <th className="num">Выручка</th>
                  <th className="num">Аванс кл.</th>
                  <th className="num">Аванс пост.</th>
                  <th className="num">Закуп</th>
                  <th className="num">Маржа</th>
                  <th className="num">%</th>
                  <th>Статус</th>
                </tr>
              </thead>
              <tbody>
                {data.orders.map((o) => {
                  const expanded = open.has(o.client)
                  return (
                    <Fragment key={o.client}>
                      <tr onClick={() => toggle(o.client)} style={{ cursor: 'pointer' }}>
                        <td className="muted" style={{ textAlign: 'center' }}>{expanded ? '▾' : '▸'}</td>
                        <td><strong>{o.client}</strong></td>
                        <td className="num">{money(o.revenue)}</td>
                        <td className="num muted">{Number(o.advance) ? money(o.advance) : '—'}</td>
                        <td className="num muted">{Number(o.advance_supplier) ? money(o.advance_supplier) : '—'}</td>
                        <td className="num neg">{Number(o.cost) ? '−' + money(o.cost) : '—'}</td>
                        <td className={`num ${signClass(o.margin)}`}>{money(o.margin)}</td>
                        <td className="num muted">{Number(o.margin_pct)}%</td>
                        <td><Badge variant={STATUS_VARIANT[o.status] || 'badge-manager'}>{o.status}</Badge></td>
                      </tr>
                      {expanded &&
                        o.details.map((d, i) => (
                          <tr key={o.client + '-' + i} style={{ background: 'var(--surface-soft)' }}>
                            <td></td>
                            <td className="caption">{d.ref}</td>
                            <td className="caption">{dateRu(d.date)}</td>
                            <td className="caption" colSpan={2}>{d.type}</td>
                            <td className="num caption">{money(d.amount, d.currency)}</td>
                            <td className="num caption muted">{money(d.amount_kgs)}</td>
                            <td colSpan={2}></td>
                          </tr>
                        ))}
                    </Fragment>
                  )
                })}
                <tr className="pnl-level">
                  <td></td>
                  <td><strong>Итого</strong></td>
                  <td className="num"><strong>{money(t.revenue)}</strong></td>
                  <td className="num">{money(t.advance)}</td>
                  <td className="num">{money(t.advance_supplier)}</td>
                  <td className="num neg"><strong>−{money(t.cost)}</strong></td>
                  <td className={`num ${signClass(t.margin)}`}><strong>{money(t.margin)}</strong></td>
                  <td colSpan={2}></td>
                </tr>
              </tbody>
            </table>
          </div>
        )}
        <p className="caption mt-lg">
          Нажмите на строку клиента, чтобы раскрыть детали заказа (операции с датой и номером: D-… депозит,
          E-… расход). Выручка — признанные депозиты, закуп — расходы «Себестоимость». Отрицательная маржа =
          закуп без прихода (кредит/аванс).
        </p>
      </div>
    </>
  )
}
