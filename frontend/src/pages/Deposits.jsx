import { useState } from 'react'
import api, { errorMessage } from '../api/client'
import { useFetch, asList } from '../lib/hooks'
import { firstOfMonth, today, money, dateRu } from '../lib/format'
import { Alert, Badge, EmptyState, Field, Modal, Spinner } from '../components/ui'
import { IconPlus } from '../components/icons'

const STATUS_VARIANT = {
  HELD: 'badge-manager',
  RECOGNIZED: 'badge-success',
  SENT_SUPPLIER: 'badge-admin',
}

export default function Deposits() {
  const [from, setFrom] = useState(firstOfMonth())
  const [to, setTo] = useState(today())
  const [status, setStatus] = useState('')
  const [showForm, setShowForm] = useState(false)
  const [busyId, setBusyId] = useState(null)
  const [error, setError] = useState('')

  const deposits = useFetch('/deposits/', { from, to, status: status || undefined, page_size: 10000 })
  const businessAccounts = useFetch('/accounts/', { module: 'BUSINESS' })
  const rows = asList(deposits.data)

  async function act(id, action) {
    setBusyId(id)
    setError('')
    try {
      await api.post(`/deposits/${id}/${action}/`, { date: today() })
      deposits.reload()
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setBusyId(null)
    }
  }

  return (
    <>
      {error && <Alert kind="error">{error}</Alert>}
      <div className="card card-soft">
        <p className="muted" style={{ margin: 0 }}>
          Принятые депозиты <strong>не</strong> формируются как выручка автоматически. Нажмите
          «Признать», чтобы учесть депозит в выручке (ООПИУ), или «Поставщику» — чтобы отправить
          как предоплату (создаётся расход «Оплата поставщикам»).
        </p>
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
            <Field label="Статус">
              <select className="select" value={status} onChange={(e) => setStatus(e.target.value)}>
                <option value="">Все</option>
                <option value="HELD">Принят (не признан)</option>
                <option value="RECOGNIZED">Признан как выручка</option>
                <option value="SENT_SUPPLIER">Отправлен поставщику</option>
              </select>
            </Field>
          </div>
          <button className="btn btn-primary" onClick={() => setShowForm(true)}>
            <IconPlus size={18} /> Новый депозит
          </button>
        </div>

        {deposits.loading ? (
          <Spinner />
        ) : rows.length === 0 ? (
          <EmptyState>Депозитов за период нет.</EmptyState>
        ) : (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>Дата</th>
                  <th>Источник</th>
                  <th>Счёт</th>
                  <th className="num">Сумма</th>
                  <th>Статус</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {rows.map((d) => (
                  <tr key={d.id}>
                    <td>{dateRu(d.date)}</td>
                    <td><strong>{d.source}</strong></td>
                    <td>{d.account_name}</td>
                    <td className="num">{money(d.amount, d.currency)}</td>
                    <td><Badge variant={STATUS_VARIANT[d.status]}>{d.status_display}</Badge></td>
                    <td className="num">
                      {d.status === 'HELD' && (
                        <div className="row gap-sm" style={{ justifyContent: 'flex-end' }}>
                          <button className="btn btn-secondary btn-sm" disabled={busyId === d.id} onClick={() => act(d.id, 'recognize')}>
                            Признать
                          </button>
                          <button className="btn btn-ghost btn-sm" disabled={busyId === d.id} onClick={() => act(d.id, 'send-to-supplier')}>
                            Поставщику
                          </button>
                        </div>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {showForm && (
        <DepositForm
          accounts={asList(businessAccounts.data)}
          onClose={() => setShowForm(false)}
          onSaved={() => {
            setShowForm(false)
            deposits.reload()
          }}
        />
      )}
    </>
  )
}

function DepositForm({ accounts, onClose, onSaved }) {
  const [source, setSource] = useState('')
  const [accountId, setAccountId] = useState(accounts[0]?.id || '')
  const [amount, setAmount] = useState('')
  const [note, setNote] = useState('')
  const [date, setDate] = useState(today())
  const [error, setError] = useState('')
  const [saving, setSaving] = useState(false)

  const acc = accounts.find((a) => String(a.id) === String(accountId))

  async function submit(e) {
    e.preventDefault()
    setError('')
    setSaving(true)
    try {
      await api.post('/deposits/', {
        source: source.trim(),
        account: accountId,
        amount,
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
      title="Новый депозит"
      onClose={onClose}
      footer={
        <>
          <button className="btn btn-secondary" onClick={onClose}>Отмена</button>
          <button className="btn btn-primary" onClick={submit} disabled={saving}>
            {saving ? 'Сохранение…' : 'Принять депозит'}
          </button>
        </>
      }
    >
      <form onSubmit={submit} className="col">
        {error && <Alert kind="error">{error}</Alert>}
        <Field label="Источник / клиент">
          <input className="input" value={source} onChange={(e) => setSource(e.target.value)} placeholder="Клиент / контрагент" required autoFocus />
        </Field>
        <Field label="Счёт зачисления" hint={acc ? `Валюта: ${acc.currency}` : 'Счета Loko Business'}>
          <select className="select" value={accountId} onChange={(e) => setAccountId(e.target.value)} required>
            {accounts.map((a) => <option key={a.id} value={a.id}>{a.name} · {a.currency}</option>)}
          </select>
        </Field>
        <div className="row row-wrap">
          <Field label={`Сумма${acc ? ', ' + acc.currency : ''}`}>
            <input className="input" type="number" step="0.01" min="0" value={amount} onChange={(e) => setAmount(e.target.value)} placeholder="0.00" required />
          </Field>
          <Field label="Дата">
            <input className="input" type="date" value={date} onChange={(e) => setDate(e.target.value)} required />
          </Field>
        </div>
        <Field label="Комментарий">
          <input className="input" value={note} onChange={(e) => setNote(e.target.value)} />
        </Field>
      </form>
    </Modal>
  )
}
