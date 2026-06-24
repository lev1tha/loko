import { createContext, useContext, useEffect, useState } from 'react'
import api, { clearSession, setSession, TOKEN_KEY } from '../api/client'

const AuthContext = createContext(null)

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null)
  const [loading, setLoading] = useState(true)

  // Restore session on first load by validating the stored token via /me.
  useEffect(() => {
    const token = localStorage.getItem(TOKEN_KEY)
    if (!token) {
      setLoading(false)
      return
    }
    api
      .get('/users/me/')
      .then((res) => setUser(res.data))
      .catch(() => {
        clearSession()
        setUser(null)
      })
      .finally(() => setLoading(false))
  }, [])

  async function login(username, password) {
    const { data } = await api.post('/auth/login/', { username, password })
    setSession({ access: data.access, refresh: data.refresh })
    setUser(data.user)
    return data.user
  }

  function logout() {
    clearSession()
    setUser(null)
  }

  const value = {
    user,
    loading,
    login,
    logout,
    isAuthenticated: !!user,
    isAdmin: !!user?.is_admin,
  }

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth() {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used within AuthProvider')
  return ctx
}
