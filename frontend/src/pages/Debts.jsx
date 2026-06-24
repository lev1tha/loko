import { useState } from 'react'
import api, { errorMessage } from '../api/client'
import { useFetch, asList } from '../lib/hooks'
import { today, money, dateRu, signClass } from '../lib/format'
import { Alert, Badge, EmptyState, Field, Modal, Spinner, Stat } from '../components/ui'
import { IconPlus } from '../components/icons'

export default function Debts() {
  const [kind, setKind] = useState('')
  const [showForm, setShowForm] = useState(false)
  const [busyId, setBusyId] = useState(null)

  const debts = useFetch('/debts/', { status: 'OPEN', kind: kind || undefined, page_size: 10000 })
  const summary = useFetch('/reports/debts/')
  const rows = asList(debts.data)
  const s = summary.data || {}

  async function close(id) {
    setBusyId(id)
    try {
      await api.post(`/debts/${id}/close/`)
      debts.reload()
      summary.reload()
    } finally {
      setBusyId(null)
    }
  }

  return (
    <>
      <div className="grid">
        <Stat label="Дебиторская (нам должны)" value={money(s.receivable)} tone="pos" sub={`Business ${money(s.business_receivable)} · Express ${money(s.express_receivable)}`} />
        <Stat label="Кредиторская (мы должны)" value={money(s.payable)} tone="neg" sub={`Business ${money(s.business_payable)} · Express ${money(s.express_payable)}`} />
        <Stat label="Сальдо (нам − мы)" value={money(s.net)} tone={signClass(s.net)} sub="дебиторка − кредиторка" />
      </div>

      <div className="card">
        <div className="card-header">
          <div className="toolbar grow">
            <Field label="Тип">
              <select className="select" value={kind} onChange={(e) => setKind(e.target.value)}>
                <option value="">Все</option>
                <option value="PAYABLE">Кредиторская</option>
                <option value="RECEIVABLE">Дебиторская</option>
              </select>
            </Field>
          </div>
          <button className="btn btn-primary" onClick={() => setShowForm(true)}>
            <IconPlus size={18} /> Новая задолженность
          </button>
        </div>

        {debts.loading ? (
          <Spinner />
        ) : rows.length === 0 ? (
          <EmptyState>Открытых задолженностей нет.</EmptyState>
        ) : (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>Дата</th>
                  <th>Тип</th>
                  <th>Контрагент</th>
                  <th className="num">Сумма</th>
                  <th>Комментарий</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {rows.map((d) => (
                  <tr key={d.id}>
                    <td>{dateRu(d.date)}</td>
                    <td>
                      <Badge variant={d.kind === 'PAYABLE' ? 'badge-danger' : 'badge-success'}>
                        {d.kind === 'PAYABLE' ? 'Кредиторская' : 'Дебиторская'}
                      </Badge>
                    </td>
                    <td><strong>{d.counterparty}</strong></td>
                    <td className="num">{money(d.amount, d.currency)}</td>
                    <td className="muted">{d.note || '—'}</td>
                    <td className="num">
                      <button className="btn btn-secondary btn-sm" disabled={busyId === d.id} onClick={() => close(d.id)}>
                        Погасить
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {showForm && (
        <DebtForm
          onClose={() => setShowForm(false)}
          onSaved={() => {
            setShowForm(false)
            debts.reload()
            summary.reload()
          }}
        />
      )}
    </>
  )
}

function DebtForm({ onClose, onSaved }) {
  const [kind, setKind] = useState('PAYABLE')
  const [counterparty, setCounterparty] = useState('')
  const [amount, setAmount] = useState('')
  const [currency, setCurrency] = useState('CNY')
  const [note, setNote] = useState('')
  const [date, setDate] = useState(today())
  const [error, setError] = useState('')
  const [saving, setSaving] = useState(false)

  async function submit(e) {
    e.preventDefault()
    setError('')
    setSaving(true)
    try {
      await api.post('/debts/', {
        kind,
        counterparty: counterparty.trim(),
        amount,
        currency,
        note: note.trim(),
        date,
      })
      onSaved()
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setSaving(false)
    }
  }

  return (
    <Modal
      title="Новая задолженность"
      onClose={onClose}
      footer={
        <>
          <button className="btn btn-secondary" onClick={onClose}>Отмена</button>
          <button className="btn btn-primary" onClick={submit} disabled={saving}>
            {saving ? 'Сохранение…' : 'Добавить'}
          </button>
        </>
      }
    >
      <form onSubmit={submit} className="col">
        {error && <Alert kind="error">{error}</Alert>}
        <Field label="Тип задолженности">
          <select className="select" value={kind} onChange={(e) => setKind(e.target.value)}>
            <option value="PAYABLE">Кредиторская (мы должны)</option>
            <option value="RECEIVABLE">Дебиторская (нам должны)</option>
          </select>
        </Field>
        <Field label="Контрагент">
          <input className="input" value={counterparty} onChange={(e) => setCounterparty(e.target.value)} placeholder="Поставщик / клиент" required autoFocus />
        </Field>
        <div className="row row-wrap">
          <Field label="Сумма">
            <input className="input" type="number" step="0.01" min="0" value={amount} onChange={(e) => setAmount(e.target.value)} placeholder="0.00" required />
          </Field>
          <Field label="Валюта">
            <select className="select" value={currency} onChange={(e) => setCurrency(e.target.value)}>
              <option value="CNY">Юань (CNY)</option>
              <option value="KGS">Сом (KGS)</option>
            </select>
          </Field>
        </div>
        <div className="row row-wrap">
          <Field label="Дата">
            <input className="input" type="date" value={date} onChange={(e) => setDate(e.target.value)} required />
          </Field>
          <Field label="Комментарий">
            <input className="input" value={note} onChange={(e) => setNote(e.target.value)} />
          </Field>
        </div>
      </form>
    </Modal>
  )
}
