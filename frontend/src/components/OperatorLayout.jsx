import { NavLink, Outlet } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'
import { IconLogout } from './icons'

// Минимальная оболочка для роли «Сотрудник»: шапка с выходом, верхняя навигация
// (две вкладки: новая продажа / мои продажи) и контент. Никаких финансов и
// других разделов.
export default function OperatorLayout() {
  const { user, logout } = useAuth()
  const name = [user?.first_name, user?.last_name].filter(Boolean).join(' ') || user?.username

  const linkClass = ({ isActive }) => `operator-nav-link ${isActive ? 'is-active' : ''}`

  return (
    <div className="operator-shell">
      <header className="operator-topbar">
        <div className="operator-brand">
          <div className="brand-mark">L</div>
          <div className="brand-text">
            <strong>Loko Express</strong>
            <span>Кабинет сотрудника</span>
          </div>
        </div>
        <div className="operator-user">
          <span className="operator-username">{name}</span>
          <button className="btn btn-secondary btn-sm" onClick={logout}>
            <IconLogout size={16} /> Выйти
          </button>
        </div>
      </header>

      <nav className="operator-nav">
        <NavLink to="/" end className={linkClass}>
          Новая продажа
        </NavLink>
        <NavLink to="/my-sales" className={linkClass}>
          Мои продажи
        </NavLink>
      </nav>

      <main className="operator-main">
        <Outlet />
      </main>
    </div>
  )
}
