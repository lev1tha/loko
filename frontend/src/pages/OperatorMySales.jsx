import { useCallback, useEffect, useState } from 'react'
import api, { errorMessage } from '../api/client'
import { som, kg, dateTimeRu } from '../lib/format'
import { Alert } from '../components/ui'
import { LoadingTruck } from '../components/states'

// Страница роли «Сотрудник»: его собственные продажи (все, новые сверху) +
// выгрузка в Excel. Финансовых полей (себестоимость/маржа) бэкенд не отдаёт —
// только то, что сотрудник и так видел при создании (код, вес, кол-во, сумма).
export default function OperatorMySales() {
  const [data, setData] = useState({ count: 0, total_som: 0, results: [] })
  const [loading, setLoading] = useState(true)
  const [exporting, setExporting] = useState(false)
  const [error, setError] = useState('')

  const load = useCallback(() => {
    setLoading(true)
    api
      .get('/sales/mine/')
      .then((res) => setData(res.data))
      .catch((err) => {
        setError(errorMessage(err))
        setData({ count: 0, total_som: 0, results: [] })
      })
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => {
    load()
  }, [load])

  // Выгрузка в Excel (.xlsx с бэкенда). JWT идёт в заголовке, поэтому качаем
  // через axios как blob, а не простой ссылкой.
  async function exportXlsx() {
    setError('')
    setExporting(true)
    try {
      const res = await api.get('/sales/mine/', {
        params: { export: 'xlsx' },
        responseType: 'blob',
      })
      const url = URL.createObjectURL(res.data)
      const a = document.createElement('a')
      a.href = url
      a.download = 'moi-prodazhi.xlsx'
      document.body.appendChild(a)
      a.click()
      a.remove()
      URL.revokeObjectURL(url)
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setExporting(false)
    }
  }

  if (loading) return <LoadingTruck />

  return (
    <div className="operator-card card">
      <div className="operator-sales-head">
        <div>
          <h2 className="card-title">Мои продажи</h2>
          <p className="muted operator-sales-sub">
            За текущий месяц
            {data.count > 0 && ` · ${data.count} шт · ${som(data.total_som)}`}
          </p>
        </div>
        <button
          type="button"
          className="btn btn-secondary btn-sm"
          onClick={exportXlsx}
          disabled={exporting || !data.results.length}
        >
          {exporting ? 'Выгрузка…' : 'Excel'}
        </button>
      </div>

      {error && <Alert kind="error">{error}</Alert>}

      {!data.results.length ? (
        <p className="muted" style={{ margin: 0 }}>В этом месяце продаж пока нет.</p>
      ) : (
        <div className="operator-sales">
          {data.results.map((s) => (
            <div key={s.id} className="operator-sales-row">
              <div className="operator-sales-main">
                <span className="operator-sales-code">{s.client_code}</span>
                <span className="operator-sales-meta">
                  {dateTimeRu(s.created_at)}
                  {s.weight_kg ? ` · ${kg(s.weight_kg)}` : ''} · {s.places} шт · {s.account_name}
                </span>
              </div>
              <span className="operator-sales-sum">{som(s.price_som)}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
