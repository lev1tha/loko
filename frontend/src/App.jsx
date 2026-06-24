import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import { AuthProvider } from './auth/AuthContext'
import ProtectedRoute from './components/ProtectedRoute'
import Layout from './components/Layout'
import Login from './pages/Login'
import Dashboard from './pages/Dashboard'
import Sales from './pages/Sales'
import Expenses from './pages/Expenses'
import Accounts from './pages/Accounts'
import Transfers from './pages/Transfers'
import Deposits from './pages/Deposits'
import Debts from './pages/Debts'
import BusinessOrders from './pages/BusinessOrders'
import Reports from './pages/Reports'
import Settings from './pages/Settings'
import Users from './pages/Users'

export default function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
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

            {/* Loko Express */}
            <Route path="sales" element={<Sales />} />
            <Route path="express/accounts" element={<Accounts module="EXPRESS" />} />

            {/* Loko Business */}
            <Route path="business/accounts" element={<Accounts module="BUSINESS" />} />
            <Route path="business/orders" element={<BusinessOrders />} />
            <Route path="business/transfers" element={<Transfers module="BUSINESS" />} />
            <Route path="business/deposits" element={<Deposits />} />
            <Route path="business/debts" element={<Debts />} />

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
          </Route>

          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  )
}
