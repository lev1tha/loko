import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { useFetch, asList } from '../lib/hooks'
import { useAuth } from '../auth/AuthContext'
import { money, num, today, firstOfMonth } from '../lib/format'
import { Spinner } from '../components/ui'
import '../director.css'

const MONTH_SHORT = ['янв', 'фев', 'мар', 'апр', 'май', 'июн', 'июл', 'авг', 'сен', 'окт', 'ноя', 'дек']

function localISO(d) {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}
// Те же дни прошлого месяца (1-е … сегодняшнее число), чтобы сравнение было честным.
function prevMonthRange() {
  const d = new Date()
  const first = new Date(d.getFullYear(), d.getMonth() - 1, 1)
  const lastDay = new Date(d.getFullYear(), d.getMonth(), 0).getDate()
  const to = new Date(d.getFullYear(), d.getMonth() - 1, Math.min(d.getDate(), lastDay))
  return { from: localISO(first), to: localISO(to) }
}
function monthsAgoFirst(k) {
  const d = new Date()
  return localISO(new Date(d.getFullYear(), d.getMonth() - k, 1))
}
const plural = (n, one, few, many) => {
  const a = Math.abs(n) % 100, b = a % 10
  if (a > 10 && a < 20) return many
  if (b > 1 && b < 5) return few
  if (b === 1) return one
  return many
}
const kg1 = (v) => `${num(v, Number(v) % 1 ? 1 : 0)} кг`
const short = (v) => {
  const n = Number(v || 0), a = Math.abs(n)
  if (a >= 1_000_000) return `${num(n / 1_000_000, 1)} млн`
  if (a >= 1_000) return `${num(n / 1_000, 0)} тыс.`
  return num(n, 0)
}

// Изменение к прошлому месяцу: «+12% к августу» / «−5%» / «—».
function Delta({ cur, prev, label }) {
  const c = Number(cur || 0), p = Number(prev || 0)
  if (!p) return <span className="delta flat">{label}: нет данных за прошлый месяц</span>
  const pct = ((c - p) / Math.abs(p)) * 100
  const cls = pct > 0.5 ? 'up' : pct < -0.5 ? 'down' : 'flat'
  const sign = pct > 0 ? '+' : ''
  return <span className={`delta ${cls}`}>{sign}{num(pct, 0)}% {label}</span>
}

// Сводка директора: показатели с динамикой к прошлому месяцу, график по
// месяцам, что требует внимания, сотрудники и склад. Всё read-only.
export default function DirectorHome() {
  const { user } = useAuth()
  const hasWarehouse = user?.module === 'EXPRESS'
  const period = { from: firstOfMonth(), to: today() }
  const pnl = useFetch('/reports/pnl/', period)
  const pnlPrev = useFetch('/reports/pnl/', prevMonthRange())
  const cash = useFetch('/reports/cashflow/', period)
  const monthly = useFetch('/reports/monthly/', { from: monthsAgoFirst(5), to: today(), report: 'pnl' })
  const wf = useFetch(hasWarehouse ? '/reports/workflow/' : null, {})
  const branches = asList(useFetch(hasWarehouse ? '/warehouse-stock/branches/' : null).data)
  const [stock, setStock] = useState({})
  const onStock = useCallback((id, d) => setStock((s) => ({ ...s, [id]: d })), [])

  const p = pnl.data, pp = pnlPrev.data, c = cash.data, t = wf.data?.totals
  if (!p || (hasWarehouse && !t)) return <Spinner full />

  const prevLabel = `к тем же дням ${MONTH_SHORT[(new Date().getMonth() + 11) % 12]}.`
  const stockList = branches.map((b) => ({ ...b, d: stock[b.id] })).filter((b) => b.d?.since)
  const stockTotal = stockList.reduce((s, b) => s + Number(b.d.balance_kg), 0)

  return (
    <div className="dir-page">
      <div className="dir-stats">
        <div className="dir-stat">
          <span className="label">Выручка с начала месяца</span>
          <span className="value">{money(p.revenue)}</span>
          <Delta cur={p.revenue} prev={pp?.revenue} label={prevLabel} />
        </div>
        <div className="dir-stat">
          <span className="label">Чистая прибыль</span>
          <span className={`value ${Number(p.net_profit) < 0 ? 'signal' : 'ledger'}`}>{money(p.net_profit)}</span>
          <span className="sub">маржа {num(p.net_margin_pct, 1)}% · {p.sales_count} {plural(p.sales_count, 'продажа', 'продажи', 'продаж')}</span>
        </div>
        {hasWarehouse ? (
          <>
            <div className="dir-stat">
              <span className="label">Оприходовано сегодня</span>
              <span className="value">{t.items_found} <span style={{ fontSize: '0.6em', fontWeight: 500, color: 'var(--muted)' }}>{plural(t.items_found, 'заказ', 'заказа', 'заказов')}</span></span>
              <span className="sub">{kg1(t.kg_found)} · {money(t.som_found)}</span>
            </div>
            <div className="dir-stat">
              <span className="label">Остаток на складе</span>
              <span className={`value ${stockTotal < 0 ? 'signal' : ''}`}>{stockList.length ? kg1(stockTotal) : '—'}</span>
              <span className="sub">{stockList.length ? `${stockList.length} ${plural(stockList.length, 'филиал', 'филиала', 'филиалов')} с учётом` : 'учёт веса не начат'}</span>
            </div>
          </>
        ) : (
          <div className="dir-stat">
            <span className="label">Денежный поток за месяц</span>
            <span className={`value ${Number(c?.net_cash_flow) < 0 ? 'signal' : 'ledger'}`}>{c ? money(c.net_cash_flow) : '…'}</span>
            <span className="sub">поступления минус выплаты</span>
          </div>
        )}
      </div>

      <div className={`dir-cols ${hasWarehouse ? 'wide-left' : ''}`}>
        <section className="dir-panel">
          <div className="dir-panel-head"><h3>Выручка и прибыль по месяцам</h3><Link to="/reports">полный отчёт →</Link></div>
          <MonthChart months={monthly.data?.months} />
        </section>
        {hasWarehouse && <Attention t={t} stockList={stockList} />}
      </div>

      {hasWarehouse && (
        <div className="dir-cols">
          <PeoplePanel employees={wf.data?.employees || []} />
          <StockPanel branches={branches} stock={stock} onStock={onStock} />
        </div>
      )}
      {/* невидимые загрузчики остатков по филиалам */}
      {hasWarehouse && branches.map((b) => <StockLoader key={b.id} branch={b} onStock={onStock} />)}
    </div>
  )
}

function Attention({ t, stockList }) {
  const items = []
  if (t.evening_now > 0) items.push({ to: '/workflow', n: t.evening_now, text: `${plural(t.evening_now, 'код ждёт', 'кода ждут', 'кодов ждут')} вечернего допоиска` })
  if (t.items_not_found > 0) items.push({ to: '/workflow', n: t.items_not_found, text: `${plural(t.items_not_found, 'код не найден', 'кода не найдены', 'кодов не найдены')} сегодня` })
  const negative = stockList.filter((b) => Number(b.d.balance_kg) < 0)
  if (negative.length) items.push({ to: '/stock', n: negative.length, text: `${plural(negative.length, 'филиал ушёл', 'филиала ушли', 'филиалов ушли')} в минус по весу` })
  return (
    <section className="dir-panel">
      <div className="dir-panel-head"><h3>Требует внимания</h3><span>сегодня</span></div>
      <div className="dir-alerts">
        {!items.length ? (
          <div className="dir-alert ok"><span className="count">✓</span>Хвостов нет: вечерний допоиск пуст, всё найденное оприходовано.</div>
        ) : items.map((it) => (
          <Link key={it.text} to={it.to} className="dir-alert"><span className="count">{it.n}</span>{it.text}<span className="arrow">→</span></Link>
        ))}
        <div className="dir-alert" style={{ background: 'var(--surface-soft)' }}>
          <span className="count" style={{ background: 'var(--ink)' }}>{t.active_orders_now}</span>
          {plural(t.active_orders_now, 'заявка', 'заявки', 'заявок')} в работе сейчас, {t.in_search_now} {plural(t.in_search_now, 'код', 'кода', 'кодов')} в поиске
          <Link to="/workflow" className="arrow">→</Link>
        </div>
      </div>
    </section>
  )
}

// Столбики: выручка (тёмный) и чистая прибыль (зелёный, красный при убытке).
function MonthChart({ months }) {
  const W = 640, H = 220, padL = 70, padR = 12, padT = 16, padB = 28
  if (!months) return <div className="empty">Считаю по месяцам…</div>
  const rows = months.slice(-6)
  if (rows.length < 2) return <div className="empty">Пока мало данных для графика.</div>
  const maxV = Math.max(1, ...rows.flatMap((m) => [Math.abs(Number(m.revenue)), Math.abs(Number(m.net_profit))]))
  const minV = Math.min(0, ...rows.map((m) => Number(m.net_profit)))
  const y = (v) => padT + ((maxV - v) / (maxV - minV)) * (H - padT - padB)
  const zero = y(0)
  const slot = (W - padL - padR) / rows.length
  const bw = Math.min(28, slot * 0.32)
  const ticks = [0, 0.5, 1].map((k) => minV + (maxV - minV) * k)
  return (
    <>
      <svg className="dir-chart" viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Выручка и чистая прибыль по месяцам">
        <g className="grid">
          {ticks.map((v) => (
            <g key={v}>
              <line x1={padL} x2={W - padR} y1={y(v)} y2={y(v)} />
              <text x={padL - 8} y={y(v) + 4} textAnchor="end">{short(v)}</text>
            </g>
          ))}
        </g>
        {rows.map((m, i) => {
          const cx = padL + slot * i + slot / 2
          const rev = Number(m.revenue), net = Number(m.net_profit)
          const [, mo] = m.month.split('-')
          return (
            <g key={m.month}>
              <rect className="bar-rev" x={cx - bw - 2} width={bw} y={y(Math.max(rev, 0))} height={Math.max(2, zero - y(Math.max(rev, 0)))} rx="3">
                <title>{`${MONTH_SHORT[Number(mo) - 1]}: выручка ${money(rev)}`}</title>
              </rect>
              <rect className={net >= 0 ? 'bar-net' : 'bar-neg'} x={cx + 2} width={bw}
                y={net >= 0 ? y(net) : zero} height={Math.max(2, Math.abs(y(net) - zero))} rx="3">
                <title>{`${MONTH_SHORT[Number(mo) - 1]}: чистая прибыль ${money(net)}`}</title>
              </rect>
              <text x={cx} y={H - 8} textAnchor="middle">{MONTH_SHORT[Number(mo) - 1]}</text>
            </g>
          )
        })}
      </svg>
      <div className="dir-legend">
        <span><i style={{ background: 'var(--ink)' }} />Выручка</span>
        <span><i style={{ background: 'var(--success)' }} />Чистая прибыль</span>
      </div>
    </>
  )
}

function PeoplePanel({ employees }) {
  return (
    <section className="dir-panel">
      <div className="dir-panel-head"><h3>Сотрудники сегодня</h3><Link to="/workflow">весь процесс →</Link></div>
      {!employees.length ? <div className="empty">Сегодня ещё никто ничего не обрабатывал.</div> : (
        <div className="table-wrap">
          <table className="table">
            <thead><tr><th>Сотрудник</th><th>Роль</th><th className="num">Оприходовал</th><th className="num">Кг</th><th className="num">Сом</th><th className="num">Не найдено</th></tr></thead>
            <tbody>
              {employees.slice(0, 8).map((e) => (
                <tr key={e.id}>
                  <td><strong>{e.name}</strong></td>
                  <td className="muted">{e.role_display}</td>
                  <td className="num">{e.items_found || (e.items_created ? `${e.orders_created} ${plural(e.orders_created, 'заявка', 'заявки', 'заявок')}` : '—')}</td>
                  <td className="num">{e.items_found ? num(e.kg_found, 1) : '—'}</td>
                  <td className="num">{e.items_found ? money(e.som_found) : '—'}</td>
                  <td className={`num ${e.items_not_found ? 'negative' : ''}`}>{e.items_not_found || '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  )
}

function StockLoader({ branch, onStock }) {
  const req = useFetch('/warehouse-stock/summary/', { branch: branch.id })
  useEffect(() => { if (req.data) onStock(branch.id, req.data) }, [req.data, branch.id, onStock])
  return null
}

function StockPanel({ branches, stock }) {
  const loaded = branches.length > 0 && branches.every((b) => stock[b.id])
  const rows = branches.map((b) => ({ ...b, d: stock[b.id] })).filter((b) => b.d?.since)
  const shortName = (n) => (String(n).includes('—') ? n.split('—').slice(1).join('—').replace('улица,', '').trim() : n)
  const todayRow = (d) => d.days.find((x) => x.date === today()) || { added_kg: 0, consumed_kg: 0 }
  return (
    <section className="dir-panel">
      <div className="dir-panel-head"><h3>Склад по филиалам</h3><Link to="/stock">внести приход →</Link></div>
      {!loaded ? <div className="empty">Загрузка…</div> : !rows.length ? (
        <div className="empty">Учёт веса ещё не начат. <Link to="/stock">Внесите первый приход</Link>, и остаток появится здесь.</div>
      ) : (
        <div className="table-wrap">
          <table className="table">
            <thead><tr><th>Филиал</th><th className="num">Сейчас</th><th className="num">Пришло сегодня</th><th className="num">Передано сегодня</th></tr></thead>
            <tbody>
              {rows.map((b) => {
                const tr = todayRow(b.d)
                return (
                  <tr key={b.id}>
                    <td><strong>{shortName(b.name)}</strong></td>
                    <td className={`num ${Number(b.d.balance_kg) < 0 ? 'negative' : ''}`}><strong>{kg1(b.d.balance_kg)}</strong></td>
                    <td className="num positive">{Number(tr.added_kg) ? `+${num(tr.added_kg, 1)}` : '—'}</td>
                    <td className="num">{Number(tr.consumed_kg) ? `−${num(tr.consumed_kg, 1)}` : '—'}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
    </section>
  )
}
