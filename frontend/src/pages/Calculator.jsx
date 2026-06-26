import { useState } from 'react'
import { useFetch } from '../lib/hooks'
import { money, num, signClass } from '../lib/format'
import { Field, Spinner } from '../components/ui'

// Калькулятор комиссии за закуп и маржи заказа из Китая.
// Курсы/ставки берутся из Настроек; ничего не сохраняется — это инструмент оценки.
export default function Calculator() {
  const settings = useFetch('/settings/')

  const [goodsCost, setGoodsCost] = useState('')
  const [weight, setWeight] = useState('')
  const [commission, setCommission] = useState('10') // базовая комиссия, %
  const [surcharge, setSurcharge] = useState('0') // надбавки (проверка/срочно/др. город), %
  const [discount, setDiscount] = useState('0') // скидка, %

  if (settings.loading) return <Spinner full />
  const s = settings.data || {}

  const usdPrice = Number(s.price_per_kg_usd || 0)
  const usdRate = Number(s.usd_rate_som || 0)
  const costPerKg = Number(s.base_cost_per_kg_som || 0)
  const deliveryRate = usdPrice * usdRate // цена доставки за 1 кг, сом

  const cost = Number(goodsCost || 0)
  const w = Number(weight || 0)
  const effPct = Number(commission || 0) + Number(surcharge || 0) - Number(discount || 0)

  const commissionSom = (cost * effPct) / 100 // комиссия за закуп
  const deliveryIncome = w * deliveryRate // доход от доставки
  const revenue = commissionSom + deliveryIncome // итого выручка
  const deliveryCost = w * costPerKg // себестоимость доставки
  const margin = revenue - deliveryCost // маржинальная прибыль
  const marginPct = revenue ? (margin / revenue) * 100 : 0

  return (
    <>
      <div className="card card-soft">
        <p className="muted" style={{ margin: 0, lineHeight: 1.6 }}>
          Оценка заказа из Китая: комиссия за закуп (% от стоимости товара) + доход от доставки (по весу) − себестоимость
          доставки. Курсы и ставки берутся из <strong>Настроек</strong> (цена {usdPrice}$/кг · курс {usdRate} · себест.
          {' '}{costPerKg} сом/кг). Ничего не сохраняется — это калькулятор.
        </p>
      </div>

      <div className="grid" style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(min(100%, 420px), 1fr))' }}>
        <div className="card">
          <div className="card-header"><span className="card-title">Параметры заказа</span></div>
          <div className="col">
            <div className="row row-wrap">
              <Field label="Стоимость товара, сом" hint="за что берём комиссию">
                <input className="input" type="number" step="0.01" min="0" value={goodsCost} onChange={(e) => setGoodsCost(e.target.value)} placeholder="50000" autoFocus />
              </Field>
              <Field label="Вес, кг" hint="для доставки">
                <input className="input" type="number" step="0.001" min="0" value={weight} onChange={(e) => setWeight(e.target.value)} placeholder="3.5" />
              </Field>
            </div>
            <div className="row row-wrap">
              <Field label="Базовая комиссия, %" hint="по умолчанию 10%">
                <input className="input" type="number" step="0.1" min="0" value={commission} onChange={(e) => setCommission(e.target.value)} />
              </Field>
              <Field label="Надбавки, %" hint="проверка / срочно / др. город">
                <input className="input" type="number" step="0.1" min="0" value={surcharge} onChange={(e) => setSurcharge(e.target.value)} />
              </Field>
              <Field label="Скидка, %" hint="постоянный клиент и т.п.">
                <input className="input" type="number" step="0.1" min="0" value={discount} onChange={(e) => setDiscount(e.target.value)} />
              </Field>
            </div>
          </div>
        </div>

        <div className="card sale-preview">
          <div className="card-header"><span className="card-title">Расчёт</span></div>
          <div className="table-wrap">
            <table className="table" style={{ minWidth: 0 }}>
              <tbody>
                <tr>
                  <td>Итоговая комиссия</td>
                  <td className="num">{num(effPct, 1)} %</td>
                </tr>
                <tr>
                  <td>Комиссия за закуп</td>
                  <td className="num">{money(commissionSom)}</td>
                </tr>
                <tr>
                  <td>Доход от доставки <span className="caption muted">({num(w, 2)} кг × {money(deliveryRate)})</span></td>
                  <td className="num">{money(deliveryIncome)}</td>
                </tr>
                <tr className="pnl-level">
                  <td><strong>Итого выручка</strong></td>
                  <td className="num"><strong>{money(revenue)}</strong></td>
                </tr>
                <tr>
                  <td>Себестоимость доставки <span className="caption muted">({num(w, 2)} кг × {money(costPerKg)})</span></td>
                  <td className="num neg">−{money(deliveryCost)}</td>
                </tr>
                <tr className="pnl-level">
                  <td><strong>Маржинальная прибыль</strong></td>
                  <td className={`num ${signClass(margin)}`}><strong>{money(margin)}</strong></td>
                </tr>
                <tr>
                  <td>Маржа, %</td>
                  <td className={`num ${signClass(margin)}`}>{num(marginPct, 1)} %</td>
                </tr>
              </tbody>
            </table>
          </div>
          <p className="caption mt-lg" style={{ lineHeight: 1.5 }}>
            Комиссия = стоимость товара × итоговый %. Доставка и себестоимость считаются от веса по ставкам из Настроек.
          </p>
        </div>
      </div>
    </>
  )
}
