import { useState } from 'react'
import { NavLink, Outlet, useLocation } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'
import {
  IconAccounts,
  IconBox,
  IconDashboard,
  IconExpense,
  IconLogout,
  IconMenu,
  IconReports,
  IconSales,
  IconSettings,
  IconTransfer,
  IconUsers,
} from './icons'
import './Layout.css'

// Navigation grouped by module. Each group renders under a section label.
const GROUPS = [
  {
    items: [{ to: '/', label: 'Дашборд', icon: IconDashboard, end: true }],
  },
  {
    title: 'Loko Express',
    items: [
      { to: '/sales', label: 'Продажи', icon: IconSales },
      { to: '/express/accounts', label: 'Счета Express', icon: IconAccounts },
    ],
  },
  {
    title: 'Loko Business',
    items: [
      { to: '/business/accounts', label: 'Счета Business', icon: IconAccounts },
      { to: '/business/orders', label: 'Заказы (маржа)', icon: IconSales },
      { to: '/business/transfers', label: 'Конвертация / Переводы', icon: IconTransfer },
      { to: '/business/deposits', label: 'Депозиты', icon: IconBox },
      { to: '/business/debts', label: 'Задолженности', icon: IconReports },
    ],
  },
  {
    title: 'Финансы',
    items: [
      { to: '/expenses', label: 'Расходы', icon: IconExpense },
      { to: '/reports', label: 'Отчёты (ООПИУ/ОДДС)', icon: IconReports },
    ],
  },
]

const ADMIN_GROUP = {
  title: 'Администрирование',
  items: [
    { to: '/settings', label: 'Настройки', icon: IconSettings },
    { to: '/users', label: 'Пользователи', icon: IconUsers },
  ],
}

const TITLES = {
  '/': ['Дашборд', 'Сводка по Loko (Express + Business)'],
  '/sales': ['Продажи', 'Loko Express · учёт карго и расчёт маржи'],
  '/express/accounts': ['Счета Express', 'Остатки касс и банков (сом)'],
  '/business/accounts': ['Счета Business', 'Мультивалютные счета · сом / юань'],
  '/business/orders': ['Заказы Business', 'Маржа по клиентам: выручка − закуп'],
  '/business/transfers': ['Конвертация / Переводы', 'Покупка юаня и движение между счетами'],
  '/business/deposits': ['Депозиты', 'Принятые депозиты и признание выручки'],
  '/business/debts': ['Задолженности', 'Кредиторская и дебиторская'],
  '/expenses': ['Расходы', 'Категории, статьи OpEx и списание со счетов'],
  '/reports': ['Отчёты', 'ООПИУ и ОДДС за период'],
  '/settings': ['Настройки', 'Ценообразование, курсы и налог'],
  '/users': ['Пользователи', 'Управление доступом и ролями'],
}

export default function Layout() {
  const { user, logout, isAdmin } = useAuth()
  const [open, setOpen] = useState(false)
  const location = useLocation()
  const [title, sub] = TITLES[location.pathname] || ['Loko ERP', '']
  const initials = (user?.username || '?').slice(0, 2).toUpperCase()
  const close = () => setOpen(false)

  const groups = isAdmin ? [...GROUPS, ADMIN_GROUP] : GROUPS

  return (
    <div className="app-shell">
      <div className={`scrim ${open ? 'show' : ''}`} onClick={close} />

      <aside className={`sidebar ${open ? 'open' : ''}`}>
        <div className="sidebar-brand">
          <div className="brand-mark">L</div>
          <div className="brand-text">
            <strong>Loko ERP</strong>
            <span>Express · Business</span>
          </div>
        </div>

        <nav className="nav">
          {groups.map((group, gi) => (
            <div key={gi}>
              {group.title && <div className="nav-section">{group.title}</div>}
              {group.items.map(({ to, label, icon: Icon, end }) => (
                <NavLink
                  key={to}
                  to={to}
                  end={end}
                  className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}
                  onClick={close}
                >
                  <Icon />
                  {label}
                </NavLink>
              ))}
            </div>
          ))}
        </nav>

        <div className="sidebar-foot">
          <div className="user-card">
            <div className="avatar">{initials}</div>
            <div className="user-meta">
              <strong>{user?.username}</strong>
              <span>{user?.role_display}</span>
            </div>
          </div>
          <button className="btn btn-secondary btn-block btn-sm" onClick={logout}>
            <IconLogout size={16} /> Выйти
          </button>
        </div>
      </aside>

      <div className="main">
        <header className="topbar">
          <button
            className="btn btn-icon btn-ghost hamburger"
            onClick={() => setOpen((o) => !o)}
            aria-label="Меню"
          >
            <IconMenu />
          </button>
          <div>
            <h1>{title}</h1>
            {sub && <div className="topbar-sub">{sub}</div>}
          </div>
        </header>

        <main className="content">
          <Outlet />
        </main>
      </div>
    </div>
  )
}
