import { useCallback, useEffect, useState } from 'react'
import api, { errorMessage } from '../api/client'
import { som } from '../lib/format'
import { Alert, Segmented } from '../components/ui'
import { LoadingTruck } from '../components/states'
import { OperatorItemRow, ReceiveModal } from '../components/OperatorItems'

// Позиции найдены и оприходованы складом (в чеке клиента, с суммой).
const FOUND = new Set(['FOUND', 'DELIVERED'])
const PERIODS = [
  { value: 'month', label: 'Этот месяц' },
  { value: 'prev', label: 'Прошлый' },
  { value: 'all', label: 'Всё время' },
]
const PERIOD_LABEL = { month: 'За текущий месяц', prev: 'За прошлый месяц', all: 'За всё время' }

// Страница роли «Сотрудник»: свои позиции (коды) за текущий месяц с подсветкой
// статуса склада. 🟢 найдено (вес + сумма) · 🔴 не найдено (можно убрать из чека
// крестиком → вечерний допоиск) · ⚪ в поиске · вечерний допоиск (убрано из чека).
export default function OperatorMySales() {
  const [data, setData] = useState({ count: 0, results: [] })
  const [loading, setLoading] = useState(true)
  const [busyId, setBusyId] = useState(null)
  const [receiveItem, setReceiveItem] = useState(null)
  const [error, setError] = useState('')
  const [period, setPeriod] = useState('month') // month | prev | all

  const load = useCallback(() => {
    setLoading(true)
    api
      .get('/warehouse-items/mine/', { params: { period } })
      .then((res) => setData(res.data))
      .catch((err) => {
        setError(errorMessage(err))
        setData({ count: 0, results: [] })
      })
      .finally(() => setLoading(false))
  }, [period])

  useEffect(() => {
    load()
  }, [load])

  // Крестик: убрать не найденную позицию из чека клиента → вечерний допоиск склада.
  async function dismiss(item) {
    setBusyId(item.id)
    setError('')
    try {
      await api.post(`/warehouse-items/${item.id}/to-evening/`)
      load()
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setBusyId(null)
    }
  }

  if (loading) return <LoadingTruck />

  const rows = data.results || []
  // Сумма к оплате клиентом = только найденное (оприходованное).
  const totalFound = rows
    .filter((r) => FOUND.has(r.status))
    .reduce((sum, r) => sum + (parseFloat(r.price_som) || 0), 0)

  return (
    <div className="operator-card card">
      <div className="operator-sales-head">
        <div>
          <h2 className="card-title">Мои продажи</h2>
          <p className="muted operator-sales-sub">
            {PERIOD_LABEL[period]}
            {rows.length > 0 && ` · ${rows.length} позиций · к оплате ${som(totalFound)}`}
          </p>
        </div>
        <Segmented value={period} onChange={setPeriod} options={PERIODS} />
      </div>

      {error && <Alert kind="error">{error}</Alert>}

      {!rows.length ? (
        <p className="muted" style={{ margin: 0 }}>В этом месяце заявок пока нет.</p>
      ) : (
        <div className="operator-sales">
          {rows.map((it) => (
            <OperatorItemRow key={it.id} item={it} busyId={busyId} onReceive={setReceiveItem} onDismiss={dismiss} />
          ))}
        </div>
      )}
      {receiveItem && (
        <ReceiveModal item={receiveItem} onClose={() => setReceiveItem(null)} onDone={() => { setReceiveItem(null); load() }} />
      )}
    </div>
  )
}
