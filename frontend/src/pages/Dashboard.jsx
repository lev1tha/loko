import { Link } from 'react-router-dom'
import { useFetch } from '../lib/hooks'
import { firstOfMonth, today, money, signClass } from '../lib/format'
import { Spinner, Stat, Badge } from '../components/ui'

export default function Dashboard() {
  const period = { from: firstOfMonth(), to: today() }
  const balances = useFetch('/reports/balances/')
  const pnlEx = useFetch('/reports/pnl/', { ...period, module: 'EXPRESS' })
  const pnlBiz = useFetch('/reports/pnl/', { ...period, module: 'BUSINESS' })
  const debts = useFetch('/reports/debts/')
  const sales = useFetch('/sales/summary/', period)

  if (balances.loading || pnlEx.loading || pnlBiz.loading || debts.loading || sales.loading) {
    return <Spinner full />
  }

  const rows = balances.data || []
  const sumKgs = (list) => list.reduce((acc, a) => acc + Number(a.current_balance_kgs || 0), 0)
  const expressRows = rows.filter((a) => a.module === 'EXPRESS')
  const businessRows = rows.filter((a) => a.module === 'BUSINESS')
  const exMoney = sumKgs(expressRows)
  const bizMoney = sumKgs(businessRows)
  const totalMoney = exMoney + bizMoney

  const pe = pnlEx.data || {}
  const pb = pnlBiz.data || {}
  const dbt = debts.data || {}
  const s = sales.data || {}

  return (
    <>
      {/* Деньги — общая картина */}
      <div className="grid">
        <Stat label="Всего денег на счетах" value={money(totalMoney)} tone={signClass(totalMoney)} sub="Express + Business, в сомах" />
        <Stat label="Деньги Loko Express" value={money(exMoney)} sub="карго" />
        <Stat label="Деньги Loko Business" value={money(bizMoney)} sub="закуп · юань пересчитан в сом" />
      </div>

      {/* Два направления — отдельно */}
      <div className="grid" style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(min(100%, 420px), 1fr))' }}>
        <DirectionCard
          title="Loko Express · карго"
          subtitle="доставка посылок Китай → КР"
          link="/sales"
          linkLabel="Продажи"
          revenue={pe.revenue}
          expenses={Number(pe.cogs || 0) + Number(pe.operating_expenses || 0)}
          profit={pe.pre_tax_profit}
          cashOnHand={exMoney}
          receivable={dbt.express_receivable}
          payable={dbt.express_payable}
          extraLabel="Продаж за месяц"
          extraValue={s.count || 0}
          note={Number(pe.cogs || 0) > 0
            ? 'Себестоимость учитывается по продажам с весом; прибыль = выручка − себестоимость − расходы.'
            : 'Себестоимость по историческим продажам не размечена (= 0); прибыль = выручка − все расходы.'}
        />
        <DirectionCard
          title="Loko Business · закуп"
          subtitle="закуп товара в Китае под заказ"
          link="/business/orders"
          linkLabel="Заказы"
          revenue={pb.revenue}
          expenses={Number(pb.cogs || 0) + Number(pb.operating_expenses || 0)}
          profit={pb.pre_tax_profit}
          cashOnHand={bizMoney}
          receivable={dbt.business_receivable}
          payable={dbt.business_payable}
        />
      </div>

      {/* Счета — детально */}
      <div className="grid" style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(min(100%, 320px), 1fr))' }}>
        <div className="card">
          <div className="card-header">
            <span className="card-title">Счета Express</span>
            <Link className="btn btn-secondary btn-sm" to="/express/accounts">Открыть</Link>
          </div>
          <BalanceTable rows={expressRows} />
        </div>
        <div className="card">
          <div className="card-header">
            <span className="card-title">Счета Business</span>
            <Link className="btn btn-secondary btn-sm" to="/business/accounts">Открыть</Link>
          </div>
          <BalanceTable rows={businessRows} />
        </div>
      </div>
    </>
  )
}

function DirectionCard({ title, subtitle, link, linkLabel, revenue, expenses, profit, cashOnHand, receivable, payable, extraLabel, extraValue, note }) {
  return (
    <div className="card">
      <div className="card-header">
        <div>
          <div className="card-title">{title}</div>
          <div className="caption">{subtitle}</div>
        </div>
        <Link className="btn btn-secondary btn-sm" to={link}>{linkLabel}</Link>
      </div>

      <div className="row row-wrap">
        <Stat label="Заработано за месяц" value={money(revenue)} sub="выручка" />
        <Stat label="Прибыль за месяц" value={money(profit)} tone={signClass(profit)} sub="до налога" />
        <Stat label="Сейчас на счетах" value={money(cashOnHand)} tone={signClass(cashOnHand)} />
      </div>

      <div className="table-wrap mt-lg">
        <table className="table" style={{ minWidth: 0 }}>
          <tbody>
            <tr><td>Выручка (заработано)</td><td className="num">{money(revenue)}</td></tr>
            <tr><td>Все расходы</td><td className="num neg">−{money(expenses)}</td></tr>
            <tr>
              <td><strong>Прибыль (до налога)</strong></td>
              <td className={`num ${signClass(profit)}`}><strong>{money(profit)}</strong></td>
            </tr>
          </tbody>
        </table>
      </div>

      <div className="row row-wrap mt-lg">
        <Stat label="Нам должны" value={money(receivable)} tone="pos" sub="дебиторка" />
        <Stat label="Мы должны" value={money(payable)} tone="neg" sub="кредиторка" />
        {extraLabel && <Stat label={extraLabel} value={extraValue} />}
      </div>

      {note && <p className="caption mt-lg" style={{ lineHeight: 1.5 }}>⚠ {note}</p>}
    </div>
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
