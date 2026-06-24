import { useState } from 'react'
import { useFetch } from '../lib/hooks'
import { firstOfMonth, today, money, num, signClass } from '../lib/format'
import { Field, Segmented, Spinner, Stat } from '../components/ui'

const PAYMENTS = [
  { value: 'all', label: 'Все' },
  { value: 'cash', label: 'Наличные' },
  { value: 'noncash', label: 'Безнал' },
]
const REPORTS = [
  { value: 'pnl', label: 'ООПИУ (P&L)' },
  { value: 'cashflow', label: 'ОДДС (Cash Flow)' },
]
const MODULES = [
  { value: 'all', label: 'Всё' },
  { value: 'EXPRESS', label: 'Express' },
  { value: 'BUSINESS', label: 'Business' },
]

export default function Reports() {
  const [from, setFrom] = useState(firstOfMonth())
  const [to, setTo] = useState(today())
  const [payment, setPayment] = useState('all')
  const [report, setReport] = useState('pnl')
  const [module, setModule] = useState('all')
  const [taxRate, setTaxRate] = useState('')

  const moduleParam = module !== 'all' ? { module } : {}
  const pnlParams = { from, to, payment, ...moduleParam, ...(taxRate !== '' ? { tax_rate: taxRate } : {}) }
  const pnl = useFetch('/reports/pnl/', pnlParams)
  const cash = useFetch('/reports/cashflow/', { from, to, payment, ...moduleParam })

  return (
    <>
      <div className="card">
        <div className="card-header">
          <div className="toolbar grow">
            <Field label="С даты">
              <input className="input" type="date" value={from} onChange={(e) => setFrom(e.target.value)} />
            </Field>
            <Field label="По дату">
              <input className="input" type="date" value={to} onChange={(e) => setTo(e.target.value)} />
            </Field>
            <div className="field">
              <span className="field-label">Направление</span>
              <Segmented value={module} onChange={setModule} options={MODULES} />
            </div>
            <div className="field">
              <span className="field-label">Расчёт</span>
              <Segmented value={payment} onChange={setPayment} options={PAYMENTS} />
            </div>
            {report === 'pnl' && (
              <Field label="Ставка налога, %" hint="Пусто = из настроек">
                <input className="input" type="number" step="0.01" min="0" value={taxRate}
                  onChange={(e) => setTaxRate(e.target.value)} placeholder="из настроек" style={{ maxWidth: 140 }} />
              </Field>
            )}
          </div>
          <div className="field">
            <span className="field-label">Отчёт</span>
            <Segmented value={report} onChange={setReport} options={REPORTS} />
          </div>
        </div>
      </div>

      {report === 'pnl' ? (
        pnl.loading ? <Spinner /> : <Pnl data={pnl.data} />
      ) : cash.loading ? (
        <Spinner />
      ) : (
        <CashFlow data={cash.data} />
      )}
    </>
  )
}

function Line({ label, value, strong, sub, level, sign, indent }) {
  const cls = sign === 'minus' ? 'neg' : sign === 'plus' ? 'pos' : signClass(value)
  const prefix = sign === 'minus' ? '−' : sign === 'plus' ? '+' : ''
  const showValue = value !== null && value !== undefined
  return (
    <tr className={level ? 'pnl-level' : ''}>
      <td style={{ paddingLeft: indent ? 28 : 12 }}>
        {strong ? <strong>{label}</strong> : label}
        {sub && <span className="caption" style={{ marginLeft: 8 }}>{sub}</span>}
      </td>
      <td className={`num ${cls}`}>
        {showValue && (strong ? <strong>{prefix}{money(value)}</strong> : <>{prefix}{money(value)}</>)}
      </td>
    </tr>
  )
}

function Pnl({ data }) {
  const d = data || {}
  const arts = d.opex_articles || {}
  const ops = d.operations || {}
  const order = ['RENT', 'PAYROLL', 'INCOME_TAX', 'SOCIAL_FUND', 'OTHER']
  return (
    <>
    <div className="grid" style={{ marginBottom: 'var(--s-lg)' }}>
      <Stat label="Приходных операций" value={num(ops.income || 0, 0)} sub="продажи + признанные депозиты" />
      <Stat label="Расходных операций" value={num(ops.expense || 0, 0)} sub="за период" />
      <Stat label="Всего операций" value={num((ops.income || 0) + (ops.expense || 0), 0)} />
    </div>
    <div className="card" style={{ maxWidth: 760 }}>
      <div className="card-header">
        <span className="card-title">Отчёт о прибылях и убытках (ООПИУ)</span>
      </div>
      <div className="table-wrap">
        <table className="table" style={{ minWidth: 0 }}>
          <tbody>
            <Line label="Выручка" value={d.revenue} strong level />
            <Line label="Продажи Loko Express" value={d.express_revenue} sign="plus" indent />
            <Line label="Депозиты, признанные как выручка" value={d.deposit_revenue} sign="plus" indent />
            <Line label="Себестоимость" value={d.cogs} sign="minus" indent />
            <Line label="Валовая прибыль" value={d.gross_profit} strong level />
            <Line label="Валовая маржа, %" value={null} sub={`${Number(d.gross_margin_pct || 0)} %`} indent />
            <Line label="Операционные расходы" sub={`${d.opex_count ?? 0} опер.`} value={d.operating_expenses} sign="minus" />
            {order.map((k) => arts[k] && (
              <Line key={k} label={arts[k].label} sub={arts[k].count ? `${arts[k].count} опер.` : null} value={arts[k].amount} sign="minus" indent />
            ))}
            <Line label="Операционная прибыль" value={d.operating_profit} strong level />
            <Line label="Прочие доходы" value={d.other_income} sign="plus" indent />
            <Line label="Прочие расходы" value={d.other_expenses} sign="minus" indent />
            <Line label="Финансовые расходы" value={d.financial_expenses} sign="minus" indent />
            <Line label="Прибыль до налогообложения" value={d.pre_tax_profit} strong level />
            <Line
              label="Налог на прибыль"
              sub={`${Number(d.tax_rate || 0)}%`}
              value={d.tax}
              sign="minus"
              indent
            />
            <Line label="Чистая прибыль" value={d.net_profit} strong level />
            <Line label="Чистая рентабельность, %" value={null} sub={`${Number(d.net_margin_pct || 0)} %`} indent />
          </tbody>
        </table>
      </div>
      <p className="caption mt-lg">
        Приходных операций: {ops.income ?? 0} (продаж {d.sales_count ?? 0} + депозитов {d.deposit_count ?? 0}),
        расходных: {ops.expense ?? 0}. Все суммы консолидированы в сомах (юань — по курсу из настроек).
        Налог рассчитывается на положительную прибыль до налогообложения.
      </p>
    </div>
    </>
  )
}

function CashFlow({ data }) {
  const d = data || {}
  const ops = d.operations || {}
  return (
    <>
    <div className="grid" style={{ marginBottom: 'var(--s-lg)' }}>
      <Stat label="Приходных операций" value={num(ops.income || 0, 0)} sub="продажи + депозиты" />
      <Stat label="Расходных операций" value={num(ops.expense || 0, 0)} sub="за период" />
      <Stat label="Всего операций" value={num((ops.income || 0) + (ops.expense || 0), 0)} />
    </div>
    <div className="card" style={{ maxWidth: 760 }}>
      <div className="card-header">
        <span className="card-title">Отчёт о движении денежных средств (ОДДС)</span>
      </div>
      <div className="table-wrap">
        <table className="table" style={{ minWidth: 0 }}>
          <tbody>
            <Line label="Остаток денег на начало" value={d.opening_balance} strong level />
            <Line label="Операционный приток" value={d.operating_inflow} sign="plus" />
            <Line label="Продажи Loko Express (оплата)" value={d.express_inflow} sign="plus" indent />
            <Line label="Принятые депозиты (Business)" value={d.deposits_inflow} sign="plus" indent />
            <Line label="Операционный отток" value={d.operating_outflow} sign="minus" />
            <Line label="OpEx" value={d.opex} sign="minus" indent />
            <Line label="Закуп товара (себест.)" value={d.cogs_paid} sign="minus" indent />
            <Line label="Поставщики / авансы" value={d.supplier_payments} sign="minus" indent />
            <Line label="Прочее (неоперац.)" value={d.other_outflow} sign="minus" indent />
            <Line label="Чистый операционный ДДС" value={d.net_operating} strong level />
            <Line label="Финансовая деятельность" value={d.financing_outflow} sign="minus" />
            <Line label="Изъятие собственника" value={d.owner_withdrawals} sign="minus" indent />
            <Line label="Чистое изменение денег" value={d.net_cash_flow} strong level />
            <Line label="Остаток денег на конец" value={d.closing_balance} strong level />
          </tbody>
        </table>
      </div>
      <p className="caption mt-lg">
        Приходных операций: {ops.income ?? 0}, расходных: {ops.expense ?? 0}. ОДДС считается по «дате
        оплаты» и фактически оплаченным суммам. Суммы в юанях пересчитаны в сомы по курсу из настроек.
      </p>

      {Array.isArray(d.payment_breakdown) && d.payment_breakdown.length > 0 && (
        <div className="mt-lg">
          <div className="card-title" style={{ marginBottom: 12 }}>Свод оплат по счетам</div>
          <div className="table-wrap">
            <table className="table" style={{ minWidth: 0 }}>
              <thead>
                <tr>
                  <th>Счёт</th>
                  <th>Вал.</th>
                  <th className="num">Приход</th>
                  <th className="num">Расход</th>
                  <th className="num">Операций</th>
                </tr>
              </thead>
              <tbody>
                {d.payment_breakdown.map((r) => (
                  <tr key={r.account}>
                    <td>{r.account}</td>
                    <td>{r.currency}</td>
                    <td className="num pos">{money(r.income, r.currency)}</td>
                    <td className="num neg">{money(r.expense, r.currency)}</td>
                    <td className="num muted">{r.income_count}/{r.expense_count}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
    </>
  )
}
