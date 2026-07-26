import { useEffect } from 'react'
import { useFetch, asList } from '../lib/hooks'
import { dateTimeRu } from '../lib/format'
import { Badge } from '../components/ui'
import WarehouseOrderForm from '../components/WarehouseOrderForm'

const STATUS_VARIANT = {
  NEW: 'badge-manager',
  IN_PROGRESS: 'badge-bank',
  READY: 'badge-success',
  ISSUED: 'badge-admin',
  CANCELLED: 'badge-danger',
}

// Страница роли «Сотрудник»: сформировать заявку на сборку (1–5 кодов) и видеть
// статус своих заявок (филиал проставляется сервером). Обновляется автоматически.
export default function OperatorWarehouse() {
  const req = useFetch('/warehouse-orders/', { active: 1 })
  const orders = asList(req.data)

  useEffect(() => {
    const t = setInterval(() => req.reload(), 8000)
    return () => clearInterval(t)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [req.reload])

  return (
    <div className="operator-card card">
      <div className="operator-card-head">
        <h2 className="card-title">Заявка на сборку (склад)</h2>
        <p className="muted">Соберите заявку из 1–5 кодов клиентов — складовщик увидит её сразу.</p>
      </div>

      <WarehouseOrderForm onCreated={() => req.reload()} />

      <div style={{ marginTop: 20 }}>
        <div className="card-title" style={{ fontSize: 15, marginBottom: 8 }}>Активные заявки филиала</div>
        {orders.length === 0 ? (
          <p className="muted" style={{ margin: 0 }}>Активных заявок нет.</p>
        ) : (
          <div className="col" style={{ gap: 8 }}>
            {orders.map((o) => (
              <div key={o.id} className="wh-mini-row">
                <div className="wh-codes">
                  {(o.client_codes || []).map((c, i) => <span key={i} className="wh-code">{c}</span>)}
                </div>
                <Badge variant={STATUS_VARIANT[o.status] || 'badge-manager'}>{o.status_display}</Badge>
                <span className="caption muted">{dateTimeRu(o.created_at)}</span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
