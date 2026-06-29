import { useState } from 'react'
import api, { errorMessage } from '../api/client'
import { useFetch, asList } from '../lib/hooks'
import { firstOfMonth, today, money, dateRu } from '../lib/format'
import { Alert, EmptyState, Field, Modal, Spinner } from '../components/ui'
import { IconPlus, IconTrash } from '../components/icons'

// Прочий доход — не от карго-продаж и не депозит (возмещения, услуги и т.п.).
// Входит в выручку ОПиУ без расчётной себестоимости 55% и в приток ОДДС.
export default function OtherIncome() {
  const [from, setFrom] = useState(firstOfMonth())
  const [to, setTo] = useState(today())
  const [form, setForm] = useState(null)
  const [busyId, setBusyId] = useState(null)
  const [error, setError] = useState('')

  const items = useFetch('/other-income/', { from, to, page_size: 10000 })
  const accounts = useFetch('/accounts/', { page_size: 10000 })
  const rows = asList(items.data)
  const totalKgs = rows.reduce((a, r) => a + Number(r.amount_kgs || 0), 0)

  async function remove(r) {
    if (!window.confirm(`Удалить прочий доход на ${money(r.amount)}?`)) return
    setBusyId(r.id)
    setError('')
    try {
      await api.delete(`/other-income/${r.id}/`)
      items.reload()
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setBusyId(null)
    }
  }

  return (
    <>
      {error && <Alert kind="error">{error}</Alert>}
      <div className="card">
        <div className="card-header">
          <div className="toolbar grow">
            <Field label="С даты">
              <input className="input" type="date" value={from} onChange={(e) => setFrom(e.target.value)} />
            </Field>
            <Field label="По дату">
              <input className="input" type="date" value={to} onChange={(e) => setTo(e.target.value)} />
            </Field>
          </div>
          <button className="btn btn-primary" onClick={() => setForm('new')}>
            <IconPlus size={18} /> Прочий доход
          </button>
        </div>
        <p className="caption" style={{ margin: '0 0 12px', lineHeight: 1.5 }}>
          Доходы не от карго-продаж (возмещения, услуги и т.п.). Входят в выручку без расчётной себестоимости 55% и в приток ОДДС.
        </p>
        {!items.loading && rows.length > 0 && (
          <div className="caption" style={{ marginBottom: 8 }}>Всего {rows.length} · {money(totalKgs)}</div>
        )}
        {items.loading ? (
          <Spinner />
        ) : rows.length === 0 ? (
          <EmptyState>Прочих доходов за период нет.</EmptyState>
        ) : (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr><th>Дата</th><th>Счёт</th><th>Источник</th><th className="num">Сумма</th><th></th></tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.id}>
                    <td>{dateRu(r.date)}</td>
                    <td>{r.account_name}</td>
                    <td>{r.description || '—'}</td>
                    <td className="num pos">
                      {money(r.amount, r.account_currency)}
                      {r.account_currency === 'CNY' && <div className="caption muted">≈ {money(r.amount_kgs)}</div>}
                    </td>
                    <td className="num">
                      <button className="btn btn-icon btn-danger btn-sm" title="Удалить" disabled={busyId === r.id} onClick={() => remove(r)}>
                        <IconTrash size={16} />
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {form && (
        <OtherIncomeForm
          accounts={asList(accounts.data)}
          onClose={() => setForm(null)}
          onSaved={() => { setForm(null); items.reload() }}
        />
      )}
    </>
  )
}

function OtherIncomeForm({ accounts, onClose, onSaved }) {
  const [accountId, setAccountId] = useState(accounts[0]?.id || '')
  const [amount, setAmount] = useState('')
  const [description, setDescription] = useState('')
  const [date, setDate] = useState(today())
  const [error, setError] = useState('')
  const [saving, setSaving] = useState(false)

  async function submit(e) {
    e.preventDefault()
    setError('')
    setSaving(true)
    try {
      await api.post('/other-income/', { account: accountId, amount, description: description.trim(), date })
      onSaved()
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setSaving(false)
    }
  }

  return (
    <Modal
      title="Прочий доход"
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
        <Field label="Счёт зачисления">
          <select className="select" value={accountId} onChange={(e) => setAccountId(e.target.value)} required>
            {accounts.map((a) => (
              <option key={a.id} value={a.id}>{a.name} · {a.currency} ({a.module === 'BUSINESS' ? 'Business' : 'Express'})</option>
            ))}
          </select>
        </Field>
        <div className="row row-wrap">
          <Field label="Сумма">
            <input className="input" type="number" step="0.01" min="0" value={amount} onChange={(e) => setAmount(e.target.value)} placeholder="0.00" required autoFocus />
          </Field>
          <Field label="Дата">
            <input className="input" type="date" value={date} onChange={(e) => setDate(e.target.value)} required />
          </Field>
        </div>
        <Field label="Источник / комментарий">
          <input className="input" value={description} onChange={(e) => setDescription(e.target.value)} placeholder="Напр.: возмещение, услуга" />
        </Field>
      </form>
    </Modal>
  )
}
