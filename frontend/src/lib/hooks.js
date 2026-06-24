import { useCallback, useEffect, useState } from 'react'
import api from '../api/client'

// Simple GET hook with refetch + loading/error state.
export function useFetch(url, params) {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  const key = JSON.stringify(params || {})

  const reload = useCallback(() => {
    let active = true
    setLoading(true)
    api
      .get(url, { params })
      .then((res) => {
        if (active) {
          setData(res.data)
          setError(null)
        }
      })
      .catch((err) => active && setError(err))
      .finally(() => active && setLoading(false))
    return () => {
      active = false
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [url, key])

  useEffect(() => reload(), [reload])

  return { data, loading, error, reload, setData }
}

// Normalize DRF list responses (paginated {results} or plain array).
export function asList(data) {
  if (!data) return []
  if (Array.isArray(data)) return data
  return data.results || []
}
