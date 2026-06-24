import { Navigate, useLocation } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'
import { Spinner } from './ui'

export default function ProtectedRoute({ children, adminOnly = false }) {
  const { isAuthenticated, isAdmin, loading } = useAuth()
  const location = useLocation()

  if (loading) return <Spinner full />
  if (!isAuthenticated) return <Navigate to="/login" state={{ from: location }} replace />
  if (adminOnly && !isAdmin) return <Navigate to="/" replace />

  return children
}
