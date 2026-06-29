import { useEffect, useRef, useState } from 'react'
import api, { errorMessage } from '../api/client'
import { useFetch, asList } from '../lib/hooks'
import { today, som, kg, dateRu } from '../lib/format'
import { Alert, Field, Segmented } from '../components/ui'
import { LoadingTruck } from '../components/states'
import { IconPlus } from '../components/icons'

// «Прямая сумма» — первой и по умолчанию (основной режим для сотрудников),
// «По весу» — вторым.
const MODES = [
  { value: 'DIRECT', label: 'Прямая сумма' },
  { value: 'WEIGHT', label: 'По весу' },
]

// Страница роли «Сотрудник»: только добавление продажи в Loko Express.
// Дата — всегда сегодня (real-time, ставится при отправке). Логика симметрична:
//   • «По весу»     — вводим вес (× кол-во мест), сумма считается и показывается.
//   • «Прямая сумма» — вводим сумму, ВЕС показывается расчётно и НЕ редактируется.
// Видна ИСКЛЮЧИТЕЛЬНО общая стоимость — без маржи, себестоимости и дебиторки.
export default function OperatorSale() {
  const accountsReq = useFetch('/sales/accounts/')
  const accounts = asList(accountsReq.data)

  const [mode, setMode] = useState('DIRECT')
  const [clientCode, setClientCode] = useState('')
  const [weight, setWeight] = useState('')
  const [directAmount, setDirectAmount] = useState('')
  const [places, setPlaces] = useState('1')
  const [accountId, setAccountId] = useState('')
  const [quote, setQuote] = useState(null)
  const [rate, setRate] = useState(0) // стоимость 1 кг (сом) — для пересчёта суммы → вес
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')
  const [saving, setSaving] = useState(false)
  const codeRef = useRef(null)

  // Вес одного места × кол-во мест = итоговый вес груза (режим «по весу»).
  const perPlace = parseFloat(weight) || 0
  const placesN = parseInt(places, 10) || 1
  const totalWeight = Number((perPlace * placesN).toFixed(3))

  // Ставка за 1 кг (для режима «прямая сумма»: вес = сумма ÷ ставка).
  useEffect(() => {
    api
      .post('/sales/quote/', { weight_kg: 1 })
      .then((res) => setRate(Number(res.data.price_som) || 0))
      .catch(() => setRate(0))
  }, [])

  // Подставить первый счёт, когда список загрузится.
  useEffect(() => {
    if (!accountId && accounts.length) setAccountId(String(accounts[0].id))
  }, [accounts, accountId])

  // Живой расчёт общей стоимости по ИТОГОВОМУ весу (без себестоимости/маржи).
  useEffect(() => {
    if (mode !== 'WEIGHT') return
    if (!(totalWeight > 0)) {
      setQuote(null)
      return
    }
    let active = true
    const t = setTimeout(() => {
      api
        .post('/sales/quote/', { weight_kg: totalWeight })
        .then((res) => active && setQuote(res.data))
        .catch(() => active && setQuote(null))
    }, 250)
    return () => {
      active = false
      clearTimeout(t)
    }
  }, [totalWeight, mode])

  const directNum = parseFloat(directAmount) || 0
  // Расчётный вес для «прямой суммы» — только показ, не редактируется.
  const derivedWeight = rate > 0 && directNum > 0 ? Number((directNum / rate).toFixed(3)) : 0
  // Общая стоимость: по весу — из расчёта, иначе — введённая сумма.
  const total = mode === 'WEIGHT' ? Number(quote?.price_som || 0) : directNum

  async function submit(e) {
    e.preventDefault()
    setError('')
    setSuccess('')

    if (!clientCode.trim()) {
      setError('Укажите код клиента.')
      return
    }
    if (!accountId) {
      setError('Нет доступного счёта зачисления — обратитесь к администратору.')
      return
    }
    if (mode === 'WEIGHT' && !(totalWeight > 0)) {
      setError('Укажите вес места больше нуля.')
      return
    }
    if (mode === 'DIRECT' && !(directNum > 0)) {
      setError('Укажите сумму больше нуля.')
      return
    }

    setSaving(true)
    try {
      const body = {
        amount_mode: mode,
        client_code: clientCode.trim(),
        places: placesN,
        account: accountId,
        // Дата операции — всегда сегодня, фиксируется в момент сохранения.
        date: today(),
        cost_is_manual: false,
        // Express: оплата всегда полная в день операции (начислено = оплачено).
        paid_som: null,
        payment_date: null,
      }
      if (mode === 'WEIGHT') {
        // Итоговый вес груза (вес места × мест).
        body.weight_kg = totalWeight > 0 ? totalWeight : null
      } else {
        // «Прямая сумма»: сумма вводится, вес — только расчётный показ (не пишем).
        body.price_som = directAmount
        body.weight_kg = null
      }

      const { data } = await api.post('/sales/', body)
      setSuccess(`Продажа «${data.client_code}» на ${som(data.price_som)} добавлена.`)

      // Сброс под следующий ввод; счёт оставляем для скорости.
      setClientCode('')
      setWeight('')
      setDirectAmount('')
      setPlaces('1')
      setQuote(null)
      codeRef.current?.focus()
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setSaving(false)
    }
  }

  if (accountsReq.loading) return <LoadingTruck />

  // Нет ни одного счёта Express — добавлять продажу некуда.
  if (!accounts.length) {
    return (
      <div className="operator-card card">
        <div className="operator-card-head">
          <h2 className="card-title">Новая продажа</h2>
        </div>
        <Alert kind="error">
          Нет доступного счёта Express для зачисления. Обратитесь к администратору.
        </Alert>
      </div>
    )
  }

  return (
    <div className="operator-card card">
      <div className="operator-card-head">
        <h2 className="card-title">Новая продажа</h2>
        <p className="muted">
          Заполните данные продажи — она попадёт в Loko Express. Дата: сегодня, {dateRu(today())}.
        </p>
      </div>

      {error && <Alert kind="error">{error}</Alert>}
      {success && <Alert kind="success">{success}</Alert>}

      <form onSubmit={submit} className="col">
        <div className="field">
          <span className="field-label">Режим суммы</span>
          <Segmented value={mode} onChange={setMode} options={MODES} />
        </div>

        <Field label="Код клиента" hint="Номер или код клиента/товара">
          <input
            ref={codeRef}
            className="input"
            value={clientCode}
            onChange={(e) => setClientCode(e.target.value)}
            placeholder="29520"
            required
            autoFocus
          />
        </Field>

        {mode === 'WEIGHT' ? (
          <>
            <div className="row row-wrap">
              <Field label="Вес одного места, кг" hint="Умножается на количество мест">
                <input
                  className="input"
                  type="number"
                  step="0.001"
                  min="0"
                  value={weight}
                  onChange={(e) => setWeight(e.target.value)}
                  placeholder="5"
                />
              </Field>
              <Field label="Кол-во мест" hint="Напр. 2 коробки">
                <input
                  className="input"
                  type="number"
                  min="1"
                  value={places}
                  onChange={(e) => setPlaces(e.target.value)}
                  onBlur={() => setPlaces(String(Math.max(1, parseInt(places, 10) || 1)))}
                />
              </Field>
            </div>
            {totalWeight > 0 && (
              <div className="caption">
                Итого вес: <strong>{kg(totalWeight)}</strong> ({perPlace} кг × {placesN} мест)
              </div>
            )}
          </>
        ) : (
          <div className="row row-wrap">
            <Field label="Сумма, сом" hint="Вводится напрямую">
              <input
                className="input"
                type="number"
                step="0.01"
                min="0"
                value={directAmount}
                onChange={(e) => setDirectAmount(e.target.value)}
                placeholder="5000"
                required
              />
            </Field>
            <Field label="Вес (расчётный), кг" hint="Считается из суммы — изменить нельзя">
              <input
                className="input input-readonly"
                value={derivedWeight > 0 ? derivedWeight.toFixed(3) : ''}
                placeholder="—"
                readOnly
                tabIndex={-1}
              />
            </Field>
          </div>
        )}

        <Field label="Счёт зачисления (нал/безнал)">
          <select
            className="select"
            value={accountId}
            onChange={(e) => setAccountId(e.target.value)}
            required
          >
            {accounts.map((a) => (
              <option key={a.id} value={a.id}>
                {a.name} ({a.kind === 'CASH' ? 'наличные' : 'безнал'})
              </option>
            ))}
          </select>
        </Field>

        <div className="card card-soft operator-total">
          <span className="operator-total-label">Общая стоимость</span>
          <span className="operator-total-value">{som(total)}</span>
        </div>

        <button className="btn btn-primary btn-block" disabled={saving} type="submit">
          <IconPlus size={18} /> {saving ? 'Добавление…' : 'Добавить продажу'}
        </button>
      </form>
    </div>
  )
}
