import { useState } from 'react'
import api, { errorMessage } from '../api/client'
import { useFetch, asList } from '../lib/hooks'
import { som } from '../lib/format'
import { Alert, EmptyState, Field, Modal, Spinner } from '../components/ui'
import { IconPlus, IconEdit, IconTrash } from '../components/icons'

// Индивидуальные цены за кг по клиентам (Express). По умолчанию цена из Настроек
// (3$ × курс), здесь — исключения для отдельных клиентов (напр. 250/220 сом/кг).
export default function ClientPrices() {
  const prices = useFetch('/client-prices/', { page_size: 10000 })
  const [form, setForm] = useState(null) // null | 'new' | объект цены
  const [busyId, setBusyId] = useState(null)
  const [error, setError] = useState('')
  const rows = asList(prices.data)

  async function remove(r) {
    if (!window.confirm(`Удалить цену клиента «${r.client_code}» (${som(r.price_per_kg_som)}/кг)?`)) return
    setBusyId(r.id)
    setError('')
    try {
      await api.delete(`/client-prices/${r.id}/`)
      prices.reload()
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
          <span className="card-title">Цены клиентов</span>
          <button className="btn btn-primary btn-sm" onClick={() => setForm('new')}>
            <IconPlus size={16} /> Цена клиента
          </button>
        </div>
        <p className="caption" style={{ margin: '0 0 12px', lineHeight: 1.5 }}>
          Индивидуальная цена за 1 кг для клиента (по коду). Подставляется в новой продаже Express «по весу»
          вместо цены по умолчанию из Настроек; её можно переопределить при вводе продажи.
        </p>

        {prices.loading ? (
          <Spinner />
        ) : rows.length === 0 ? (
          <EmptyState>Индивидуальных цен пока нет.</EmptyState>
        ) : (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>Код клиента</th>
                  <th className="num">Цена за кг</th>
                  <th>Комментарий</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.id}>
                    <td><strong>{r.client_code}</strong></td>
                    <td className="num">{som(r.price_per_kg_som)}</td>
                    <td className="muted">{r.note || '—'}</td>
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
        <ClientPriceForm
          editing={form === 'new' ? null : form}
          onClose={() => setForm(null)}
          onSaved={() => { setForm(null); prices.reload() }}
        />
      )}
    </>
  )
}

function ClientPriceForm({ editing, onClose, onSaved }) {
  const isEdit = !!editing
  const [clientCode, setClientCode] = useState(editing?.client_code || '')
  const [price, setPrice] = useState(editing?.price_per_kg_som || '')
  const [note, setNote] = useState(editing?.note || '')
  const [error, setError] = useState('')
  const [saving, setSaving] = useState(false)

  async function submit(e) {
    e.preventDefault()
    setError('')
    setSaving(true)
    try {
      const body = { client_code: clientCode.trim(), price_per_kg_som: price, note: note.trim() }
      // Создание — upsert по коду на бэке; правка существующей — PATCH.
      if (isEdit) await api.patch(`/client-prices/${editing.id}/`, body)
      else await api.post('/client-prices/', body)
      onSaved()
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setSaving(false)
    }
  }

  return (
    <Modal
      title={isEdit ? `Цена клиента · ${editing.client_code}` : 'Цена клиента'}
      onClose={onClose}
      footer={
        <>
          <button className="btn btn-secondary" onClick={onClose}>Отмена</button>
          <button className="btn btn-primary" onClick={submit} disabled={saving}>
            {saving ? 'Сохранение…' : isEdit ? 'Сохранить' : 'Добавить'}
          </button>
        </>
      }
    >
      <form onSubmit={submit} className="col">
        {error && <Alert kind="error">{error}</Alert>}
        <Field label="Код клиента" hint="Точный код, как в продажах">
          <input className="input" value={clientCode} onChange={(e) => setClientCode(e.target.value)} placeholder="29520" required autoFocus disabled={isEdit} />
        </Field>
        <Field label="Цена за 1 кг, сом" hint="Напр. 250 или 220 (по умолчанию ≈ 270)">
          <input className="input" type="number" step="0.01" min="0" value={price} onChange={(e) => setPrice(e.target.value)} placeholder="250" required />
        </Field>
        <Field label="Комментарий">
          <input className="input" value={note} onChange={(e) => setNote(e.target.value)} placeholder="напр.: постоянный клиент" />
        </Field>
      </form>
    </Modal>
  )
}
