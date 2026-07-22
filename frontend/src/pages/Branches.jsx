import { useState } from 'react'
import api, { errorMessage } from '../api/client'
import { useFetch, asList } from '../lib/hooks'
import { Alert, Badge, EmptyState, Field, Modal, Spinner } from '../components/ui'
import { IconPlus, IconEdit, IconTrash } from '../components/icons'

// Админ-страница управления филиалами Loko Express (точки приёма карго).
// Продажи/расходы тегируются филиалом для раздельной аналитики; история (branch=NULL)
// остаётся в выборке «Все филиалы».
export default function Branches() {
  const req = useFetch('/branches/')
  const [form, setForm] = useState(null) // null | 'new' | branch object
  const [error, setError] = useState('')
  const [busyId, setBusyId] = useState(null)

  const rows = asList(req.data)

  async function remove(b) {
    if (!window.confirm(`Удалить филиал «${b.name}»?`)) return
    setBusyId(b.id)
    setError('')
    try {
      await api.delete(`/branches/${b.id}/`)
      req.reload()
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setBusyId(null)
    }
  }

  if (req.loading) return <Spinner full />

  return (
    <>
      {error && <Alert kind="error">{error}</Alert>}
      <div className="card">
        <div className="card-header">
          <span className="card-title">Филиалы Loko Express</span>
          <button className="btn btn-primary btn-sm" onClick={() => setForm('new')}>
            <IconPlus size={16} /> Новый филиал
          </button>
        </div>
        <p className="caption" style={{ margin: '0 0 12px', lineHeight: 1.5 }}>
          Филиалы — точки приёма карго Express. Продажи и расходы тегируются филиалом для
          раздельной и сводной аналитики. Неактивный филиал не предлагается в формах, но его
          история сохраняется. Удалить филиал с операциями нельзя — отметьте его неактивным.
        </p>
        {rows.length === 0 ? (
          <EmptyState>Филиалов пока нет. Добавьте первый.</EmptyState>
        ) : (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>Название</th>
                  <th>Адрес</th>
                  <th>Статус</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {rows.map((b) => (
                  <tr key={b.id}>
                    <td><strong>{b.name}</strong></td>
                    <td className="muted">{b.address || '—'}</td>
                    <td>
                      <Badge variant={b.is_active ? 'badge-success' : 'badge-manager'}>
                        {b.is_active ? 'Активен' : 'Неактивен'}
                      </Badge>
                    </td>
                    <td className="num">
                      <div className="row gap-sm" style={{ justifyContent: 'flex-end' }}>
                        <button className="btn btn-icon btn-ghost btn-sm" title="Изменить" onClick={() => setForm(b)}>
                          <IconEdit size={16} />
                        </button>
                        <button
                          className="btn btn-icon btn-danger btn-sm"
                          title="Удалить"
                          disabled={busyId === b.id}
                          onClick={() => remove(b)}
                        >
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
        <BranchForm
          editing={form === 'new' ? null : form}
          onClose={() => setForm(null)}
          onSaved={() => {
            setForm(null)
            req.reload()
          }}
        />
      )}
    </>
  )
}

function BranchForm({ editing, onClose, onSaved }) {
  const isEdit = !!editing
  const [name, setName] = useState(editing?.name || '')
  const [address, setAddress] = useState(editing?.address || '')
  const [isActive, setIsActive] = useState(editing ? editing.is_active : true)
  const [error, setError] = useState('')
  const [saving, setSaving] = useState(false)

  async function submit(e) {
    e.preventDefault()
    setError('')
    setSaving(true)
    try {
      const body = { name: name.trim(), address: address.trim(), is_active: isActive }
      if (isEdit) await api.patch(`/branches/${editing.id}/`, body)
      else await api.post('/branches/', body)
      onSaved()
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setSaving(false)
    }
  }

  return (
    <Modal
      title={isEdit ? `Филиал · ${editing.name}` : 'Новый филиал'}
      onClose={onClose}
      footer={
        <>
          <button className="btn btn-secondary" onClick={onClose}>Отмена</button>
          <button className="btn btn-primary" onClick={submit} disabled={saving}>
            {saving ? 'Сохранение…' : isEdit ? 'Сохранить' : 'Создать филиал'}
          </button>
        </>
      }
    >
      <form onSubmit={submit} className="col">
        {error && <Alert kind="error">{error}</Alert>}
        <Field label="Название">
          <input
            className="input"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Loko Express — Гульчинская, 13/1"
            required
            autoFocus
          />
        </Field>
        <Field label="Адрес" hint="Необязательно">
          <input
            className="input"
            value={address}
            onChange={(e) => setAddress(e.target.value)}
            placeholder="ул. Гульчинская, 13/1"
          />
        </Field>
        <label className="check-row">
          <input type="checkbox" checked={isActive} onChange={(e) => setIsActive(e.target.checked)} />
          <span>Активен (предлагается в формах продаж и фильтрах)</span>
        </label>
      </form>
    </Modal>
  )
}
