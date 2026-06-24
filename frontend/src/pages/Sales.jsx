import { useEffect, useState } from 'react'
import api, { errorMessage } from '../api/client'
import { useFetch, asList } from '../lib/hooks'
import { firstOfMonth, today, som, kg, dateRu, signClass } from '../lib/format'
import { Alert, Badge, EmptyState, Field, Modal, Segmented, Spinner, Stat } from '../components/ui'
import { IconPlus } from '../components/icons'

const PAYMENTS = [
  { value: 'all', label: 'Все' },
  { value: 'cash', label: 'Наличные' },
  { value: 'noncash', label: 'Безнал' },
]
const MODES = [
  { value: 'WEIGHT', label: 'По весу' },
  { value: 'DIRECT', label: 'Прямая сумма' },
]

export default function Sales() {
  const [from, setFrom] = useState(firstOfMonth())
  const [to, setTo] = useState(today())
  const [payment, setPayment] = useState('all')
  const [search, setSearch] = useState('')
  const [showForm, setShowForm] = useState(false)

  const params = { from, to, payment, search: search || undefined, page_size: 10000 }
  const sales = useFetch('/sales/', params)
  const summary = useFetch('/sales/summary/', params)
  const accounts = useFetch('/accounts/', { module: 'EXPRESS' })

  const rows = asList(sales.data)
  const total = sales.data?.count ?? rows.length
  const s = summary.data || {}

  function refresh() {
    sales.reload()
    summary.reload()
  }

  return (
    <>
      <div className="grid">
        <Stat label="Продаж за период" value={s.count || 0} sub={kg(s.weight)} />
        <Stat label="Начислено (выручка)" value={som(s.revenue)} />
        <Stat label="Оплачено" value={som(s.paid)} sub="фактический приток" />
        <Stat label="Дебиторка" value={som(s.receivable)} tone={signClass(s.receivable)} sub="не оплачено" />
        <Stat label="Маржа" value={som(s.margin)} tone={signClass(s.margin)} />
      </div>

      <div className="card">
        <div className="card-header">
          <div className="toolbar grow">
            <Field label="С даты">
              <input className="input" type="date" value={from} onChange={(e) => setFrom(e.target.value)} />
            </Field>
            <Field label="По дату">
              <input className="input" type="date" value={to} onChange={(e) => setTo(e.target.value)} />
            </Field>
            <Field label="Поиск по коду">
              <input className="input" placeholder="код клиента" value={search} onChange={(e) => setSearch(e.target.value)} />
            </Field>
            <div className="field">
              <span className="field-label">Оплата</span>
              <Segmented value={payment} onChange={setPayment} options={PAYMENTS} />
            </div>
          </div>
          <button className="btn btn-primary" onClick={() => setShowForm(true)}>
            <IconPlus size={18} /> Новая продажа
          </button>
        </div>

        {!sales.loading && rows.length > 0 && (
          <div className="caption" style={{ marginBottom: 8 }}>Показано {rows.length} из {total} продаж</div>
        )}
        {sales.loading ? (
          <Spinner />
        ) : rows.length === 0 ? (
          <EmptyState>Продаж за выбранный период нет.</EmptyState>
        ) : (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>Дата</th>
                  <th>Код клиента</th>
                  <th className="num">Вес</th>
                  <th>Счёт</th>
                  <th className="num">Начислено</th>
                  <th className="num">Оплачено</th>
                  <th className="num">Дебиторка</th>
                  <th className="num">Маржа</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.id}>
                    <td>{dateRu(r.date)}</td>
                    <td><strong>{r.client_code}</strong></td>
                    <td className="num">{r.weight_kg ? kg(r.weight_kg) : '—'}</td>
                    <td>
                      <Badge variant={r.is_cash ? 'badge-cash' : 'badge-bank'}>{r.account_name}</Badge>
                    </td>
                    <td className="num">{som(r.price_som)}</td>
                    <td className="num">{som(r.paid_som)}</td>
                    <td className={`num ${signClass(r.receivable_som)}`}>{som(r.receivable_som)}</td>
                    <td className={`num ${signClass(r.margin_som)}`}>{som(r.margin_som)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {showForm && (
        <SaleForm
          accounts={asList(accounts.data)}
          onClose={() => setShowForm(false)}
          onSaved={() => {
            setShowForm(false)
            refresh()
          }}
        />
      )}
    </>
  )
}

function SaleForm({ accounts, onClose, onSaved }) {
  const [mode, setMode] = useState('WEIGHT')
  const [clientCode, setClientCode] = useState('')
  const [weight, setWeight] = useState('')
  const [directAmount, setDirectAmount] = useState('')
  const [places, setPlaces] = useState('1')
  const [accountId, setAccountId] = useState(accounts[0]?.id || '')
  const [date, setDate] = useState(today())
  const [paid, setPaid] = useState('')
  const [paymentDate, setPaymentDate] = useState('')
  const [quote, setQuote] = useState(null)
  const [error, setError] = useState('')
  const [saving, setSaving] = useState(false)

  // Live preview for WEIGHT mode.
  useEffect(() => {
    if (mode !== 'WEIGHT') return
    const w = parseFloat(weight)
    if (!w || w <= 0) {
      setQuote(null)
      return
    }
    let active = true
    const t = setTimeout(() => {
      api.post('/sales/quote/', { weight_kg: weight }).then((res) => active && setQuote(res.data)).catch(() => active && setQuote(null))
    }, 250)
    return () => {
      active = false
      clearTimeout(t)
    }
  }, [weight, mode])

  // Accrued amount (начисление) used as the default "оплачено".
  const accrual = mode === 'WEIGHT' ? Number(quote?.price_som || 0) : Number(directAmount || 0)
  const paidValue = paid === '' ? accrual : Number(paid)
  const receivable = accrual - paidValue

  async function submit(e) {
    e.preventDefault()
    setError('')
    setSaving(true)
    try {
      const body = {
        amount_mode: mode,
        client_code: clientCode.trim(),
        places: Number(places) || 1,
        account: accountId,
        date,
        payment_date: paymentDate || date,
      }
      if (mode === 'WEIGHT') body.weight_kg = weight
      else body.price_som = directAmount
      if (paid !== '') body.paid_som = paid
      await api.post('/sales/', body)
      onSaved()
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setSaving(false)
    }
  }

  return (
    <Modal
      title="Новая продажа"
      onClose={onClose}
      footer={
        <>
          <button className="btn btn-secondary" onClick={onClose}>Отмена</button>
          <button className="btn btn-primary" onClick={submit} disabled={saving}>
            {saving ? 'Сохранение…' : 'Создать продажу'}
          </button>
        </>
      }
    >
      <form onSubmit={submit} className="col">
        {error && <Alert kind="error">{error}</Alert>}

        <div className="field">
          <span className="field-label">Режим суммы</span>
          <Segmented value={mode} onChange={setMode} options={MODES} />
        </div>

        <Field label="Код клиента" hint="Номер или код клиента/товара">
          <input className="input" value={clientCode} onChange={(e) => setClientCode(e.target.value)} placeholder="29520" required autoFocus />
        </Field>

        {mode === 'WEIGHT' ? (
          <div className="row row-wrap">
            <Field label="Вес, кг" hint="Можно дробный: 0.80, 0.53">
              <input className="input" type="number" step="0.001" min="0" value={weight} onChange={(e) => setWeight(e.target.value)} placeholder="0.80" required />
            </Field>
            <Field label="Кол-во мест">
              <input className="input" type="number" min="1" value={places} onChange={(e) => setPlaces(e.target.value)} />
            </Field>
          </div>
        ) : (
          <div className="row row-wrap">
            <Field label="Сумма начисления, сом" hint="Вводится напрямую">
              <input className="input" type="number" step="0.01" min="0" value={directAmount} onChange={(e) => setDirectAmount(e.target.value)} placeholder="5000" required />
            </Field>
            <Field label="Кол-во мест">
              <input className="input" type="number" min="1" value={places} onChange={(e) => setPlaces(e.target.value)} />
            </Field>
          </div>
        )}

        <div className="row row-wrap">
          <Field label="Счёт зачисления (нал/безнал)">
            <select className="select" value={accountId} onChange={(e) => setAccountId(e.target.value)} required>
              {accounts.map((a) => (
                <option key={a.id} value={a.id}>{a.name} ({a.kind === 'CASH' ? 'наличные' : 'безнал'})</option>
              ))}
            </select>
          </Field>
          <Field label="Дата операции (ОПиУ)">
            <input className="input" type="date" value={date} onChange={(e) => setDate(e.target.value)} required />
          </Field>
        </div>

        <div className="row row-wrap">
          <Field label="Оплачено, сом" hint="Пусто = оплачено полностью">
            <input className="input" type="number" step="0.01" min="0" value={paid} onChange={(e) => setPaid(e.target.value)} placeholder={accrual ? String(accrual) : '0.00'} />
          </Field>
          <Field label="Дата оплаты (ОДДС)" hint="Пусто = дата операции">
            <input className="input" type="date" value={paymentDate} onChange={(e) => setPaymentDate(e.target.value)} />
          </Field>
        </div>

        <div className="card card-soft" style={{ padding: 16 }}>
          <div className="caption" style={{ marginBottom: 8 }}>
            Расчёт {mode === 'WEIGHT' ? '(3$/кг · курс 90 · динамическая себестоимость)' : '(прямая сумма)'}
          </div>
          <div className="row row-wrap">
            <Stat label="Начислено" value={som(accrual)} />
            <Stat label="Оплачено" value={som(paidValue)} />
            <Stat label="Дебиторка" value={som(receivable)} tone={signClass(receivable)} />
            {mode === 'WEIGHT' && <Stat label="Маржа" value={som(quote?.margin_som)} tone={signClass(quote?.margin_som)} />}
          </div>
        </div>
      </form>
    </Modal>
  )
}
