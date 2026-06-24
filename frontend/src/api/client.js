import axios from 'axios'

const BASE_URL = import.meta.env.VITE_API_BASE_URL || '/api'

export const TOKEN_KEY = 'loko_access'
export const REFRESH_KEY = 'loko_refresh'

const api = axios.create({ baseURL: BASE_URL })

// Attach the JWT access token to every request.
api.interceptors.request.use((config) => {
  const token = localStorage.getItem(TOKEN_KEY)
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

// On 401, try a one-shot refresh; if that fails, drop the session.
let refreshing = null

api.interceptors.response.use(
  (response) => response,
  async (error) => {
    const original = error.config
    const status = error.response?.status

    const isAuthCall =
      original?.url?.includes('/auth/login') || original?.url?.includes('/auth/refresh')

    if (status === 401 && !original._retry && !isAuthCall) {
      original._retry = true
      const refresh = localStorage.getItem(REFRESH_KEY)
      if (!refresh) {
        clearSession()
        return Promise.reject(error)
      }
      try {
        if (!refreshing) {
          refreshing = axios
            .post(`${BASE_URL}/auth/refresh/`, { refresh })
            .finally(() => {
              const p = refreshing
              // reset after settle on next tick
              setTimeout(() => {
                if (refreshing === p) refreshing = null
              }, 0)
            })
        }
        const { data } = await refreshing
        localStorage.setItem(TOKEN_KEY, data.access)
        if (data.refresh) localStorage.setItem(REFRESH_KEY, data.refresh)
        original.headers.Authorization = `Bearer ${data.access}`
        return api(original)
      } catch (e) {
        clearSession()
        return Promise.reject(e)
      }
    }
    return Promise.reject(error)
  }
)

export function clearSession() {
  localStorage.removeItem(TOKEN_KEY)
  localStorage.removeItem(REFRESH_KEY)
}

export function setSession({ access, refresh }) {
  if (access) localStorage.setItem(TOKEN_KEY, access)
  if (refresh) localStorage.setItem(REFRESH_KEY, refresh)
}

// Surface a readable message from a DRF error payload.
export function errorMessage(error, fallback = 'Что-то пошло не так') {
  const data = error?.response?.data
  if (!data) return error?.message || fallback
  if (typeof data === 'string') return data
  if (data.detail) return data.detail
  const firstKey = Object.keys(data)[0]
  if (firstKey) {
    const val = data[firstKey]
    const msg = Array.isArray(val) ? val[0] : val
    return firstKey === 'non_field_errors' ? msg : `${firstKey}: ${msg}`
  }
  return fallback
}

export default api
