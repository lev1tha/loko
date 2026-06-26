import { useState } from 'react'
import api, { errorMessage } from '../api/client'
import { useFetch, asList } from '../lib/hooks'
import { Alert, Badge, EmptyState, Field, Modal, Spinner } from '../components/ui'
import { IconPlus } from '../components/icons'

export default function Users() {
  const users = useFetch('/users/')
  const [showForm, setShowForm] = useState(false)
  const rows = asList(users.data)

  return (
    <>
      <div className="card">
        <div className="card-header">
          <span className="card-title">Пользователи системы</span>
          <button className="btn btn-primary btn-sm" onClick={() => setShowForm(true)}>
            <IconPlus size={16} /> Новый пользователь
          </button>
        </div>

        {users.loading ? (
          <Spinner />
        ) : rows.length === 0 ? (
          <EmptyState>Пользователей нет.</EmptyState>
        ) : (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>Логин</th>
                  <th>Имя</th>
                  <th>Роль</th>
                  <th>Статус</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((u) => (
                  <tr key={u.id}>
                    <td><strong>{u.username}</strong></td>
                    <td className="muted">{[u.first_name, u.last_name].filter(Boolean).join(' ') || '—'}</td>
                    <td>
                      <Badge variant={u.is_admin ? 'badge-admin' : 'badge-manager'}>{u.role_display}</Badge>
                    </td>
                    <td>
                      <Badge variant={u.is_active ? 'badge-success' : 'badge-danger'}>
                        {u.is_active ? 'Активен' : 'Отключён'}
                      </Badge>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {showForm && (
        <UserForm
          onClose={() => setShowForm(false)}
          onSaved={() => {
            setShowForm(false)
            users.reload()
          }}
        />
      )}
    </>
  )
}

function UserForm({ onClose, onSaved }) {
  const [username, setUsername] = useState('')
  const [firstName, setFirstName] = useState('')
  const [role, setRole] = useState('MANAGER')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [saving, setSaving] = useState(false)

  async function submit(e) {
    e.preventDefault()
    setError('')
    setSaving(true)
    try {
      await api.post('/users/', {
        username: username.trim(),
        first_name: firstName.trim(),
        role,
        password,
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
      title="Новый пользователь"
      onClose={onClose}
      footer={
        <>
          <button className="btn btn-secondary" onClick={onClose}>Отмена</button>
          <button className="btn btn-primary" onClick={submit} disabled={saving}>
            {saving ? 'Сохранение…' : 'Создать'}
          </button>
        </>
      }
    >
      <form onSubmit={submit} className="col">
        {error && <Alert kind="error">{error}</Alert>}
        <Field label="Логин">
          <input className="input" value={username} onChange={(e) => setUsername(e.target.value)} required autoFocus />
        </Field>
        <Field label="Имя">
          <input className="input" value={firstName} onChange={(e) => setFirstName(e.target.value)} />
        </Field>
        <Field label="Роль">
          <select className="select" value={role} onChange={(e) => setRole(e.target.value)}>
            <option value="MANAGER">Кассир/Менеджер</option>
            <option value="OPERATOR">Сотрудник (только добавление продаж)</option>
            <option value="ADMIN">Администратор</option>
          </select>
        </Field>
        <Field label="Пароль" hint="Минимум 6 символов">
          <input className="input" type="password" value={password} onChange={(e) => setPassword(e.target.value)} required minLength={6} />
        </Field>
      </form>
    </Modal>
  )
}
