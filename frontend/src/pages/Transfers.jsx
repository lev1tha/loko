import { useEffect, useMemo, useState } from 'react'
import api, { errorMessage } from '../api/client'
import { useFetch, asList } from '../lib/hooks'
import { firstOfMonth, today, money, dateRu } from '../lib/format'
import { useAuth } from '../auth/AuthContext'
import { Alert, Badge, EmptyState, Field, Modal, Spinner } from '../components/ui'
import { IconPlus, IconEdit, IconTrash, IconTransfer } from '../components/icons'

// module: 'BUSINESS' | undefined (all)
export default function Transfers({ module }) {
  const { isAdmin } = useAuth()
  const [from, setFrom] = useState(firstOfMonth())
  const [to, setTo] = useState(today())
  const [form, setForm] = useState(null) // null=закрыто, 'new', или объект перевода (правка)
  const [busyId, setBusyId] = useState(null)
  const [error, setError] = useState('')

  const params = { from, to, ...(module ? { module } : {}), page_size: 10000 }
  const transfers = useFetch('/transfers/', params)
  const withdrawals = useFetch('/expenses/', { from, to, category: 'OWNER', ...(module ? { module } : {}), page_size: 10000 })
  const accounts = useFetch('/accounts/', module ? { module, page_size: 10000 } : { page_size: 10000 })

  // Правка/удаление операций — привилегия администратора (корректировка обмена/переводов).
  async function removeTransfer(t) {
    if (!window.confirm(`Удалить перевод от ${dateRu(t.date)} на ${money(t.amount, t.from_currency)}? Действие необратимо.`)) return
    setBusyId(t.id)
    setError('')
    try {
      await api.delete(`/transfers/${t.id}/`)
      transfers.reload()
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setBusyId(null)
    }
  }

  // Переводы/конвертации + изъятия «на личный кошелёк» (вывод владельцем) в одном списке, по дате.
  const movements = [
    ...asList(transfers.data).map((t) => ({ kind: 'transfer', ...t })),
    ...asList(withdrawals.data).map((e) => ({ kind: 'withdrawal', ...e })),
  ].sort((a, b) => String(b.date).localeCompare(String(a.date)))
  const loading = transfers.loading || withdrawals.loading

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
            <IconPlus size={18} /> {module === 'BUSINESS' ? 'Перевод / Обмен' : 'Новый перевод'}
          </button>
        </div>

        {loading ? (
          <Spinner />
        ) : movements.length === 0 ? (
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
                  {isAdmin && <th></th>}
                </tr>
              </thead>
              <tbody>
                {movements.map((m) => m.kind === 'transfer' ? (
                  <tr key={'t' + m.id}>
                    <td>{dateRu(m.date)}</td>
                    <td>{m.from_account_name}</td>
                    <td className="num">{money(m.amount, m.from_currency)}</td>
                    <td className="muted"><IconTransfer size={16} /></td>
                    <td>
                      <strong>{m.to_account_name}</strong>{' '}
                      {m.is_conversion && <Badge variant="badge-admin">обмен</Badge>}
                    </td>
                    <td className="num">{money(m.to_amount, m.to_currency)}</td>
                    <td className="num">{m.is_conversion ? Number(m.rate).toLocaleString('ru-RU') : '—'}</td>
                    <td className="muted">{m.description || '—'}</td>
                    {isAdmin && (
                      <td className="num">
                        <div className="row gap-sm" style={{ justifyContent: 'flex-end' }}>
                          <button className="btn btn-icon btn-ghost btn-sm" title="Изменить" onClick={() => setForm(m)}>
                            <IconEdit size={16} />
                          </button>
                          <button className="btn btn-icon btn-danger btn-sm" title="Удалить" disabled={busyId === m.id} onClick={() => removeTransfer(m)}>
                            <IconTrash size={16} />
                          </button>
                        </div>
                      </td>
                    )}
                  </tr>
                ) : (
                  <tr key={'w' + m.id}>
                    <td>{dateRu(m.date)}</td>
                    <td>{m.account_name}</td>
                    <td className="num">{money(m.amount, m.account_currency)}</td>
                    <td className="muted"><IconTransfer size={16} /></td>
                    <td>
                      <strong>Личный кошелёк</strong>{' '}
                      <Badge variant="badge-danger">вывод</Badge>
                    </td>
                    <td className="num muted">—</td>
                    <td className="num">—</td>
                    <td className="muted">{m.description || 'Изъятие собственника'}</td>
                    {isAdmin && <td className="num"><span className="caption muted" title="Изъятия правятся в разделе «Расходы»">—</span></td>}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <p className="caption mt-lg" style={{ lineHeight: 1.5 }}>
          Здесь и переводы между счетами, и покупка юаня (обмен), и изъятия «на личный кошелёк» (вывод владельцем).
          Изъятия также учитываются в разделе «Расходы» (категория «Изъятие собственника»).
        </p>
      </div>

      {form && (
        <TransferForm
          editing={form === 'new' ? null : form}
          accounts={asList(accounts.data)}
          onClose={() => setForm(null)}
          onSaved={() => {
            setForm(null)
            transfers.reload()
          }}
        />
      )}
    </>
  )
}

function TransferForm({ editing, accounts, onClose, onSaved }) {
  const isEdit = !!editing
  const [fromId, setFromId] = useState(editing?.from_account ?? (accounts[0]?.id || ''))
  const [toId, setToId] = useState(editing?.to_account ?? (accounts[1]?.id || accounts[0]?.id || ''))
  const [amount, setAmount] = useState(editing?.amount ?? '')
  const [rate, setRate] = useState(editing && Number(editing.rate) !== 1 ? String(editing.rate) : '')
  const [toAmount, setToAmount] = useState(editing?.to_amount ?? '')
  const [description, setDescription] = useState(editing?.description ?? '')
  const [date, setDate] = useState(editing?.date ?? today())
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
      const body = {
        from_account: fromId,
        to_account: toId,
        amount,
        to_amount: toAmount || amount,
        rate: isConversion ? rate || 1 : 1,
        description: description.trim(),
        date,
      }
      if (isEdit) await api.patch(`/transfers/${editing.id}/`, body)
      else await api.post('/transfers/', body)
      onSaved()
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setSaving(false)
    }
  }

  return (
    <Modal
      title={isEdit ? 'Изменить перевод / обмен' : 'Перевод / Конвертация'}
      onClose={onClose}
      footer={
        <>
          <button className="btn btn-secondary" onClick={onClose}>Отмена</button>
          <button className="btn btn-primary" onClick={submit} disabled={saving}>
            {saving ? 'Сохранение…' : isEdit ? 'Сохранить' : 'Выполнить'}
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
