import { useEffect, useState } from 'react'
import api, { errorMessage } from '../api/client'
import { useFetch, asList } from '../lib/hooks'
import { firstOfMonth, today, som, kg, dateRu, signClass } from '../lib/format'
import { Alert, Badge, EmptyState, Field, Modal, Segmented, Spinner, Stat } from '../components/ui'
import { IconPlus, IconEdit, IconTrash } from '../components/icons'

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
  const [form, setForm] = useState(null) // null=закрыто, 'new', или объект продажи (редактирование)
  const [busyId, setBusyId] = useState(null)
  const [error, setError] = useState('')
  const [editCell, setEditCell] = useState(null) // inline-правка суммы в таблице: {id, value}
  const [savingCell, setSavingCell] = useState(false)

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

  async function remove(r) {
    if (!window.confirm(`Удалить продажу «${r.client_code}» на ${som(r.price_som)}?`)) return
    setBusyId(r.id)
    setError('')
    try {
      await api.delete(`/sales/${r.id}/`)
      refresh()
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setBusyId(null)
    }
  }

  // Двойной клик по «Оплачено» → быстрая правка суммы прямо в таблице.
  // Express: оплата = цена, поэтому ставим ручную сумму (режим «прямая сумма»),
  // оплата приравнивается к начислению (paid_som=null → бэкенд подставит цену).
  async function saveCell(r) {
    const raw = editCell?.value
    if (raw === '' || raw == null || Number(raw) < 0 || Number(raw) === Number(r.price_som)) {
      setEditCell(null)
      return
    }
    setSavingCell(true)
    setError('')
    try {
      await api.patch(`/sales/${r.id}/`, {
        amount_mode: 'DIRECT', price_som: raw, paid_som: null, cost_is_manual: false,
      })
      setEditCell(null)
      refresh()
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setSavingCell(false)
    }
  }

  return (
    <>
      {error && <Alert kind="error">{error}</Alert>}
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
          <button className="btn btn-primary" onClick={() => setForm('new')}>
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
                  <th></th>
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
                    <td
                      className="num cell-edit"
                      onDoubleClick={() => setEditCell({ id: r.id, value: String(r.price_som ?? '') })}
                      title="Двойной клик — изменить сумму"
                    >
                      {editCell?.id === r.id ? (
                        <input
                          className="input input-cell"
                          type="number"
                          step="0.01"
                          min="0"
                          autoFocus
                          disabled={savingCell}
                          value={editCell.value}
                          onChange={(e) => setEditCell({ id: r.id, value: e.target.value })}
                          onKeyDown={(e) => {
                            if (e.key === 'Enter') saveCell(r)
                            if (e.key === 'Escape') setEditCell(null)
                          }}
                          onBlur={() => saveCell(r)}
                        />
                      ) : (
                        som(r.paid_som)
                      )}
                    </td>
                    <td className={`num ${signClass(r.receivable_som)}`}>{som(r.receivable_som)}</td>
                    <td className={`num ${signClass(r.margin_som)}`}>{som(r.margin_som)}</td>
                    <td className="num">
                      <div className="row gap-sm" style={{ justifyContent: 'flex-end' }}>
                        <button className="btn btn-icon btn-ghost btn-sm" title="Изменить" onClick={() => setForm(r)}>
                          <IconEdit size={16} />
                        </button>
                        <button className="btn btn-icon btn-danger btn-sm" title="Удалить" disabled={busyId === r.id} onClick={() => remove(r)}>
                          <IconTrash size={16} />
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {form && (
        <SaleForm
          editing={form === 'new' ? null : form}
          accounts={asList(accounts.data)}
          onClose={() => setForm(null)}
          onSaved={() => {
            setForm(null)
            refresh()
          }}
        />
      )}
    </>
  )
}

function SaleForm({ editing, accounts, onClose, onSaved }) {
  const isEdit = !!editing
  const [mode, setMode] = useState(editing?.amount_mode || 'WEIGHT')
  const [clientCode, setClientCode] = useState(editing?.client_code || '')
  const [weight, setWeight] = useState(editing?.weight_kg || '')
  const [directAmount, setDirectAmount] = useState(isEdit && editing.amount_mode === 'DIRECT' ? editing.price_som : '')
  const [places, setPlaces] = useState(String(editing?.places || '1'))
  const [accountId, setAccountId] = useState(editing?.account || accounts[0]?.id || '')
  const [date, setDate] = useState(editing?.date || today())
  const [quote, setQuote] = useState(null)
  const [perKgRate, setPerKgRate] = useState(0) // цена 1 кг (сом) — для пересчёта суммы → вес
  const [costPerKg, setCostPerKg] = useState(0) // себестоимость 1 кг (сом) — для расчёта в «прямой сумме»
  const [error, setError] = useState('')
  const [saving, setSaving] = useState(false)

  // Ставки за 1 кг (цена и себестоимость) — для режима «прямая сумма»:
  // вес = сумма ÷ цена-за-кг, себестоимость = вес × себест-за-кг.
  useEffect(() => {
    api
      .post('/sales/quote/', { weight_kg: 1 })
      .then((res) => {
        setPerKgRate(Number(res.data.price_som) || 0)
        setCostPerKg(Number(res.data.cost_per_kg_som) || 0)
      })
      .catch(() => {
        setPerKgRate(0)
        setCostPerKg(0)
      })
  }, [])

  // Live preview for WEIGHT mode (цена зависит от веса).
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

  const accrual = mode === 'WEIGHT' ? Number(quote?.price_som || 0) : Number(directAmount || 0)
  // «Прямая сумма»: расчётный вес (только показ, не редактируется) = сумма ÷ ставка за кг.
  const directDerivedWeight =
    perKgRate > 0 && Number(directAmount) > 0 ? Number(directAmount) / perKgRate : 0
  // Себестоимость — динамическая, от веса по ставке из Настроек (см. AppSettings).
  // В «прямой сумме» — от расчётного веса (сумма ÷ цена-за-кг) × себестоимость-за-кг.
  const autoCost =
    mode === 'WEIGHT' ? Number(quote?.cost_som || 0) : directDerivedWeight * costPerKg
  const margin = accrual - autoCost

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
        cost_is_manual: false, // себестоимость всегда автоматическая (ставка из Настроек)
      }
      if (mode === 'WEIGHT') body.weight_kg = weight || null
      else body.price_som = directAmount
      // Express: оплата всегда полная в день операции (начислено = оплачено).
      body.paid_som = null
      body.payment_date = null
      if (isEdit) await api.patch(`/sales/${editing.id}/`, body)
      else await api.post('/sales/', body)
      onSaved()
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setSaving(false)
    }
  }

  return (
    <Modal
      title={isEdit ? `Продажа · ${editing.client_code}` : 'Новая продажа'}
      onClose={onClose}
      footer={
        <>
          <button className="btn btn-secondary" onClick={onClose}>Отмена</button>
          <button className="btn btn-primary" onClick={submit} disabled={saving}>
            {saving ? 'Сохранение…' : isEdit ? 'Сохранить' : 'Создать продажу'}
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
            <Field label="Вес, кг" hint="Необязателен. Цена и себестоимость — от веса">
              <input className="input" type="number" step="0.001" min="0" value={weight} onChange={(e) => setWeight(e.target.value)} placeholder="0.80" />
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
            <Field label="Вес (расчётный), кг" hint="Из суммы — изменить нельзя">
              <input
                className="input input-readonly"
                value={directDerivedWeight > 0 ? directDerivedWeight.toFixed(3) : ''}
                placeholder="—"
                readOnly
                tabIndex={-1}
              />
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
          <Field label="Дата операции">
            <input className="input" type="date" value={date} onChange={(e) => setDate(e.target.value)} required />
          </Field>
        </div>

        <div className="card card-soft sale-preview">
          <div className="caption">Расчёт · {mode === 'WEIGHT' ? 'по весу' : 'прямая сумма'}</div>
          <div className="preview-grid">
            <div className="preview-cell">
              <span className="preview-label">Начислено</span>
              <span className="preview-value">{som(accrual)}</span>
            </div>
            <div className="preview-cell">
              <span className="preview-label">Себестоимость</span>
              <span className="preview-value">{som(autoCost)}</span>
            </div>
            <div className="preview-cell">
              <span className="preview-label">Маржа</span>
              <span className={`preview-value ${signClass(margin)}`}>{som(margin)}</span>
            </div>
          </div>
        </div>
      </form>
    </Modal>
  )
}
