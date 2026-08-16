import { useCallback, useEffect, useRef, useState } from 'react'
import api, { errorMessage } from '../api/client'
import { today, dateRu, som, kg } from '../lib/format'
import { Alert, Field } from '../components/ui'
import { IconPlus } from '../components/icons'
import { useAuth } from '../auth/AuthContext'

const MAX_CODES = 5
const FOUND = new Set(['FOUND', 'DELIVERED'])

// Экран роли «Сотрудник» (двухэтапный учёт). Оператор вписывает до 5 кодов клиента
// (без веса/суммы — их определит склад). Ниже — живой список этих кодов: когда
// складовщик найдёт и взвесит товар, строка зеленеет и показывается ЦЕНА.
export default function OperatorSale() {
  const { userBranchName } = useAuth()
  const [codes, setCodes] = useState([''])
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')
  const [saving, setSaving] = useState(false)

  const [items, setItems] = useState([])
  const [loadingItems, setLoadingItems] = useState(true)
  const [busyId, setBusyId] = useState(null)
  const firstRef = useRef(null)

  // Живой список своих кодов (цена подтягивается, когда склад оприходует).
  const loadItems = useCallback(() => {
    api.get('/warehouse-items/mine/')
      .then((res) => setItems(res.data.results || []))
      .catch(() => {})
      .finally(() => setLoadingItems(false))
  }, [])
  useEffect(() => { loadItems() }, [loadItems])
  useEffect(() => {
    const t = setInterval(loadItems, 7000) // near-real-time: цена появляется сама
    return () => clearInterval(t)
  }, [loadItems])

  function setCodeAt(i, val) {
    setCodes((cs) => cs.map((c, idx) => (idx === i ? val : c)))
  }
  function addRow() {
    setCodes((cs) => (cs.length < MAX_CODES ? [...cs, ''] : cs))
  }
  function removeRow(i) {
    setCodes((cs) => (cs.length > 1 ? cs.filter((_, idx) => idx !== i) : cs))
  }

  const uniqueCodes = [...new Set(codes.map((c) => c.trim()).filter(Boolean))]

  async function submit(e) {
    e.preventDefault()
    setError('')
    setSuccess('')
    if (!userBranchName) {
      setError('Вам не назначен филиал — обратитесь к администратору.')
      return
    }
    if (!uniqueCodes.length) {
      setError('Впишите хотя бы один код клиента.')
      return
    }
    setSaving(true)
    try {
      await api.post('/warehouse-orders/', { client_codes: uniqueCodes })
      setSuccess(`Отправлено на склад: ${uniqueCodes.length}. Цена появится ниже, когда склад найдёт и взвесит.`)
      setCodes([''])
      firstRef.current?.focus()
      loadItems()
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setSaving(false)
    }
  }

  // Крестик на не найденной позиции: убрать из чека → вечерний допоиск склада.
  async function dismiss(item) {
    setBusyId(item.id)
    setError('')
    try {
      await api.post(`/warehouse-items/${item.id}/to-evening/`)
      loadItems()
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setBusyId(null)
    }
  }

  return (
    <div className="operator-card card">
      <div className="operator-card-head">
        <h2 className="card-title">Новая продажа</h2>
        <p className="muted">
          Впишите коды клиента (до {MAX_CODES}) — склад найдёт, взвесит и оприходует.
          Цена появится ниже. Дата: сегодня, {dateRu(today())}.
        </p>
      </div>

      {error && <Alert kind="error">{error}</Alert>}
      {success && <Alert kind="success">{success}</Alert>}

      <form onSubmit={submit} className="col">
        <div className="field">
          <span className="field-label">Код клиента</span>
          <div className="operator-code-rows">
            {codes.map((c, i) => (
              <div className="operator-code-row" key={i}>
                <input
                  ref={i === 0 ? firstRef : null}
                  className="input operator-code-input"
                  value={c}
                  onChange={(e) => setCodeAt(i, e.target.value)}
                  placeholder="29520"
                  autoFocus={i === 0}
                />
                {codes.length > 1 && (
                  <button
                    type="button" className="operator-code-remove"
                    title="Убрать строку" onClick={() => removeRow(i)}
                  >
                    ✕
                  </button>
                )}
              </div>
            ))}
          </div>
          {codes.length < MAX_CODES && (
            <button type="button" className="operator-add-code" onClick={addRow}>
              + Добавить код <span className="muted">({codes.length}/{MAX_CODES})</span>
            </button>
          )}
        </div>

        {userBranchName ? (
          <Field label="Филиал" hint="Заявка уйдёт в филиал, к которому вы привязаны">
            <input className="input input-readonly operator-code-input" value={userBranchName} readOnly tabIndex={-1} />
          </Field>
        ) : (
          <div className="field">
            <span className="field-label">Филиал</span>
            <Alert kind="error">
              Вам не назначен филиал. Обратитесь к администратору — без филиала заявку создать нельзя.
            </Alert>
          </div>
        )}

        <button className="btn btn-primary btn-block" disabled={saving || !userBranchName || !uniqueCodes.length} type="submit">
          <IconPlus size={18} /> {saving ? 'Отправка…' : 'Отправить на склад'}
        </button>
      </form>

      {/* Живой список кодов оператора — цена появляется, когда склад найдёт. */}
      <div className="operator-mycodes">
        <div className="operator-mycodes-head">
          <span className="field-label">Мои коды за месяц</span>
          <span className="caption muted">🟢 найдено · 🔴 не найдено · ⚪ в поиске</span>
        </div>
        {loadingItems && !items.length ? (
          <p className="muted" style={{ margin: 0 }}>Загрузка…</p>
        ) : !items.length ? (
          <p className="muted" style={{ margin: 0 }}>Пока пусто — впишите коды выше.</p>
        ) : (
          <div className="operator-sales">
            {items.map((s) => {
              const found = FOUND.has(s.status)
              return (
                <div key={s.id} className={`operator-sales-row wh-row-${s.status.toLowerCase()}`}>
                  <div className="operator-sales-main">
                    <span className="operator-sales-code">{s.client_code}</span>
                    <span className="operator-sales-meta">
                      {found
                        ? `оприходовано${s.weight_kg ? ` · ${kg(s.weight_kg)}` : ''}`
                        : s.status === 'NOT_FOUND'
                          ? `не найдено${s.reason ? ` · ${s.reason}` : ''}`
                          : s.status === 'EVENING'
                            ? 'убрано из чека · вечерний допоиск'
                            : 'в поиске'}
                    </span>
                  </div>
                  {found && <span className="operator-sales-sum">{som(s.price_som)}</span>}
                  {s.status === 'NOT_FOUND' && (
                    <button
                      type="button" className="btn btn-icon wh-remove"
                      title="Убрать из чека (в вечерний допоиск)"
                      disabled={busyId === s.id} onClick={() => dismiss(s)}
                    >
                      ✕
                    </button>
                  )}
                </div>
              )
            })}
          </div>
        )}
      </div>
    </div>
  )
}
