import { useState } from 'react'
import { NavLink, Outlet, useLocation } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'
import {
  IconAccounts,
  IconBook,
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
    items: [
      { to: '/', label: 'Сводка', icon: IconDashboard, end: true },
      { to: '/control', label: 'Сверка', icon: IconReports },
      { to: '/journal', label: 'История операций', icon: IconReports },
    ],
  },
  {
    title: 'Loko Express',
    items: [
      { to: '/sales', label: 'Продажи', icon: IconSales },
      { to: '/express/client-prices', label: 'Цены клиентов', icon: IconAccounts },
      { to: '/express/other-income', label: 'Прочий доход', icon: IconSales },
      { to: '/express/expenses', label: 'Расходы', icon: IconExpense },
      { to: '/express/transfers', label: 'Переводы и выплаты', icon: IconTransfer },
      { to: '/express/accounts', label: 'Счета', icon: IconAccounts },
      { to: '/express/reports', label: 'Аналитика', icon: IconReports },
    ],
  },
  {
    title: 'Loko Business',
    items: [
      { to: '/business/accounts', label: 'Счета', icon: IconAccounts },
      { to: '/business/orders', label: 'Заказы', icon: IconSales },
      { to: '/business/transfers', label: 'Обмен и переводы', icon: IconTransfer },
      { to: '/business/deposits', label: 'Депозиты', icon: IconBox },
      { to: '/business/other-income', label: 'Поступления', icon: IconSales },
      { to: '/business/expenses', label: 'Расходы', icon: IconExpense },
      { to: '/business/debts', label: 'Задолженности', icon: IconReports },
      { to: '/business/calculator', label: 'Калькулятор', icon: IconExpense },
      { to: '/business/reports', label: 'Аналитика', icon: IconReports },
    ],
  },
  {
    title: 'Финансы',
    items: [
      { to: '/expenses', label: 'Расходы', icon: IconExpense },
      { to: '/reports', label: 'Аналитика', icon: IconReports },
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

// Отдельная группа внизу — инструкция по системе (только для админа).
const HELP_GROUP = {
  title: 'Справка',
  items: [
    { to: '/guide', label: 'Инструкция', icon: IconBook },
  ],
}

const TITLES = {
  '/': ['Сводка', 'Сводка по Loko (Express + Business)'],
  '/control': ['Сверка', 'Как складываются итоги — сверка с тетрадью'],
  '/journal': ['История операций', 'Все события (Express + Business) и как из них вышли цифры'],
  '/sales': ['Продажи', 'Loko Express · учёт карго и расчёт маржи'],
  '/express/client-prices': ['Цены клиентов', 'Индивидуальная цена за кг по клиентам (исключения из цены по умолчанию)'],
  '/express/other-income': ['Прочий доход', 'Доходы не от карго — в выручку без себестоимости 55%'],
  '/express/expenses': ['Расходы · Loko Express', 'Типы расходов, изъятия и статьи — по Express'],
  '/express/transfers': ['Переводы и выплаты · Express', 'Переводы между счетами Express и вывод владельцем'],
  '/express/accounts': ['Счета · Loko Express', 'Остатки касс и банков (сом)'],
  '/express/reports': ['Аналитика · Loko Express', 'ОПиУ и ОДДС по направлению Express'],
  '/business/accounts': ['Счета · Loko Business', 'Мультивалютные счета · сом / юань'],
  '/business/orders': ['Заказы Business', 'Маржа по клиентам: выручка − закуп'],
  '/business/transfers': ['Обмен и переводы', 'Покупка юаня и движение между счетами'],
  '/business/deposits': ['Депозиты', 'Принятые депозиты и признание выручки'],
  '/business/other-income': ['Поступления · Loko Business', 'Доходы не от закупа — в выручку без себестоимости, приток ОДДС'],
  '/business/expenses': ['Расходы · Loko Business', 'Типы расходов, изъятия и статьи — по Business'],
  '/business/debts': ['Задолженности', 'Кредиторская и дебиторская'],
  '/business/calculator': ['Калькулятор закупа', 'Комиссия за закуп и маржа заказа из Китая'],
  '/business/reports': ['Аналитика · Loko Business', 'ОПиУ и ОДДС по направлению Business'],
  '/expenses': ['Расходы', 'Категории, статьи OpEx и списание со счетов'],
  '/reports': ['Аналитика', 'ООПИУ и ОДДС за период'],
  '/settings': ['Настройки', 'Ценообразование, курсы и налог'],
  '/users': ['Пользователи', 'Управление доступом и ролями'],
  '/guide': ['Инструкция', 'Как пользоваться системой — для администраторов'],
}

export default function Layout() {
  const { user, logout, isAdmin } = useAuth()
  const [open, setOpen] = useState(false)
  const location = useLocation()
  const [title, sub] = TITLES[location.pathname] || ['Loko ERP', '']
  const initials = (user?.username || '?').slice(0, 2).toUpperCase()
  const close = () => setOpen(false)

  const groups = isAdmin ? [...GROUPS, ADMIN_GROUP, HELP_GROUP] : GROUPS

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
