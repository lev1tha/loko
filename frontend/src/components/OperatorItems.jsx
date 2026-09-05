import { useState } from 'react'
import api, { errorMessage } from '../api/client'
import { useFetch, asList } from '../lib/hooks'
import { som, kg } from '../lib/format'
import { Alert, Field, Modal } from './ui'

const FOUND = new Set(['FOUND', 'DELIVERED'])

// Подпись статуса позиции глазами сотрудника.
function itemMeta(s) {
  if (FOUND.has(s.status)) return `оприходовано${s.weight_kg ? ` · ${kg(s.weight_kg)}` : ''}`
  if (s.status === 'LOCATED') return `склад нашёл${s.found_by_name ? ` (${s.found_by_name})` : ''} · взвесьте и оприходуйте`
  if (s.status === 'NOT_FOUND') return `не найдено${s.reason ? ` · ${s.reason}` : ''}`
  if (s.status === 'EVENING') return 'убрано из чека · вечерний допоиск'
  if (s.status === 'EXPECTED') return 'в пути с сайта'
  return 'в поиске'
}

// Строка позиции сотрудника: статус, сумма, действия «Оприходовать» (найденное) и «✕» (не найдено).
export function OperatorItemRow({ item, busyId, onReceive, onDismiss }) {
  const found = FOUND.has(item.status)
  return (
    <div className={`operator-sales-row wh-row-${item.status.toLowerCase()}`}>
      <div className="operator-sales-main">
        <span className="operator-sales-code">{item.client_code}</span>
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
  const [weight, setWeight] = useState('')
  const [tracking, setTracking] = useState(item.tracking_number || '')
  const [accountId, setAccountId] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const acc = accountId || (accounts.find((a) => a.kind === 'CASH') || accounts[0])?.id || ''

  async function submit(e) {
    e?.preventDefault?.()
    if (!(parseFloat(weight) > 0)) { setError('Укажите вес больше нуля.'); return }
    if (!acc) { setError('Нет счёта зачисления, обратитесь к администратору.'); return }
    setBusy(true); setError('')
    try {
      await api.post(`/warehouse-items/${item.id}/receive/`, { weight_kg: weight, account: acc, tracking_number: tracking.trim() })
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
          Склад нашёл посылку{item.found_by_name ? ` (${item.found_by_name})` : ''}. Взвесьте её: сумма посчитается по тарифу, продажа запишется на вас.
        </p>
        <Field label="Фактический вес, кг">
          <input className="input" type="number" step="0.001" min="0" value={weight} onChange={(e) => setWeight(e.target.value)} placeholder="5" autoFocus />
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
