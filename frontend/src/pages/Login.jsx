import { useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'
import { errorMessage } from '../api/client'
import { Alert, Field } from '../components/ui'
import './Login.css'

export default function Login() {
  const { login } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  const from = location.state?.from?.pathname || '/'

  async function onSubmit(e) {
    e.preventDefault()
    setError('')
    setLoading(true)
    try {
      await login(username.trim(), password)
      navigate(from, { replace: true })
    } catch (err) {
      setError(errorMessage(err, 'Неверный логин или пароль'))
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="login-wrap">
      <form className="login-card" onSubmit={onSubmit}>
        <div className="login-brand">
          <div className="brand-mark" style={{ width: 44, height: 44, fontSize: 22 }}>
            L
          </div>
          <h2 className="display display-sm" style={{ marginTop: 16 }}>
            Loko Express
          </h2>
          <p className="muted" style={{ margin: '4px 0 0' }}>
            ERP-система · вход в кабинет
          </p>
        </div>

        {error && <Alert kind="error">{error}</Alert>}

        <Field label="Логин">
          <input
            className="input"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            placeholder="admin"
            autoFocus
            autoComplete="username"
          />
        </Field>
        <Field label="Пароль">
          <input
            className="input"
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            placeholder="••••••••"
            autoComplete="current-password"
          />
        </Field>

        <button className="btn btn-primary btn-block" disabled={loading} style={{ marginTop: 4 }}>
          {loading ? 'Вход…' : 'Войти'}
        </button>

        <p className="caption text-center" style={{ marginTop: 4 }}>
          Демо: admin / admin123 · kassir / kassir123
        </p>
      </form>
    </div>
  )
}
