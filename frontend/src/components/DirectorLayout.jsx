import { Outlet } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'
import { IconLogout } from './icons'

const DIRECTION_LABEL = {
  EXPRESS: 'Loko Express',
  BUSINESS: 'Loko Business',
}

// Оболочка для роли «Директор»: только шапка с выходом и отчёты (ОПиУ/ОДДС)
// своего направления. Никакого ввода данных, других разделов и переключателя
// направления — всё read-only и ограничено его направлением на сервере.
export default function DirectorLayout() {
  const { user, logout } = useAuth()
  const name = [user?.first_name, user?.last_name].filter(Boolean).join(' ') || user?.username
  const direction = DIRECTION_LABEL[user?.module] || 'направление не задано'

  return (
    <div className="operator-shell">
      <header className="operator-topbar">
        <div className="operator-brand">
          <div className="brand-mark">L</div>
          <div className="brand-text">
            <strong>{direction}</strong>
            <span>Отчёты · только просмотр</span>
          </div>
        </div>
        <div className="operator-user">
          <span className="operator-username">{name}</span>
          <button className="btn btn-secondary btn-sm" onClick={logout}>
            <IconLogout size={16} /> Выйти
          </button>
        </div>
      </header>

      <main className="operator-main operator-main-wide">
        <Outlet />
      </main>
    </div>
  )
}
