import { useState } from 'react'
import api, { errorMessage } from '../api/client'
import { Alert, Field } from './ui'
import { IconPlus } from './icons'

const MAX = 5

// Форма создания заявки на сборку: 1–5 кодов клиентов + комментарий для склада
// (+ выбор филиала для менеджера/админа). Используется на доске склада и у оператора.
export default function WarehouseOrderForm({ onCreated, branches = [], showBranch = false }) {
  const [codes, setCodes] = useState([''])
  const [comment, setComment] = useState('')
  const [branchId, setBranchId] = useState(branches.find((b) => b.is_default)?.id || '')
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')
  const [saving, setSaving] = useState(false)

  const setCode = (i, v) => setCodes((cs) => cs.map((c, j) => (j === i ? v : c)))
  const addCode = () => setCodes((cs) => (cs.length < MAX ? [...cs, ''] : cs))
  const removeCode = (i) => setCodes((cs) => (cs.length > 1 ? cs.filter((_, j) => j !== i) : cs))

  async function submit(e) {
    e.preventDefault()
    setError('')
    setSuccess('')
    const clean = codes.map((c) => c.trim()).filter(Boolean)
    if (clean.length < 1 || clean.length > MAX) {
      setError(`Укажите от 1 до ${MAX} кодов клиентов.`)
      return
    }
    setSaving(true)
    try {
      const body = { client_codes: clean, comment: comment.trim() }
      if (showBranch && branchId) body.branch = branchId
      await api.post('/warehouse-orders/', body)
      setCodes([''])
      setComment('')
      setSuccess(`Заявка на сборку (${clean.length} код${clean.length === 1 ? '' : 'ов'}) создана.`)
      onCreated?.()
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setSaving(false)
    }
  }

  return (
    <form onSubmit={submit} className="col">
      {error && <Alert kind="error">{error}</Alert>}
      {success && <Alert kind="success">{success}</Alert>}

      <div className="field">
        <span className="field-label">Коды клиентов ({codes.length}/{MAX})</span>
        {codes.map((c, i) => (
          <div key={i} className="row gap-sm" style={{ marginBottom: 6 }}>
            <input
              className="input"
              value={c}
              onChange={(e) => setCode(i, e.target.value)}
              placeholder={`Код клиента ${i + 1}`}
              autoFocus={i === 0}
            />
            {codes.length > 1 && (
              <button type="button" className="btn btn-icon btn-ghost btn-sm" title="Убрать код" onClick={() => removeCode(i)}>
                ×
              </button>
            )}
          </div>
        ))}
        {codes.length < MAX && (
          <button type="button" className="btn btn-secondary btn-sm" onClick={addCode}>
            <IconPlus size={14} /> Добавить код
          </button>
        )}
      </div>

      {showBranch && branches.length > 0 && (
        <Field label="Филиал">
          <select className="select" value={branchId} onChange={(e) => setBranchId(e.target.value)}>
            <option value="">По умолчанию</option>
            {branches.map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}
          </select>
        </Field>
      )}

      <Field label="Комментарий для склада" hint="напр. «Хрупкое», «Большая коробка»">
        <input className="input" value={comment} onChange={(e) => setComment(e.target.value)} placeholder="необязательно" />
      </Field>

      <button className="btn btn-primary" disabled={saving} type="submit">
        {saving ? 'Создание…' : 'Сформировать сборку на склад'}
      </button>
    </form>
  )
}
