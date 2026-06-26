import { useState } from 'react'
import { useFetch } from '../lib/hooks'
import { firstOfMonth, today, money, signClass } from '../lib/format'
import { Field, Spinner, Stat } from '../components/ui'

// «Контроль / сверка» — показывает, как складываются ключевые итоги по каждому
// направлению, с пояснением «откуда», чтобы оператор сверил их с тетрадью/Excel.
export default function Control() {
  const [from, setFrom] = useState(firstOfMonth())
  const [to, setTo] = useState(today())
  const period = { from, to }
  const pnlEx = useFetch('/reports/pnl/', { ...period, module: 'EXPRESS' })
  const pnlBiz = useFetch('/reports/pnl/', { ...period, module: 'BUSINESS' })
  const balances = useFetch('/reports/balances/')
  const debts = useFetch('/reports/debts/')

  if (pnlEx.loading || pnlBiz.loading || balances.loading || debts.loading) return <Spinner full />

  const rows = balances.data || []
  const sumKgs = (list) => list.reduce((a, x) => a + Number(x.current_balance_kgs || 0), 0)
  const exMoney = sumKgs(rows.filter((a) => a.module === 'EXPRESS'))
  const bizMoney = sumKgs(rows.filter((a) => a.module === 'BUSINESS'))

  const pe = pnlEx.data || {}
  const pb = pnlBiz.data || {}
  const d = debts.data || {}

  return (
    <>
      <div className="card card-soft">
        <p className="muted" style={{ margin: 0, lineHeight: 1.6 }}>
          Здесь видно, <strong>как складывается каждая итоговая цифра</strong> — сверьте с тетрадью или Excel.
          Прибыль = выручка − себестоимость − операционные расходы. Авансы, переводы и конвертации в прибыль не входят.
        </p>
      </div>

      <div className="card">
        <div className="toolbar">
          <Field label="С даты">
            <input className="input" type="date" value={from} onChange={(e) => setFrom(e.target.value)} />
          </Field>
          <Field label="По дату">
            <input className="input" type="date" value={to} onChange={(e) => setTo(e.target.value)} />
          </Field>
        </div>
      </div>

      <div className="grid" style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(min(100%, 440px), 1fr))' }}>
        <ControlBlock
          title="Loko Business · закуп"
          p={pb}
          cashOnHand={bizMoney}
          receivable={d.business_receivable}
          payable={d.business_payable}
        />
        <ControlBlock
          title="Loko Express · карго"
          p={pe}
          cashOnHand={exMoney}
          receivable={d.express_receivable}
          payable={d.express_payable}
          note="Расходы карго пока не размечены на себестоимость и операционные — все показаны как операционные, поэтому себестоимость = 0."
        />
      </div>

      <div className="grid">
        <Stat label="Всего денег на счетах" value={money(exMoney + bizMoney)} tone={signClass(exMoney + bizMoney)} sub="Express + Business, в сомах" />
      </div>
    </>
  )
}

function ControlBlock({ title, p, cashOnHand, receivable, payable, note }) {
  const revenue = Number(p.revenue || 0)
  const cogs = Number(p.cogs || 0)
  const opex = Number(p.operating_expenses || 0)
  const other = Number(p.other_expenses || 0)
  const profit = Number(p.pre_tax_profit || 0)
  // Прибыль до налога = выручка − себест. − опер.расходы − прочие (как в build_pnl).
  const arithmeticOk = Math.abs(revenue - cogs - opex - other - profit) < 1

  return (
    <div className="card">
      <div className="card-header">
        <span className="card-title">{title}</span>
        {arithmeticOk && (
          <span style={{ color: 'var(--success)', fontSize: 13, fontWeight: 500 }}>✓ сходится</span>
        )}
      </div>
      <div className="table-wrap">
        <table className="table" style={{ minWidth: 0 }}>
          <tbody>
            <CtrlRow label="Выручка (заработано)" value={revenue} hint="продажи + признанные приходы" />
            <CtrlRow label="Себестоимость (закуп товара)" value={cogs} sign="minus" hint="оплата поставщику за товар" />
            <CtrlRow label="Операционные расходы" value={opex} sign="minus" hint="аренда, прочее" />
            {other !== 0 && (
              <CtrlRow label="Прочие (неоперационные) расходы" value={other} sign="minus" hint="вне основной деятельности" />
            )}
            <tr className="pnl-level">
              <td><strong>= Прибыль до налога</strong> <span className="caption" style={{ marginLeft: 6 }}>выручка − себест. − расходы</span></td>
              <td className={`num ${signClass(profit)}`}><strong>{money(profit)}</strong></td>
            </tr>
          </tbody>
        </table>
      </div>

      <div className="row row-wrap mt-lg">
        <Stat label="Деньги на счетах" value={money(cashOnHand)} tone={signClass(cashOnHand)} sub="текущий остаток" />
        <Stat label="Нам должны" value={money(receivable)} tone="pos" sub="дебиторка" />
        <Stat label="Мы должны" value={money(payable)} tone="neg" sub="кредиторка" />
      </div>

      {note && <p className="caption mt-lg" style={{ lineHeight: 1.5 }}>⚠ {note}</p>}
    </div>
  )
}

function CtrlRow({ label, value, sign, hint }) {
  const prefix = sign === 'minus' ? '−' : ''
  const cls = sign === 'minus' ? 'neg' : ''
  return (
    <tr>
      <td>
        {label}
        {hint && <span className="caption" style={{ marginLeft: 8 }}>{hint}</span>}
      </td>
      <td className={`num ${cls}`}>{prefix}{money(value)}</td>
    </tr>
  )
}
