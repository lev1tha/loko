import { useCallback, useEffect, useRef, useState } from 'react'
import api from '../api/client'

// Simple GET hook with refetch + loading/error state.
export function useFetch(url, params) {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  const key = JSON.stringify(params || {})

  const reload = useCallback(() => {
    let active = true
    // url === null → запрос не нужен (например, раздел недоступен роли).
    if (!url) {
      setLoading(false)
      return () => {}
    }
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

// Фоновое обновление ленты: тикает только пока вкладка на экране.
// Бэкенд крутится на одном ядре, а доски склада открыты весь день — опрос в
// скрытых вкладках занимал очередь и растягивал вход и любую запись.
export function usePoll(fn, ms) {
  const ref = useRef(fn)
  ref.current = fn
  useEffect(() => {
    const tick = () => {
      if (typeof document !== 'undefined' && document.hidden) return
      ref.current()
    }
    const t = setInterval(tick, ms)
    // Вернулись на вкладку — обновляем сразу, не дожидаясь тика.
    const onShow = () => {
      if (!document.hidden) ref.current()
    }
    document.addEventListener('visibilitychange', onShow)
    return () => {
      clearInterval(t)
      document.removeEventListener('visibilitychange', onShow)
    }
  }, [ms])
}

// Normalize DRF list responses (paginated {results} or plain array).
export function asList(data) {
  if (!data) return []
  if (Array.isArray(data)) return data
  return data.results || []
}
