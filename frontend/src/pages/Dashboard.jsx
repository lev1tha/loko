import { Link } from 'react-router-dom'
import { useFetch } from '../lib/hooks'
import { firstOfMonth, today, money, kg, num, signClass } from '../lib/format'
import { Spinner, Stat, Badge } from '../components/ui'

export default function Dashboard() {
  const period = { from: firstOfMonth(), to: today() }
  const balances = useFetch('/reports/balances/')
  const summary = useFetch('/sales/summary/', period)
  const pnl = useFetch('/reports/pnl/', period)
  const cash = useFetch('/reports/cashflow/', period)
  const debts = useFetch('/reports/debts/')

  if (balances.loading || summary.loading || pnl.loading || cash.loading || debts.loading) {
    return <Spinner full />
  }

  const rows = balances.data || []
  // Totals must use the KGS-converted value (accounts mix сом and юань).
  const sumKgs = (list) => list.reduce((acc, a) => acc + Number(a.current_balance_kgs || 0), 0)
  const expressRows = rows.filter((a) => a.module === 'EXPRESS')
  const businessRows = rows.filter((a) => a.module === 'BUSINESS')
  const totalBalance = sumKgs(rows)

  const s = summary.data || {}
  const p = pnl.data || {}
  const c = cash.data || {}
  const dbt = debts.data || {}

  return (
    <>
      <div className="grid">
        <Stat label="Остаток на счетах (оба напр.)" value={money(totalBalance)} tone={signClass(totalBalance)} sub="консолидировано в сомах" />
        <Stat label="Выручка за месяц (ООПИУ)" value={money(p.revenue)} sub={`Express ${money(p.express_revenue)} + депозиты`} />
        <Stat label="Чистая прибыль (ООПИУ)" value={money(p.net_profit)} tone={signClass(p.net_profit)} sub={`налог ${Number(p.tax_rate || 0)}%`} />
        <Stat label="Денежный поток (ОДДС)" value={money(c.net_cash_flow)} tone={signClass(c.net_cash_flow)} />
      </div>

      <div className="grid" style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(min(100%, 320px), 1fr))' }}>
        <div className="card">
          <div className="card-header">
            <span className="card-title">Loko Express · счета</span>
            <Link className="btn btn-secondary btn-sm" to="/express/accounts">Открыть</Link>
          </div>
          <BalanceTable rows={expressRows} />
        </div>

        <div className="card">
          <div className="card-header">
            <span className="card-title">Loko Business · счета</span>
            <Link className="btn btn-secondary btn-sm" to="/business/accounts">Открыть</Link>
          </div>
          <BalanceTable rows={businessRows} />
        </div>

        <div className="card">
          <div className="card-header">
            <span className="card-title">Прибыль за месяц</span>
            <Link className="btn btn-secondary btn-sm" to="/reports">Отчёты</Link>
          </div>
          <div className="table-wrap">
            <table className="table" style={{ minWidth: 0 }}>
              <tbody>
                <tr><td>Выручка</td><td className="num">{money(p.revenue)}</td></tr>
                <tr><td>Себестоимость</td><td className="num neg">−{money(p.cogs)}</td></tr>
                <tr><td>Валовая прибыль</td><td className="num">{money(p.gross_profit)}</td></tr>
                <tr><td>Операционные расходы</td><td className="num neg">−{money(p.operating_expenses)}</td></tr>
                <tr><td>Налог</td><td className="num neg">−{money(p.tax)}</td></tr>
                <tr>
                  <td><strong>Чистая прибыль</strong></td>
                  <td className={`num ${signClass(p.net_profit)}`}><strong>{money(p.net_profit)}</strong></td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>

        <div className="card">
          <div className="card-header">
            <span className="card-title">Задолженности</span>
            <Link className="btn btn-secondary btn-sm" to="/business/debts">Открыть</Link>
          </div>
          <div className="row row-wrap">
            <Stat label="Кредиторская" value={money(dbt.payable)} tone="neg" />
            <Stat label="Дебиторская" value={money(dbt.receivable)} tone="pos" />
          </div>
          <div className="row row-wrap mt-lg">
            <Stat label="Приходных операций" value={num(p.operations?.income || 0, 0)} sub="за месяц" />
            <Stat label="Расходных операций" value={num(p.operations?.expense || 0, 0)} sub="за месяц" />
          </div>
          <div className="mt-lg">
            <Stat label="Маржа продаж за месяц" value={money(s.margin)} sub={`${s.count || 0} продаж · ${kg(s.weight)}`} tone={signClass(s.margin)} />
          </div>
        </div>
      </div>
    </>
  )
}

function BalanceTable({ rows }) {
  if (!rows.length) return <div className="empty">Нет счетов</div>
  return (
    <div className="table-wrap">
      <table className="table" style={{ minWidth: 0 }}>
        <tbody>
          {rows.map((a) => (
            <tr key={a.id}>
              <td>
                {a.name} <Badge variant={a.currency === 'KGS' ? 'badge-cash' : 'badge-bank'}>{a.currency}</Badge>
              </td>
              <td className={`num ${signClass(a.current_balance)}`}>{money(a.current_balance, a.currency)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
