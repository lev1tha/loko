import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import { AuthProvider, useAuth } from './auth/AuthContext'
import ProtectedRoute from './components/ProtectedRoute'
import ErrorBoundary from './components/ErrorBoundary'
import Layout from './components/Layout'
import OperatorLayout from './components/OperatorLayout'
import DirectorLayout from './components/DirectorLayout'
import Login from './pages/Login'
import NotFound from './pages/NotFound'
import Dashboard from './pages/Dashboard'
import Control from './pages/Control'
import Sales from './pages/Sales'
import OtherIncome from './pages/OtherIncome'
import OperatorSale from './pages/OperatorSale'
import Expenses from './pages/Expenses'
import Accounts from './pages/Accounts'
import Transfers from './pages/Transfers'
import Deposits from './pages/Deposits'
import Debts from './pages/Debts'
import BusinessOrders from './pages/BusinessOrders'
import Journal from './pages/Journal'
import Calculator from './pages/Calculator'
import Reports from './pages/Reports'
import Settings from './pages/Settings'
import Users from './pages/Users'

export default function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <ErrorBoundary>
          <AppRoutes />
        </ErrorBoundary>
      </BrowserRouter>
    </AuthProvider>
  )
}

function AppRoutes() {
  const { isOperator, isDirector, directorModule } = useAuth()

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
          <Route index element={<Reports lockedModule={directorModule} />} />
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

        {/* 404 — внутри оболочки приложения, с навигацией */}
        <Route path="*" element={<NotFound />} />
      </Route>
    </Routes>
  )
}
