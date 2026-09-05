import { useEffect, useMemo, useState } from 'react'
import api, { errorMessage } from '../api/client'
import { useFetch, asList } from '../lib/hooks'
import { prompt } from '../lib/dialogs'
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
  // Заявка клиента (QR) без сотрудника: кому засчитать — сотрудники филиала заявки.
  const [operators, setOperators] = useState([])
  const [operatorId, setOperatorId] = useState('')

  const dayParams = useMemo(
    () => ({ active_items: 1, ...(search.trim() ? { search: search.trim() } : {}) }),
    [search],
  )
  const dayReq = useFetch('/warehouse-orders/', dayParams)
  // Вечерний допоиск: всё, что днём не нашли (не найдено складом + убрано оператором из чека).
  const eveningReq = useFetch('/warehouse-items/', { status: 'NOT_FOUND,EVENING' })
  // Ожидаемые посылки: заказы Kargoosh «в пути», сгруппированы по клиенту (заявки моста).
  const expectedParams = useMemo(
    () => ({ origin: 'KARGO', active: 1, ...(search.trim() ? { search: search.trim() } : {}) }),
    [search],
  )
  const expectedReq = useFetch('/warehouse-orders/', expectedParams)
  const accounts = asList(useFetch('/warehouse-items/accounts/').data)
  // Остаток веса на складе своего филиала (ведёт директор) — только чтение.
  const stock = useFetch(isWarehouse && userBranchName ? '/warehouse-stock/summary/' : null, {})

  const orders = asList(dayReq.data)
  const evening = asList(eveningReq.data)
  const expected = asList(expectedReq.data)
  const expectedTotal = expectedReq.data?.count ?? expected.length

  // Авто-обновление обеих лент (near-real-time без WebSocket).
  useEffect(() => {
    const t = setInterval(() => { dayReq.reload(); eveningReq.reload(); expectedReq.reload() }, POLL_MS)
    return () => clearInterval(t)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dayReq.reload, eveningReq.reload, expectedReq.reload])

  function openReceive(item) {
    setError('')
    setReceiveItem(item)
    setWeight('')
    setTracking(item.tracking_number || '')
    setOperators([])
    setOperatorId('')
    if (!item.created_by) {
      api.get('/warehouse-items/operators/', { params: isWarehouse ? {} : { branch: item.branch } })
        .then((res) => {
          const list = res.data || []
          setOperators(list)
          if (list.length === 1) setOperatorId(String(list[0].id))
        })
        .catch(() => setOperators([]))
    }
    const def = accounts.find((a) => a.kind === 'CASH') || accounts[0]
    setAccountId(def ? String(def.id) : '')
  }

  async function submitReceive(e) {
    e?.preventDefault?.()
    if (!receiveItem) return
    if (!(parseFloat(weight) > 0)) { setError('Укажите вес больше нуля.'); return }
    if (!accountId) { setError('Выберите счёт зачисления.'); return }
    if (!receiveItem.created_by && !operatorId) { setError('Выберите сотрудника, кому засчитать заявку клиента.'); return }
    setBusyId(receiveItem.id)
    setError('')
    try {
      await api.post(`/warehouse-items/${receiveItem.id}/receive/`, {
        weight_kg: weight, account: accountId, tracking_number: tracking.trim(),
        ...(operatorId ? { operator: operatorId } : {}),
      })
      setReceiveItem(null)
      dayReq.reload(); eveningReq.reload(); expectedReq.reload()
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setBusyId(null)
    }
  }

  async function markNotFound(item) {
    const reason = await prompt({
      title: `Не найдено · ${item.client_code}`, label: 'Что не найдено / где искали', okLabel: 'Отметить «не найдено»',
      hint: 'Позиция уйдёт во вкладку «Вечерний допоиск», сотрудник увидит причину', placeholder: 'например: нет на полках Б-3, Б-4',
    })
    if (!reason) return
    setBusyId(item.id)
    setError('')
    try {
      await api.post(`/warehouse-items/${item.id}/not-found/`, { reason: reason.trim() })
      dayReq.reload(); eveningReq.reload(); expectedReq.reload()
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
          {isWarehouse && stock.data && (
            <div className="wh-stock">
              {stock.data.since ? (
                <>
                  <span className="wh-stock-lbl">На складе сейчас</span>
                  <strong className={`wh-stock-val ${parseFloat(stock.data.balance_kg) < 0 ? 'neg' : ''}`}>{kg(stock.data.balance_kg)}</strong>
                  <span className="muted">учёт с {stock.data.since.split('-').reverse().join('.')} · приход вносит директор, расход считается по оприходованному весу</span>
                </>
              ) : (
                <>
                  <span className="wh-stock-lbl">На складе сейчас</span>
                  <strong className="wh-stock-val muted">—</strong>
                  <span className="muted">учёт веса ещё не начат: директор вносит первый приход в разделе «Остаток на складе»</span>
                </>
              )}
            </div>
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
        <button className={`wh-tab ${tab === 'expected' ? 'active' : ''}`} onClick={() => setTab('expected')}>
          Ожидаются
          {expectedTotal > 0 && <span className="wh-tab-badge">{expectedTotal}</span>}
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
      ) : tab === 'expected' ? (
        expectedReq.loading && !expected.length ? (
          <Spinner full />
        ) : !expected.length ? (
          <div className="wh-empty-box">
            {search.trim() ? 'По этому коду ожидаемых посылок нет.' : 'Ожидаемых посылок нет: сайт kargoosh.kg не сообщал о новых отправках за последние 30 дней.'}
          </div>
        ) : (
          <>
            <p className="muted" style={{ margin: '0 0 8px' }}>
              Посылки, о которых сообщил kargoosh.kg («в пути»). Когда приедут, оприходуйте здесь, запись не задвоится.
              {expectedTotal > expected.length && ` Показаны ${expected.length} клиентов из ${expectedTotal}, уточните поиск по коду.`}
            </p>
            <div className="wh-orders">
              {expected.map((o) => (
                <OrderCard key={o.id} order={o} showBranch={!isWarehouse} {...itemProps} />
              ))}
            </div>
          </>
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
          {!receiveItem.created_by && (
            <Field label="Кому засчитать" hint="Заявка пришла от клиента по QR — закрепите за сотрудником филиала">
              {operators.length ? (
                <select className="select" value={operatorId} onChange={(e) => setOperatorId(e.target.value)}>
                  <option value="">Выберите сотрудника…</option>
                  {operators.map((o) => <option key={o.id} value={o.id}>{o.name}</option>)}
                </select>
              ) : (
                <div className="caption" style={{ color: 'var(--error)' }}>
                  В этом филиале нет сотрудников с ролью «Сотрудник». Добавьте их в «Пользователи» и привяжите к филиалу.
                </div>
              )}
            </Field>
          )}
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
        {order.created_by_name
          ? <span className="muted">🧑 {order.created_by_name}</span>
          : <span className="wh-item-branch" title="Заявка от клиента по QR, сотрудник ещё не закреплён">от клиента · без сотрудника</span>}
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
        {item.tracking_number && <span className="wh-track">{item.tracking_number}</span>}
        {item.status === 'EXPECTED' && item.shipment_date && (
          <span className="muted">отправлено {item.shipment_date.split('-').reverse().join('.')}</span>
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
          {item.status !== 'EXPECTED' && (
            <button
              className="btn btn-ghost btn-sm"
              disabled={busyId === item.id}
              onClick={() => onNotFound(item)}
            >
              Не найдено
            </button>
          )}
        </div>
      )}
    </div>
  )
}
