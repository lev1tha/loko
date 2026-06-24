import { useState } from 'react'
import { useFetch } from '../lib/hooks'
import { firstOfMonth, today, money, num, dateRu, signClass } from '../lib/format'
import { Field, Modal, Segmented, Spinner, Stat } from '../components/ui'

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
  const [drill, setDrill] = useState(null) // { line, label, basis }

  const moduleParam = module !== 'all' ? { module } : {}
  const pnlParams = { from, to, payment, ...moduleParam, ...(taxRate !== '' ? { tax_rate: taxRate } : {}) }
  const pnl = useFetch('/reports/pnl/', pnlParams)
  const cash = useFetch('/reports/cashflow/', { from, to, payment, ...moduleParam })

  const openDrill = (basis) => (line, label) => setDrill({ line, label, basis })

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
        <p className="caption" style={{ margin: 0 }}>
          💡 Нажмите на «Выручку», «Расходы» или любую подсвеченную строку — откроется детальная
          расшифровка: откуда деньги и как.
        </p>
      </div>

      {report === 'pnl' ? (
        pnl.loading ? <Spinner /> : <Pnl data={pnl.data} onDrill={openDrill('accrual')} />
      ) : cash.loading ? (
        <Spinner />
      ) : (
        <CashFlow data={cash.data} onDrill={openDrill('cash')} />
      )}

      {drill && (
        <BreakdownModal
          {...drill}
          params={{ from, to, payment, ...moduleParam }}
          onClose={() => setDrill(null)}
        />
      )}
    </>
  )
}

function BreakdownModal({ line, label, basis, params, onClose }) {
  const data = useFetch('/reports/breakdown/', { ...params, line, basis })
  const d = data.data || {}
  const items = d.items || []

  return (
    <Modal title={`Расшифровка: ${label}`} onClose={onClose}>
      {data.loading ? (
        <Spinner />
      ) : (
        <>
          <div className="row row-wrap" style={{ marginBottom: 12 }}>
            <Stat label="Итого" value={money(d.total)} />
            <Stat label="Операций" value={num(d.count || 0, 0)} sub={d.truncated ? `показано ${d.shown}` : null} />
          </div>
          <div className="table-wrap" style={{ maxHeight: '52vh', overflowY: 'auto' }}>
            <table className="table" style={{ minWidth: 0 }}>
              <thead>
                <tr>
                  <th>№</th>
                  <th>Дата</th>
                  <th>Операция</th>
                  <th>Счёт</th>
                  <th className="num">Сумма</th>
                </tr>
              </thead>
              <tbody>
                {items.map((it) => (
                  <tr key={it.id}>
                    <td className="caption muted">{it.id}</td>
                    <td>{dateRu(it.date)}</td>
                    <td>{it.title}</td>
                    <td className="muted">{it.account}</td>
                    <td className="num">{money(it.amount, it.currency)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {d.truncated && (
            <p className="caption mt-lg">Показаны первые {d.shown} из {d.count}. Сузьте период для полного списка.</p>
          )}
        </>
      )}
    </Modal>
  )
}

function Line({ label, value, strong, sub, level, sign, indent, lineKey, onDrill }) {
  const cls = sign === 'minus' ? 'neg' : sign === 'plus' ? 'pos' : signClass(value)
  const prefix = sign === 'minus' ? '−' : sign === 'plus' ? '+' : ''
  const showValue = value !== null && value !== undefined
  const drillable = lineKey && onDrill && Number(value)
  return (
    <tr
      className={`${level ? 'pnl-level' : ''} ${drillable ? 'drillable' : ''}`}
      onClick={drillable ? () => onDrill(lineKey, label) : undefined}
      style={drillable ? { cursor: 'pointer' } : undefined}
    >
      <td style={{ paddingLeft: indent ? 28 : 12 }}>
        {strong ? <strong>{label}</strong> : label}
        {drillable && <span className="muted" style={{ marginLeft: 6 }}>›</span>}
        {sub && <span className="caption" style={{ marginLeft: 8 }}>{sub}</span>}
      </td>
      <td className={`num ${cls}`}>
        {showValue && (strong ? <strong>{prefix}{money(value)}</strong> : <>{prefix}{money(value)}</>)}
      </td>
    </tr>
  )
}

function Pnl({ data, onDrill }) {
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
      <p className="caption" style={{ margin: '0 0 12px', lineHeight: 1.5 }}>
        Сколько заработали и потратили за период (по дате операции). Прибыль = выручка − себестоимость − расходы. Авансы, переводы и конвертации сюда не входят.
      </p>
      <div className="table-wrap">
        <table className="table" style={{ minWidth: 0 }}>
          <tbody>
            <Line label="Выручка" value={d.revenue} strong level lineKey="revenue" onDrill={onDrill} />
            <Line label="Продажи Loko Express" value={d.express_revenue} sign="plus" indent lineKey="express_revenue" onDrill={onDrill} />
            <Line label="Депозиты, признанные как выручка" value={d.deposit_revenue} sign="plus" indent lineKey="deposit_revenue" onDrill={onDrill} />
            <Line label="Себестоимость" value={d.cogs} sign="minus" indent lineKey="cogs" onDrill={onDrill} />
            <Line label="Валовая прибыль" value={d.gross_profit} strong level />
            <Line label="Валовая маржа, %" value={null} sub={`${Number(d.gross_margin_pct || 0)} %`} indent />
            <Line label="Операционные расходы" sub={`${d.opex_count ?? 0} опер.`} value={d.operating_expenses} sign="minus" lineKey="opex" onDrill={onDrill} />
            {order.map((k) => arts[k] && (
              <Line key={k} label={arts[k].label} sub={arts[k].count ? `${arts[k].count} опер.` : null} value={arts[k].amount} sign="minus" indent lineKey={`opex_${k}`} onDrill={onDrill} />
            ))}
            <Line label="Операционная прибыль" value={d.operating_profit} strong level />
            <Line label="Прочие доходы" value={d.other_income} sign="plus" indent />
            <Line label="Прочие расходы" value={d.other_expenses} sign="minus" indent lineKey="other" onDrill={onDrill} />
            <Line label="Финансовые расходы" value={d.financial_expenses} sign="minus" indent />
            <Line label="Прибыль до налогообложения" value={d.pre_tax_profit} strong level />
            <Line label="Налоги (нал/безнал)" sub={`нал ${Number(d.cash_tax_rate || 0)}% · безнал ${Number(d.noncash_tax_rate || 0)}% → эфф. ${Number(d.tax_rate || 0)}%`} value={d.tax} sign="minus" indent />
            <Line label="Чистая прибыль" value={d.net_profit} strong level />
            <Line label="Чистая рентабельность, %" value={null} sub={`${Number(d.net_margin_pct || 0)} %`} indent />
          </tbody>
        </table>
      </div>
      <p className="caption mt-lg">
        Приходных операций: {ops.income ?? 0} (продаж {d.sales_count ?? 0} + депозитов {d.deposit_count ?? 0}),
        расходных: {ops.expense ?? 0}. Нажмите на строку со знаком «›» — увидите все операции за ней.
      </p>
    </div>
    </>
  )
}

function CashFlow({ data, onDrill }) {
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
      <p className="caption" style={{ margin: '0 0 12px', lineHeight: 1.5 }}>
        Сколько денег реально пришло и ушло (по дате оплаты). Показывает остаток на начало и конец периода.
      </p>
      <div className="table-wrap">
        <table className="table" style={{ minWidth: 0 }}>
          <tbody>
            <Line label="Остаток денег на начало" value={d.opening_balance} strong level />
            <Line label="Операционный приток" value={d.operating_inflow} sign="plus" lineKey="inflow" onDrill={onDrill} />
            <Line label="Продажи Loko Express (оплата)" value={d.express_inflow} sign="plus" indent lineKey="express_revenue" onDrill={onDrill} />
            <Line label="Принятые депозиты (Business)" value={d.deposits_inflow} sign="plus" indent lineKey="deposit_revenue" onDrill={onDrill} />
            <Line label="Операционный отток" value={d.operating_outflow} sign="minus" />
            <Line label="OpEx" value={d.opex} sign="minus" indent lineKey="opex" onDrill={onDrill} />
            <Line label="Закуп товара (себест.)" value={d.cogs_paid} sign="minus" indent lineKey="cogs" onDrill={onDrill} />
            <Line label="Поставщики / авансы" value={d.supplier_payments} sign="minus" indent lineKey="supplier" onDrill={onDrill} />
            <Line label="Прочее (неоперац.)" value={d.other_outflow} sign="minus" indent lineKey="other" onDrill={onDrill} />
            <Line label="Чистый операционный ДДС" value={d.net_operating} strong level />
            <Line label="Инвестиционная деятельность" value={d.net_investing} strong level />
            <Line label="Покупка оборудования/активов" value={d.investing_outflow} sign="minus" indent lineKey="invest" onDrill={onDrill} />
            <Line label="Финансовая деятельность" value={d.net_financing} strong level />
            <Line label="Изъятие собственника" value={d.owner_withdrawals} sign="minus" indent lineKey="owner" onDrill={onDrill} />
            <Line label="Кредиты / проценты" value={d.financing_other} sign="minus" indent lineKey="financing" onDrill={onDrill} />
            <Line label="Чистое изменение денег" value={d.net_cash_flow} strong level />
            <Line label="Остаток денег на конец" value={d.closing_balance} strong level />
          </tbody>
        </table>
      </div>
      <p className="caption mt-lg">
        Приходных операций: {ops.income ?? 0}, расходных: {ops.expense ?? 0}. ОДДС по «дате оплаты».
        Нажмите на строку со знаком «›» — увидите операции за ней.
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
