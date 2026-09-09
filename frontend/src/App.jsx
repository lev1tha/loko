import { Suspense, lazy } from 'react'
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import { Spinner } from './components/ui'
import { DialogHost } from './lib/dialogs'
import { AuthProvider, useAuth } from './auth/AuthContext'
import ProtectedRoute from './components/ProtectedRoute'
import ErrorBoundary from './components/ErrorBoundary'
import Layout from './components/Layout'
import OperatorLayout from './components/OperatorLayout'
import DirectorLayout from './components/DirectorLayout'
import Login from './pages/Login'
import NotFound from './pages/NotFound'
import WarehouseLayout from './components/WarehouseLayout'

// Страницы грузятся по требованию: у складовщика и сотрудника в стартовом бандле нет
// ни отчётов, ни админки. Оболочки и логин остаются в основном чанке.
const ClientApp = lazy(() => import('./client/ClientApp'))
const Dashboard = lazy(() => import('./pages/Dashboard'))
const Control = lazy(() => import('./pages/Control'))
const Sales = lazy(() => import('./pages/Sales'))
const Clients = lazy(() => import('./pages/Clients'))
const ClientPrices = lazy(() => import('./pages/ClientPrices'))
const OtherIncome = lazy(() => import('./pages/OtherIncome'))
const OperatorSale = lazy(() => import('./pages/OperatorSale'))
const OperatorMySales = lazy(() => import('./pages/OperatorMySales'))
const WarehouseDashboard = lazy(() => import('./pages/WarehouseDashboard'))
const Workflow = lazy(() => import('./pages/Workflow'))
const DirectorHome = lazy(() => import('./pages/DirectorHome'))
const DirectorIncome = lazy(() => import('./pages/DirectorIncome'))
const DirectorExpense = lazy(() => import('./pages/DirectorExpense'))
const WarehouseStock = lazy(() => import('./pages/WarehouseStock'))
const Expenses = lazy(() => import('./pages/Expenses'))
const Accounts = lazy(() => import('./pages/Accounts'))
const Transfers = lazy(() => import('./pages/Transfers'))
const Deposits = lazy(() => import('./pages/Deposits'))
const Debts = lazy(() => import('./pages/Debts'))
const BusinessOrders = lazy(() => import('./pages/BusinessOrders'))
const Journal = lazy(() => import('./pages/Journal'))
const Calculator = lazy(() => import('./pages/Calculator'))
const Reports = lazy(() => import('./pages/Reports'))
const Bonuses = lazy(() => import('./pages/Bonuses'))
const Settings = lazy(() => import('./pages/Settings'))
const Users = lazy(() => import('./pages/Users'))
const Branches = lazy(() => import('./pages/Branches'))
const Guide = lazy(() => import('./pages/Guide'))

export default function App() {
  // Публичная клиентская страница по QR (/track?b=…) — отдельное приложение без
  // входа и вне AuthProvider (клиент узнаётся по телефону, не по JWT).
  if (window.location.pathname.startsWith('/track')) {
    return (
      <Suspense fallback={<Spinner full />}>
        <ClientApp />
      </Suspense>
    )
  }
  return (
    <AuthProvider>
      <BrowserRouter>
        <ErrorBoundary>
          <Suspense fallback={<Spinner full />}>
            <AppRoutes />
          </Suspense>
          <DialogHost />
        </ErrorBoundary>
      </BrowserRouter>
    </AuthProvider>
  )
}

function AppRoutes() {
  const { isOperator, isDirector, isWarehouse, directorModule } = useAuth()

  // Роль «Сотрудник» получает ОТДЕЛЬНОЕ приложение: только страница добавления
  // продаж Express. Любой другой путь возвращает на неё — никаких финансов.
  if (isOperator) {
    return (
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route
          element={
            <ProtectedRoute>
              <OperatorLayout />
            </ProtectedRoute>
          }
        >
          <Route index element={<OperatorSale />} />
          <Route path="my-sales" element={<OperatorMySales />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Route>
      </Routes>
    )
  }

  // Роль «Директор» — ОТДЕЛЬНОЕ приложение: только отчёты ОПиУ/ОДДС своего
  // направления, read-only. Направление зафиксировано (lockedModule), сервер
  // дополнительно ограничивает данные его направлением.
  if (isDirector) {
    return (
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route
          element={
            <ProtectedRoute>
              <DirectorLayout />
            </ProtectedRoute>
          }
        >
          <Route index element={<DirectorHome />} />
          <Route path="reports" element={<Reports initialModule={directorModule || 'all'} />} />
          <Route path="workflow" element={<Workflow />} />
          <Route path="stock" element={<WarehouseStock />} />
          <Route path="income" element={<DirectorIncome />} />
          <Route path="expense" element={<DirectorExpense />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Route>
      </Routes>
    )
  }

  // Роль «Складовщик» — ОТДЕЛЬНОЕ приложение: доска сборки заказов своего филиала.
  // Любой путь возвращает на доску.
  if (isWarehouse) {
    return (
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route
          element={
            <ProtectedRoute>
              <WarehouseLayout />
            </ProtectedRoute>
          }
        >
          <Route index element={<WarehouseDashboard />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Route>
      </Routes>
    )
  }

  return (
    <Routes>
      <Route path="/login" element={<Login />} />

      <Route
        element={
          <ProtectedRoute>
            <Layout />
          </ProtectedRoute>
        }
      >
        <Route index element={<Dashboard />} />
        <Route path="control" element={<Control />} />
        <Route path="journal" element={<Journal />} />

        {/* Loko Express */}
        <Route path="sales" element={<Sales />} />
        <Route path="express/clients" element={<Clients />} />
        <Route path="express/workflow" element={<Workflow />} />
        <Route path="express/stock" element={<WarehouseStock />} />
        <Route path="express/client-prices" element={<ClientPrices />} />
        <Route path="express/other-income" element={<OtherIncome lockedModule="EXPRESS" />} />
        <Route path="express/expenses" element={<Expenses lockedModule="EXPRESS" />} />
        <Route path="express/transfers" element={<Transfers module="EXPRESS" />} />
        <Route path="express/accounts" element={<Accounts module="EXPRESS" />} />
        <Route path="express/reports" element={<Reports lockedModule="EXPRESS" />} />

        {/* Loko Business */}
        <Route path="business/accounts" element={<Accounts module="BUSINESS" />} />
        <Route path="business/orders" element={<BusinessOrders />} />
        <Route path="business/transfers" element={<Transfers module="BUSINESS" />} />
        <Route path="business/deposits" element={<Deposits />} />
        <Route path="business/other-income" element={<OtherIncome lockedModule="BUSINESS" />} />
        <Route path="business/expenses" element={<Expenses lockedModule="BUSINESS" />} />
        <Route path="business/debts" element={<Debts />} />
        <Route path="business/calculator" element={<Calculator />} />
        <Route path="business/reports" element={<Reports lockedModule="BUSINESS" />} />

        {/* Финансы */}
        <Route path="expenses" element={<Expenses />} />
        <Route path="reports" element={<Reports />} />
        <Route path="bonuses" element={<Bonuses />} />

        {/* Совместимость со старыми ссылками */}
        <Route path="accounts" element={<Navigate to="/express/accounts" replace />} />
        <Route path="transfers" element={<Navigate to="/business/transfers" replace />} />

        {/* Администрирование */}
        <Route
          path="settings"
          element={
            <ProtectedRoute adminOnly>
              <Settings />
            </ProtectedRoute>
          }
        />
        <Route
          path="users"
          element={
            <ProtectedRoute adminOnly>
              <Users />
            </ProtectedRoute>
          }
        />
        <Route
          path="branches"
          element={
            <ProtectedRoute adminOnly>
              <Branches />
            </ProtectedRoute>
          }
        />
        <Route
          path="guide"
          element={
            <ProtectedRoute adminOnly>
              <Guide />
            </ProtectedRoute>
          }
        />

        {/* 404 — внутри оболочки приложения, с навигацией */}
        <Route path="*" element={<NotFound />} />
      </Route>
    </Routes>
  )
}
