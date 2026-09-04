import { useEffect, useMemo, useState } from 'react'
import api, { errorMessage } from '../api/client'
import { useFetch, asList } from '../lib/hooks'
import { useAuth } from '../auth/AuthContext'
import { som, kg } from '../lib/format'
import { Alert, Field, Modal, Spinner } from '../components/ui'

const POLL_MS = 7000

// Короткое имя филиала для карточки: "Loko Express — Гульчинская улица, 13/1" → "Гульчинская, 13/1".
function shortBranch(name) {
  if (!name) return ''
  const tail = String(name).includes('—') ? String(name).split('—').slice(1).join('—') : name
  return tail.replace('улица,', '').replace(/\s+/g, ' ').trim()
}

const isFound = (s) => s === 'FOUND' || s === 'DELIVERED'

// Доска склада (двухэтапный учёт). Складовщик оприходует КАЖДЫЙ код пошту́чно:
// «Оприходовать» (вес → создаётся продажа) или «Не найдено» (причина). Вкладка
// «Вечерний допоиск» — коды, от которых оператор отказался днём (ревизия смены).
export default function WarehouseDashboard() {
  const { isWarehouse, userBranchName } = useAuth()
  const noBranch = isWarehouse && !userBranchName

  const [tab, setTab] = useState('day')
  const [search, setSearch] = useState('')
  const [error, setError] = useState('')
  const [busyId, setBusyId] = useState(null)

  // Модалка оприходования: позиция + вес + счёт зачисления.
  const [receiveItem, setReceiveItem] = useState(null)
  const [weight, setWeight] = useState('')
  const [accountId, setAccountId] = useState('')
  const [tracking, setTracking] = useState('')

  const dayParams = useMemo(
    () => ({ active_items: 1, ...(search.trim() ? { search: search.trim() } : {}) }),
    [search],
  )
  const dayReq = useFetch('/warehouse-orders/', dayParams)
  const eveningReq = useFetch('/warehouse-items/', { status: 'EVENING' })
  const accounts = asList(useFetch('/warehouse-items/accounts/').data)
  // Остаток веса на складе своего филиала (ведёт директор) — только чтение.
  const stock = useFetch(isWarehouse && userBranchName ? '/warehouse-stock/summary/' : null, {})

  const orders = asList(dayReq.data)
  const evening = asList(eveningReq.data)

  // Авто-обновление обеих лент (near-real-time без WebSocket).
  useEffect(() => {
    const t = setInterval(() => { dayReq.reload(); eveningReq.reload() }, POLL_MS)
    return () => clearInterval(t)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dayReq.reload, eveningReq.reload])

  function openReceive(item) {
    setError('')
    setReceiveItem(item)
    setWeight('')
    setTracking('')
    const def = accounts.find((a) => a.kind === 'CASH') || accounts[0]
    setAccountId(def ? String(def.id) : '')
  }

  async function submitReceive(e) {
    e?.preventDefault?.()
    if (!receiveItem) return
    if (!(parseFloat(weight) > 0)) { setError('Укажите вес больше нуля.'); return }
    if (!accountId) { setError('Выберите счёт зачисления.'); return }
    setBusyId(receiveItem.id)
    setError('')
    try {
      await api.post(`/warehouse-items/${receiveItem.id}/receive/`, {
        weight_kg: weight, account: accountId, tracking_number: tracking.trim(),
      })
      setReceiveItem(null)
      dayReq.reload(); eveningReq.reload()
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setBusyId(null)
    }
  }

  async function markNotFound(item) {
    const reason = window.prompt('Что не найдено / где искали (обязательно):', '')
    if (!reason || !reason.trim()) return
    setBusyId(item.id)
    setError('')
    try {
      await api.post(`/warehouse-items/${item.id}/not-found/`, { reason: reason.trim() })
      dayReq.reload(); eveningReq.reload()
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setBusyId(null)
    }
  }

  if (noBranch) {
    return (
      <div className="wh-page">
        <div className="wh-head"><h2 className="card-title">Склад · сборка заказов</h2></div>
        <Alert kind="error">
          Вам не назначен филиал. Обратитесь к администратору — он привяжет вас к филиалу
          в разделе «Пользователи». Без филиала заявки склада не отображаются.
        </Alert>
      </div>
    )
  }

  const itemProps = { busyId, onReceive: openReceive, onNotFound: markNotFound }

  return (
    <div className="wh-page">
      {error && <Alert kind="error">{error}</Alert>}

      <div className="wh-head">
        <div>
          <h2 className="card-title">Склад · сборка заказов</h2>
          <p className="muted" style={{ margin: '2px 0 0' }}>
            {isWarehouse ? 'Заявки вашего филиала' : 'Все филиалы'} · обновляется автоматически
          </p>
          {stock.data?.since && (
            <p style={{ margin: '6px 0 0', fontSize: 14 }}>
              На складе сейчас: <strong>{kg(stock.data.balance_kg)}</strong>
              <span className="muted"> · учёт с {stock.data.since.split('-').reverse().join('.')}</span>
            </p>
          )}
        </div>
        <div className="row gap-sm wh-head-actions">
          <input
            className="input"
            placeholder="Поиск по коду клиента…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            style={{ maxWidth: 220 }}
          />
        </div>
      </div>

      <div className="wh-tabs">
        <button className={`wh-tab ${tab === 'day' ? 'active' : ''}`} onClick={() => setTab('day')}>
          Дневная сборка
        </button>
        <button className={`wh-tab ${tab === 'evening' ? 'active' : ''}`} onClick={() => setTab('evening')}>
          Вечерний допоиск
          {evening.length > 0 && <span className="wh-tab-badge">{evening.length}</span>}
        </button>
      </div>

      {tab === 'day' ? (
        dayReq.loading && !orders.length ? (
          <Spinner full />
        ) : !orders.length ? (
          <div className="wh-empty-box">Нет заявок в работе — всё оприходовано.</div>
        ) : (
          <div className="wh-orders">
            {orders.map((o) => (
              <OrderCard key={o.id} order={o} showBranch={!isWarehouse} {...itemProps} />
            ))}
          </div>
        )
      ) : eveningReq.loading && !evening.length ? (
        <Spinner full />
      ) : !evening.length ? (
        <div className="wh-empty-box">Вечерний допоиск пуст — отказов нет.</div>
      ) : (
        <div className="card wh-order">
          <div className="wh-order-head">
            <strong>Вечерний допоиск / ревизия</strong>
            <span className="muted">коды, от которых отказались днём — перепроверьте</span>
          </div>
          <div className="wh-items">
            {evening.map((it) => (
              <ItemRow key={it.id} item={it} showBranch={!isWarehouse} {...itemProps} />
            ))}
          </div>
        </div>
      )}

      {receiveItem && (
        <Modal
          title={`Оприходовать · ${receiveItem.client_code}`}
          onClose={() => setReceiveItem(null)}
          footer={
            <>
              <button className="btn btn-secondary" onClick={() => setReceiveItem(null)}>Отмена</button>
              <button className="btn btn-primary" disabled={busyId === receiveItem.id} onClick={submitReceive}>
                {busyId === receiveItem.id ? 'Сохранение…' : 'Оприходовать'}
              </button>
            </>
          }
        >
          <p className="caption" style={{ margin: 0, lineHeight: 1.5 }}>
            Введите фактический вес — сумма посчитается по тарифу и создастся продажа.
          </p>
          <Field label="Фактический вес, кг">
            <input
              className="input" type="number" step="0.001" min="0"
              value={weight} onChange={(e) => setWeight(e.target.value)}
              placeholder="5" autoFocus
            />
          </Field>
          <Field label="Трек-номер посылки" hint="Необязательно. Клиент увидит его в кабинете kargoosh.kg">
            <input
              className="input" value={tracking} onChange={(e) => setTracking(e.target.value)}
              placeholder="YT8872477816368"
            />
          </Field>
          <Field label="Счёт зачисления (нал/безнал)">
            <select className="select" value={accountId} onChange={(e) => setAccountId(e.target.value)}>
              {accounts.map((a) => (
                <option key={a.id} value={a.id}>
                  {a.name} ({a.kind === 'CASH' ? 'наличные' : 'безнал'})
                </option>
              ))}
            </select>
          </Field>
        </Modal>
      )}
    </div>
  )
}

// Карточка заявки-«чека»: коды одного клиента с их статусами и действиями.
function OrderCard({ order, showBranch, ...itemProps }) {
  const items = order.items || []
  return (
    <div className="card wh-order">
      <div className="wh-order-head">
        <span className="wh-order-id">#{order.id}</span>
        {showBranch && order.branch_name && (
          <span className="wh-item-branch">{shortBranch(order.branch_name)}</span>
        )}
        {order.created_by_name && <span className="muted">🧑 {order.created_by_name}</span>}
      </div>
      <div className="wh-items">
        {items.map((it) => (
          <ItemRow key={it.id} item={it} showBranch={false} {...itemProps} />
        ))}
      </div>
    </div>
  )
}

// Строка позиции: код + статус + действия (оприходовать / не найдено) либо сумма.
function ItemRow({ item, showBranch, busyId, onReceive, onNotFound }) {
  const found = isFound(item.status)
  return (
    <div className={`wh-item wh-row-${item.status.toLowerCase()}`}>
      <div className="wh-item-main">
        <span className="wh-code">{item.client_code}</span>
        <span className={`wh-status wh-status-${item.status.toLowerCase()}`}>{item.status_display}</span>
        {showBranch && item.branch_name && (
          <span className="wh-item-branch">{shortBranch(item.branch_name)}</span>
        )}
        {item.status === 'NOT_FOUND' && item.reason && (
          <span className="wh-item-reason">💬 {item.reason}</span>
        )}
      </div>

      {found ? (
        <div className="wh-item-fin">
          {item.weight_kg && <span className="muted">{kg(item.weight_kg)}</span>}
          <strong>{som(item.price_som)}</strong>
        </div>
      ) : (
        <div className="wh-item-actions">
          <button
            className="btn btn-primary btn-sm"
            disabled={busyId === item.id}
            onClick={() => onReceive(item)}
          >
            Оприходовать
          </button>
          <button
            className="btn btn-ghost btn-sm"
            disabled={busyId === item.id}
            onClick={() => onNotFound(item)}
          >
            Не найдено
          </button>
        </div>
      )}
    </div>
  )
}
