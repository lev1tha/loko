import { useEffect, useState } from 'react'
import api, { errorMessage } from '../api/client'
import { useFetch, asList } from '../lib/hooks'
import { useAuth } from '../auth/AuthContext'
import { Alert, Spinner } from '../components/ui'
import WarehouseOrderForm from '../components/WarehouseOrderForm'

// Колонки канбан-доски (активные статусы). ISSUED/CANCELLED скрыты (active=1).
const COLUMNS = [
  { key: 'NEW', label: 'Новые', sub: 'в очереди' },
  { key: 'IN_PROGRESS', label: 'В поиске', sub: 'собираются' },
  { key: 'READY', label: 'Готовы к выдаче', sub: 'ждут клиента' },
]
const POLL_MS = 7000

// Короткое имя филиала для карточки: "Loko Express — Гульчинская улица, 13/1" → "Гульчинская, 13/1".
function shortBranch(name) {
  if (!name) return ''
  const tail = String(name).includes('—') ? String(name).split('—').slice(1).join('—') : name
  return tail.replace('улица,', '').replace(/\s+/g, ' ').trim()
}

// Доска склада: складовщик ведёт заявки своего филиала по статусам; менеджер/админ
// видят все филиалы, создают заявки и «выдают». Авто-обновление (polling ~7с).
export default function WarehouseDashboard() {
  const { isWarehouse } = useAuth()
  const canCreate = !isWarehouse // заявки создают оператор/менеджер/админ, не складовщик
  const canIssue = !isWarehouse // «Выдать» — кассир/менеджер/админ (после оплаты)

  const [search, setSearch] = useState('')
  const [showCreate, setShowCreate] = useState(false)
  const [busyId, setBusyId] = useState(null)
  const [error, setError] = useState('')

  const params = { active: 1, ...(search.trim() ? { search: search.trim() } : {}) }
  const req = useFetch('/warehouse-orders/', params)
  const branchesReq = useFetch('/branches/', { active: 1 })
  const orders = asList(req.data)

  // Авто-обновление (polling) — near-real-time без WebSocket.
  useEffect(() => {
    const t = setInterval(() => req.reload(), POLL_MS)
    return () => clearInterval(t)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [req.reload])

  async function changeStatus(order, status) {
    let comment
    if (status === 'CANCELLED') {
      comment = window.prompt('Причина отмены (обязательно):', '')
      if (!comment || !comment.trim()) return
    }
    setBusyId(order.id)
    setError('')
    try {
      await api.patch(`/warehouse-orders/${order.id}/status/`, {
        status,
        ...(comment ? { comment: comment.trim() } : {}),
      })
      req.reload()
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setBusyId(null)
    }
  }

  const byStatus = (k) => orders.filter((o) => o.status === k)
  const readyCount = byStatus('READY').length

  return (
    <div className="wh-page">
      {error && <Alert kind="error">{error}</Alert>}

      <div className="wh-head">
        <div>
          <h2 className="card-title">Склад · сборка заказов</h2>
          <p className="muted" style={{ margin: '2px 0 0' }}>
            {isWarehouse ? 'Заявки вашего филиала' : 'Все филиалы'} · обновляется автоматически
            {readyCount > 0 && <> · <strong className="pos">{readyCount} готово к выдаче</strong></>}
          </p>
        </div>
        <div className="row gap-sm wh-head-actions">
          <input
            className="input"
            placeholder="Поиск по коду клиента…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            style={{ maxWidth: 220 }}
          />
          {canCreate && (
            <button className="btn btn-primary" onClick={() => setShowCreate((v) => !v)}>
              {showCreate ? 'Закрыть' : '+ Новая заявка'}
            </button>
          )}
        </div>
      </div>

      {canCreate && showCreate && (
        <div className="card" style={{ marginBottom: 16, maxWidth: 520 }}>
          <WarehouseOrderForm
            showBranch
            branches={asList(branchesReq.data)}
            onCreated={() => { setShowCreate(false); req.reload() }}
          />
        </div>
      )}

      {req.loading && !orders.length ? (
        <Spinner full />
      ) : (
        <div className="wh-board">
          {COLUMNS.map((col) => {
            const items = byStatus(col.key)
            return (
              <section key={col.key} className={`wh-col wh-col-${col.key.toLowerCase()}`}>
                <header className="wh-col-head">
                  <span className="wh-col-label">{col.label}</span>
                  <span className="wh-col-count">{items.length}</span>
                </header>
                <div className="wh-col-sub">{col.sub}</div>
                <div className="wh-col-body">
                  {items.length === 0 ? (
                    <div className="wh-empty">пусто</div>
                  ) : (
                    items.map((o) => (
                      <WhCard
                        key={o.id}
                        order={o}
                        busy={busyId === o.id}
                        onChange={changeStatus}
                        canIssue={canIssue}
                        showBranch={!isWarehouse}
                      />
                    ))
                  )}
                </div>
              </section>
            )
          })}
        </div>
      )}
    </div>
  )
}

function WhCard({ order, busy, onChange, canIssue, showBranch }) {
  const codes = order.client_codes || []
  return (
    <article className={`wh-card wh-card-${order.status.toLowerCase()}`}>
      <div className="wh-card-top">
        <span className="wh-card-id">#{order.id}</span>
        {showBranch && order.branch_name && <span className="wh-card-branch">{shortBranch(order.branch_name)}</span>}
      </div>
      <div className="wh-codes">
        {codes.map((c, i) => <span key={i} className="wh-code">{c}</span>)}
      </div>
      {order.comment && <div className="wh-comment">💬 {order.comment}</div>}
      {order.assigned_to_name && <div className="wh-assigned">🧑‍🔧 {order.assigned_to_name}</div>}

      <div className="wh-actions">
        {order.status === 'NEW' && (
          <button className="btn btn-primary btn-block" disabled={busy} onClick={() => onChange(order, 'IN_PROGRESS')}>
            Взять в поиск
          </button>
        )}
        {order.status === 'IN_PROGRESS' && (
          <>
            <button className="btn btn-primary btn-block wh-btn-ready" disabled={busy} onClick={() => onChange(order, 'READY')}>
              Готова к выдаче
            </button>
            <button className="btn btn-ghost btn-sm" disabled={busy} onClick={() => onChange(order, 'CANCELLED')}>
              Отмена
            </button>
          </>
        )}
        {order.status === 'READY' && (
          <>
            {canIssue && (
              <button className="btn btn-primary btn-block" disabled={busy} onClick={() => onChange(order, 'ISSUED')}>
                Выдать клиенту
              </button>
            )}
            <button className="btn btn-ghost btn-sm" disabled={busy} onClick={() => onChange(order, 'CANCELLED')}>
              Отмена
            </button>
          </>
        )}
      </div>
    </article>
  )
}
