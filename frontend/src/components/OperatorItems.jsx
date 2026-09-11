import { useState } from 'react'
import api, { errorMessage } from '../api/client'
import { useFetch, asList } from '../lib/hooks'
import { som, kg } from '../lib/format'
import { Alert, Field, Modal } from './ui'

const FOUND = new Set(['FOUND', 'DELIVERED'])

// Подпись статуса позиции глазами сотрудника.
function itemMeta(s) {
  if (FOUND.has(s.status)) return `оприходовано${s.weight_kg ? ` · ${s.weight_is_estimated ? '≈ ' : ''}${kg(s.weight_kg)}` : ''}`
  if (s.status === 'LOCATED') return `склад нашёл ${s.quantity > 1 ? `${s.quantity} мест` : ''}${s.found_by_name ? `(${s.found_by_name})` : ''} · впишите сумму и оприходуйте`
  if (s.status === 'NOT_FOUND') return `не найдено${s.reason ? ` · ${s.reason}` : ''}`
  if (s.status === 'EVENING') return 'убрано из чека · вечерний допоиск'
  if (s.status === 'EXPECTED') return 'в пути с сайта'
  return 'в поиске'
}

// Заголовок дня: «Сегодня · 11.09», «Вчера · 10.09», дальше «09.09.2026, среда».
const DAYS = ['воскресенье', 'понедельник', 'вторник', 'среда', 'четверг', 'пятница', 'суббота']
function localDay(iso) {
  const d = new Date(iso)
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}
function dayLabel(key) {
  const [y, m, d] = key.split('-').map(Number)
  const date = new Date(y, m - 1, d)
  const t = new Date(); const today = localDay(t)
  const yd = new Date(t); yd.setDate(t.getDate() - 1)
  const short = `${String(d).padStart(2, '0')}.${String(m).padStart(2, '0')}`
  if (key === today) return `Сегодня · ${short}`
  if (key === localDay(yd)) return `Вчера · ${short}`
  return `${short}.${y}, ${DAYS[date.getDay()]}`
}

// Список позиций по дням: свежие сверху, в каждом дне — счётчик и сумма оприходованного.
export function OperatorItemsByDay({ items, busyId, onReceive, onDismiss }) {
  const groups = new Map()
  for (const it of items) {
    const key = localDay(it.created_at)
    if (!groups.has(key)) groups.set(key, [])
    groups.get(key).push(it)
  }
  const keys = [...groups.keys()].sort().reverse()
  return (
    <div className="operator-sales">
      {keys.map((key) => {
        const rows = groups.get(key)
        const total = rows.filter((r) => FOUND.has(r.status)).reduce((s, r) => s + (parseFloat(r.price_som) || 0), 0)
        const pending = rows.filter((r) => r.status === 'LOCATED').length
        return (
          <div className="operator-day" key={key}>
            <div className="operator-day-head">
              <span className="operator-day-title">{dayLabel(key)}</span>
              <span className="operator-day-meta">
                {rows.length} {rows.length === 1 ? 'код' : rows.length < 5 ? 'кода' : 'кодов'}
                {pending > 0 && ` · оприходовать: ${pending}`}
                {total > 0 && ` · ${som(total)}`}
              </span>
            </div>
            {rows.map((it) => (
              <OperatorItemRow key={it.id} item={it} busyId={busyId} onReceive={onReceive} onDismiss={onDismiss} />
            ))}
          </div>
        )
      })}
    </div>
  )
}

// Строка позиции сотрудника: статус, сумма, действия «Оприходовать» (найденное) и «✕» (не найдено).
export function OperatorItemRow({ item, busyId, onReceive, onDismiss }) {
  const found = FOUND.has(item.status)
  return (
    <div className={`operator-sales-row wh-row-${item.status.toLowerCase()}`}>
      <div className="operator-sales-main">
        <span className="operator-sales-code">{item.client_code}{item.quantity > 1 ? ` × ${item.quantity}` : ''}</span>
        <span className="operator-sales-meta">{itemMeta(item)}</span>
      </div>
      {found && <span className="operator-sales-sum">{som(item.price_som)}</span>}
      {item.status === 'LOCATED' && (
        <button type="button" className="btn btn-primary btn-sm" disabled={busyId === item.id} onClick={() => onReceive(item)}>
          Оприходовать
        </button>
      )}
      {item.status === 'NOT_FOUND' && (
        <button type="button" className="btn btn-icon wh-remove" title="Убрать из чека (в вечерний допоиск)"
          disabled={busyId === item.id} onClick={() => onDismiss(item)}>✕</button>
      )}
    </div>
  )
}

// Модалка оприходования сотрудником: вес, счёт, трек-номер → продажа с ценой.
export function ReceiveModal({ item, onClose, onDone }) {
  const accounts = asList(useFetch('/warehouse-items/accounts/').data)
  const [amount, setAmount] = useState('')
  const [weight, setWeight] = useState('')
  const [qty, setQty] = useState(item.quantity || 1)
  const [tracking, setTracking] = useState(item.tracking_number || '')
  const [accountId, setAccountId] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const acc = accountId || (accounts.find((a) => a.kind === 'CASH') || accounts[0])?.id || ''

  async function submit(e) {
    e?.preventDefault?.()
    const sum = parseFloat(String(amount).replace(',', '.'))
    if (!(sum > 0)) { setError('Укажите сумму больше нуля.'); return }
    if (weight !== '' && !(parseFloat(weight) > 0)) { setError('Вес должен быть больше нуля, либо оставьте поле пустым.'); return }
    if (!acc) { setError('Нет счёта зачисления, обратитесь к администратору.'); return }
    setBusy(true); setError('')
    try {
      await api.post(`/warehouse-items/${item.id}/receive/`, {
        price_som: sum.toFixed(2), weight_kg: weight !== '' ? weight : null, account: acc, tracking_number: tracking.trim(),
        quantity: Math.max(1, parseInt(qty, 10) || 1),
      })
      onDone()
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <Modal
      title={`Оприходовать · ${item.client_code}`}
      onClose={onClose}
      footer={
        <>
          <button className="btn btn-secondary" onClick={onClose}>Отмена</button>
          <button className="btn btn-primary" disabled={busy} onClick={submit}>{busy ? 'Сохраняю…' : 'Оприходовать'}</button>
        </>
      }
    >
      <form onSubmit={submit}>
        {error && <Alert kind="error">{error}</Alert>}
        <p className="caption" style={{ margin: '0 0 8px', lineHeight: 1.5 }}>
          Склад нашёл посылку{item.found_by_name ? ` (${item.found_by_name})` : ''}. Впишите сумму — продажа запишется на вас. Вес по желанию: без него он посчитается из суммы по тарифу.
        </p>
        <Field label="Сумма, сом">
          <input className="input" type="number" step="0.01" min="0" value={amount} onChange={(e) => setAmount(e.target.value)} placeholder="810" autoFocus />
        </Field>
        <Field label="Кол-во мест" hint="Сколько коробок реально получили">
          <input className="input" type="number" min="1" max="999" value={qty} onChange={(e) => setQty(e.target.value)} />
        </Field>
        <Field label="Вес, кг" hint="Необязательно, если взвесили">
          <input className="input" type="number" step="0.001" min="0" value={weight} onChange={(e) => setWeight(e.target.value)} placeholder="≈ из суммы" />
        </Field>
        <Field label="Трек-номер посылки" hint="Необязательно. Клиент увидит его в кабинете kargoosh.kg">
          <input className="input" value={tracking} onChange={(e) => setTracking(e.target.value)} placeholder="YT8872477816368" />
        </Field>
        <Field label="Счёт зачисления (нал/безнал)">
          <select className="select" value={acc} onChange={(e) => setAccountId(e.target.value)}>
            {accounts.map((a) => <option key={a.id} value={a.id}>{a.name} ({a.kind === 'CASH' ? 'наличные' : 'безнал'})</option>)}
          </select>
        </Field>
      </form>
    </Modal>
  )
}
