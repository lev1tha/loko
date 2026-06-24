import { useEffect, useMemo, useState } from 'react'
import api, { errorMessage } from '../api/client'
import { useFetch, asList } from '../lib/hooks'
import { firstOfMonth, today, money, dateRu } from '../lib/format'
import { Alert, Badge, EmptyState, Field, Modal, Spinner } from '../components/ui'
import { IconPlus, IconTransfer } from '../components/icons'

// module: 'BUSINESS' | undefined (all)
export default function Transfers({ module }) {
  const [from, setFrom] = useState(firstOfMonth())
  const [to, setTo] = useState(today())
  const [showForm, setShowForm] = useState(false)

  const params = { from, to, ...(module ? { module } : {}), page_size: 10000 }
  const transfers = useFetch('/transfers/', params)
  const accounts = useFetch('/accounts/', module ? { module, page_size: 10000 } : { page_size: 10000 })
  const rows = asList(transfers.data)

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
          </div>
          <button className="btn btn-primary" onClick={() => setShowForm(true)}>
            <IconPlus size={18} /> {module === 'BUSINESS' ? 'Перевод / Обмен' : 'Новый перевод'}
          </button>
        </div>

        {transfers.loading ? (
          <Spinner />
        ) : rows.length === 0 ? (
          <EmptyState>Перемещений за период нет.</EmptyState>
        ) : (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>Дата</th>
                  <th>Со счёта</th>
                  <th className="num">Списано</th>
                  <th></th>
                  <th>На счёт</th>
                  <th className="num">Зачислено</th>
                  <th className="num">Курс</th>
                  <th>Комментарий</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((t) => (
                  <tr key={t.id}>
                    <td>{dateRu(t.date)}</td>
                    <td>{t.from_account_name}</td>
                    <td className="num">{money(t.amount, t.from_currency)}</td>
                    <td className="muted"><IconTransfer size={16} /></td>
                    <td>
                      <strong>{t.to_account_name}</strong>{' '}
                      {t.is_conversion && <Badge variant="badge-admin">обмен</Badge>}
                    </td>
                    <td className="num">{money(t.to_amount, t.to_currency)}</td>
                    <td className="num">{t.is_conversion ? Number(t.rate).toLocaleString('ru-RU') : '—'}</td>
                    <td className="muted">{t.description || '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {showForm && (
        <TransferForm
          accounts={asList(accounts.data)}
          onClose={() => setShowForm(false)}
          onSaved={() => {
            setShowForm(false)
            transfers.reload()
          }}
        />
      )}
    </>
  )
}

function TransferForm({ accounts, onClose, onSaved }) {
  const [fromId, setFromId] = useState(accounts[0]?.id || '')
  const [toId, setToId] = useState(accounts[1]?.id || accounts[0]?.id || '')
  const [amount, setAmount] = useState('')
  const [rate, setRate] = useState('')
  const [toAmount, setToAmount] = useState('')
  const [description, setDescription] = useState('')
  const [date, setDate] = useState(today())
  const [error, setError] = useState('')
  const [saving, setSaving] = useState(false)

  const fromAcc = useMemo(() => accounts.find((a) => String(a.id) === String(fromId)), [accounts, fromId])
  const toAcc = useMemo(() => accounts.find((a) => String(a.id) === String(toId)), [accounts, toId])
  const isConversion = fromAcc && toAcc && fromAcc.currency !== toAcc.currency

  // For conversions, derive credited amount = списано / курс (rate = сом за 1 юань).
  useEffect(() => {
    if (!isConversion) {
      setToAmount(amount)
      return
    }
    const a = parseFloat(amount)
    const r = parseFloat(rate)
    if (a > 0 && r > 0) {
      // KGS -> CNY: CNY = KGS / rate ; CNY -> KGS: KGS = CNY * rate
      const credited = fromAcc.currency === 'KGS' ? a / r : a * r
      setToAmount(credited ? credited.toFixed(2) : '')
    } else {
      setToAmount('')
    }
  }, [amount, rate, isConversion, fromAcc])

  async function submit(e) {
    e.preventDefault()
    setError('')
    if (String(fromId) === String(toId)) {
      setError('Счёт отправителя и получателя не могут совпадать.')
      return
    }
    setSaving(true)
    try {
      await api.post('/transfers/', {
        from_account: fromId,
        to_account: toId,
        amount,
        to_amount: toAmount || amount,
        rate: isConversion ? rate || 1 : 1,
        description: description.trim(),
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
      title="Перевод / Конвертация"
      onClose={onClose}
      footer={
        <>
          <button className="btn btn-secondary" onClick={onClose}>Отмена</button>
          <button className="btn btn-primary" onClick={submit} disabled={saving}>
            {saving ? 'Выполнение…' : 'Выполнить'}
          </button>
        </>
      }
    >
      <form onSubmit={submit} className="col">
        {error && <Alert kind="error">{error}</Alert>}
        <div className="row row-wrap">
          <Field label="Со счёта (отправитель)">
            <select className="select" value={fromId} onChange={(e) => setFromId(e.target.value)} required>
              {accounts.map((a) => <option key={a.id} value={a.id}>{a.name} · {a.currency}</option>)}
            </select>
          </Field>
          <Field label="На счёт (получатель)">
            <select className="select" value={toId} onChange={(e) => setToId(e.target.value)} required>
              {accounts.map((a) => <option key={a.id} value={a.id}>{a.name} · {a.currency}</option>)}
            </select>
          </Field>
        </div>

        <div className="row row-wrap">
          <Field label={`Сумма списания${fromAcc ? ', ' + fromAcc.currency : ''}`}>
            <input className="input" type="number" step="0.01" min="0" value={amount} onChange={(e) => setAmount(e.target.value)} placeholder="0.00" required autoFocus />
          </Field>
          {isConversion && (
            <Field label="Курс (сом за 1 юань)" hint="Вводится вручную при обмене">
              <input className="input" type="number" step="0.0001" min="0" value={rate} onChange={(e) => setRate(e.target.value)} placeholder="13.00" required />
            </Field>
          )}
        </div>

        {toAcc && (Number(amount) > 0 || Number(toAmount) > 0) && (
          <div className="card card-soft sale-preview">
            <div className="caption">Поступит на счёт{isConversion ? ' · обмен валюты' : ''}</div>
            <div className="preview-grid">
              <div className="preview-cell">
                <span className="preview-label">Счёт получателя</span>
                <span className="preview-value">{toAcc.name}</span>
              </div>
              <div className="preview-cell">
                <span className="preview-label">Будет зачислено</span>
                <span className="preview-value">{money(toAmount || amount, toAcc.currency)}</span>
              </div>
              {isConversion && (
                <div className="preview-cell">
                  <span className="preview-label">Курс</span>
                  <span className="preview-value">{rate || '—'} сом/¥</span>
                </div>
              )}
            </div>
          </div>
        )}

        <div className="row row-wrap">
          <Field label="Дата">
            <input className="input" type="date" value={date} onChange={(e) => setDate(e.target.value)} required />
          </Field>
          <Field label="Комментарий">
            <input className="input" value={description} onChange={(e) => setDescription(e.target.value)} placeholder="Покупка юаня / инкассация…" />
          </Field>
        </div>
      </form>
    </Modal>
  )
}
