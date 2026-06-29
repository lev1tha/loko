import { useState } from 'react'
import api, { errorMessage } from '../api/client'
import { useAuth } from '../auth/AuthContext'
import { useFetch, asList } from '../lib/hooks'
import { Alert, Badge, EmptyState, Field, Modal, Spinner } from '../components/ui'
import { IconPlus, IconTrash } from '../components/icons'

export default function Users() {
  const { user } = useAuth()
  const users = useFetch('/users/')
  const [showForm, setShowForm] = useState(false)
  const [busyId, setBusyId] = useState(null)
  const [error, setError] = useState('')
  const rows = asList(users.data)

  async function remove(u) {
    if (!window.confirm(`Удалить пользователя «${u.username}»? Действие необратимо.`)) return
    setBusyId(u.id)
    setError('')
    try {
      await api.delete(`/users/${u.id}/`)
      users.reload()
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
                  <th>Направление</th>
                  <th>Статус</th>
                  <th></th>
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
                    <td className="muted">{u.role === 'DIRECTOR' ? (u.module_display || '—') : '—'}</td>
                    <td>
                      <Badge variant={u.is_active ? 'badge-success' : 'badge-danger'}>
                        {u.is_active ? 'Активен' : 'Отключён'}
                      </Badge>
                    </td>
                    <td className="num">
                      {u.id === user?.id ? (
                        <span className="caption muted">вы</span>
                      ) : (
                        <button
                          className="btn btn-icon btn-danger btn-sm"
                          title="Удалить пользователя"
                          disabled={busyId === u.id}
                          onClick={() => remove(u)}
                        >
                          <IconTrash size={16} />
                        </button>
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
  const [module, setModule] = useState('EXPRESS')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [saving, setSaving] = useState(false)

  const isDirector = role === 'DIRECTOR'

  async function submit(e) {
    e.preventDefault()
    setError('')
    setSaving(true)
    try {
      await api.post('/users/', {
        username: username.trim(),
        first_name: firstName.trim(),
        role,
        // Направление шлём только для директора (остальным сервер обнулит).
        module: isDirector ? module : null,
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
            <option value="DIRECTOR">Директор (только просмотр отчётов направления)</option>
            <option value="OPERATOR">Сотрудник (только добавление продаж)</option>
            <option value="ADMIN">Администратор</option>
          </select>
        </Field>
        {isDirector && (
          <Field label="Направление директора" hint="Какие отчёты ОПиУ/ОДДС он будет видеть">
            <select className="select" value={module} onChange={(e) => setModule(e.target.value)}>
              <option value="EXPRESS">Loko Express</option>
              <option value="BUSINESS">Loko Business</option>
            </select>
          </Field>
        )}
        <Field label="Пароль" hint="Минимум 6 символов">
          <input className="input" type="password" value={password} onChange={(e) => setPassword(e.target.value)} required minLength={6} />
        </Field>
      </form>
    </Modal>
  )
}
