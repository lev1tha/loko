import { Outlet } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'
import { IconLogout } from './icons'

// Минимальная оболочка для роли «Сотрудник»: только шапка с выходом и форма
// добавления продажи. Никакой навигации, финансов и других разделов.
export default function OperatorLayout() {
  const { user, logout } = useAuth()
  const name = [user?.first_name, user?.last_name].filter(Boolean).join(' ') || user?.username

  return (
    <div className="operator-shell">
      <header className="operator-topbar">
        <div className="operator-brand">
          <div className="brand-mark">L</div>
          <div className="brand-text">
            <strong>Loko Express</strong>
            <span>Добавление продаж</span>
          </div>
        </div>
        <div className="operator-user">
          <span className="operator-username">{name}</span>
          <button className="btn btn-secondary btn-sm" onClick={logout}>
            <IconLogout size={16} /> Выйти
          </button>
        </div>
      </header>

      <main className="operator-main">
        <Outlet />
      </main>
    </div>
  )
}
