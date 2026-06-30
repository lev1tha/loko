import { useEffect, useRef, useState } from 'react'
import api, { errorMessage } from '../api/client'
import { useFetch, asList } from '../lib/hooks'
import { today, som, kg, dateRu } from '../lib/format'
import { Alert, Field, Modal, Segmented } from '../components/ui'
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
  // «МБанк» исключён из выбора счёта на странице сотрудника (по требованию).
  const accounts = asList(accountsReq.data).filter(
    (a) => !/mbank|мбанк/i.test(a.name || ''),
  )

  const [mode, setMode] = useState('DIRECT')
  const [clientCode, setClientCode] = useState('')
  const [weight, setWeight] = useState('')
  const [directAmount, setDirectAmount] = useState('')
  const [places, setPlaces] = useState('1')
  const [accountId, setAccountId] = useState('')
  const [quote, setQuote] = useState(null)
  const [rate, setRate] = useState(0) // стоимость 1 кг (сом) — для пересчёта суммы → вес
  const [uniquePrice, setUniquePrice] = useState('') // активная уникальная цена за кг (сом)
  const [uniqueDraft, setUniqueDraft] = useState('') // значение в модалке до «Применить»
  const [showUnique, setShowUnique] = useState(false)
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')
  const [saving, setSaving] = useState(false)
  const codeRef = useRef(null)

  // Вес груза (режим «по весу»). «Количество» — отдельный учётный показатель и
  // НЕ влияет на цену: вес на количество НЕ умножается.
  const weightNum = parseFloat(weight) || 0
  const placesN = parseInt(places, 10) || 1

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
    if (!(weightNum > 0)) {
      setQuote(null)
      return
    }
    let active = true
    const t = setTimeout(() => {
      // client_code — чтобы итог посчитался по спец-цене клиента (если задана).
      // Саму цену сотрудник не видит, только «Общую стоимость».
      api
        .post('/sales/quote/', { weight_kg: weightNum, client_code: clientCode.trim() })
        .then((res) => active && setQuote(res.data))
        .catch(() => active && setQuote(null))
    }, 250)
    return () => {
      active = false
      clearTimeout(t)
    }
  }, [weightNum, mode, clientCode])

  const directNum = parseFloat(directAmount) || 0
  // Расчётный вес для «прямой суммы» — только показ, не редактируется (2 знака).
  const derivedWeight = rate > 0 && directNum > 0 ? Number((directNum / rate).toFixed(2)) : 0
  // Уникальная цена за кг: вес НЕ меняется, меняется цена за вес → пересчёт стоимости.
  const uniqueNum = parseFloat(uniquePrice) || 0
  const hasUnique = uniqueNum > 0
  // Вес-основа: «по весу» — итоговый вес; «прямая сумма» — расчётный вес из суммы.
  const baseWeight = mode === 'WEIGHT' ? weightNum : derivedWeight
  // Общая стоимость: с уникальной ценой = вес × цена; иначе по весу из расчёта / введённая сумма.
  const total = hasUnique && baseWeight > 0
    ? Number((baseWeight * uniqueNum).toFixed(2))
    : mode === 'WEIGHT' ? Number(quote?.price_som || 0) : directNum

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
    if (mode === 'WEIGHT' && !(weightNum > 0)) {
      setError('Укажите вес больше нуля.')
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
      if (hasUnique && baseWeight > 0) {
        // Уникальная цена: вес сохраняем как есть, стоимость = вес × цена за кг.
        body.amount_mode = 'DIRECT'
        body.price_som = (baseWeight * uniqueNum).toFixed(2)
        body.weight_kg = baseWeight
      } else if (mode === 'WEIGHT') {
        // Вес груза (количество на вес/цену не влияет).
        body.weight_kg = weightNum > 0 ? weightNum : null
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
      setUniquePrice('')
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
          <Field label="Вес, кг" hint="Итоговый вес груза">
            <input
              className="input"
              type="number"
              step="0.01"
              min="0"
              value={weight}
              onChange={(e) => setWeight(e.target.value)}
              placeholder="5"
            />
          </Field>
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
                value={derivedWeight > 0 ? derivedWeight.toFixed(2) : ''}
                placeholder="—"
                readOnly
                tabIndex={-1}
              />
            </Field>
          </div>
        )}

        <Field label="Количество" hint="Для учёта — на цену не влияет">
          <input
            className="input"
            type="number"
            min="1"
            value={places}
            onChange={(e) => setPlaces(e.target.value)}
            onBlur={() => setPlaces(String(Math.max(1, parseInt(places, 10) || 1)))}
          />
        </Field>

        <div className="field">
          <button
            type="button"
            className={`btn btn-block ${hasUnique ? 'btn-primary' : 'btn-secondary'}`}
            onClick={() => { setUniqueDraft(uniquePrice); setShowUnique(true) }}
          >
            {hasUnique ? `Уникальная цена: ${uniqueNum} сом/кг` : 'Уникальная цена'}
          </button>
          {hasUnique && baseWeight > 0 && (
            <span className="field-hint">
              Вес {kg(baseWeight)} не меняется · цена {uniqueNum} сом/кг → {som(total)}
            </span>
          )}
        </div>

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

      {showUnique && (
        <Modal
          title="Уникальная цена за кг"
          onClose={() => setShowUnique(false)}
          footer={
            <>
              {hasUnique && (
                <button className="btn btn-secondary" onClick={() => { setUniquePrice(''); setShowUnique(false) }}>
                  Сбросить
                </button>
              )}
              <button className="btn btn-secondary" onClick={() => setShowUnique(false)}>Отмена</button>
              <button className="btn btn-primary" onClick={() => { setUniquePrice(uniqueDraft); setShowUnique(false) }}>
                Применить
              </button>
            </>
          }
        >
          <p className="caption" style={{ margin: 0, lineHeight: 1.5 }}>
            Задайте цену за 1 кг для этого клиента. Вес не изменится — пересчитается общая стоимость.
          </p>
          <Field label="Цена за 1 кг, сом">
            <input
              className="input"
              type="number"
              step="0.01"
              min="0"
              value={uniqueDraft}
              onChange={(e) => setUniqueDraft(e.target.value)}
              placeholder="250"
              autoFocus
            />
          </Field>
          {baseWeight > 0 ? (
            Number(uniqueDraft) > 0 && (
              <div className="caption">
                Итог: {kg(baseWeight)} × {Number(uniqueDraft)} сом = <strong>{som(baseWeight * Number(uniqueDraft))}</strong>
              </div>
            )
          ) : (
            <Alert kind="error">
              Сначала укажите {mode === 'WEIGHT' ? 'вес' : 'сумму'} — от него считается стоимость.
            </Alert>
          )}
        </Modal>
      )}
    </div>
  )
}
