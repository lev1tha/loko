import { useCallback, useEffect, useRef, useState } from 'react'
import api, { errorMessage } from '../api/client'
import './ClientApp.css'

const MAX = 5
const FOUND = new Set(['FOUND', 'DELIVERED'])
const PHONE_KEY = 'loko_client_phone'
const NAME_KEY = 'loko_client_name'

// Контурные SVG-иконки (без эмодзи), наследуют цвет через currentColor.
const svg = (p) => (
  <svg className="gi" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">{p}</svg>
)
const IC = {
  pin: svg(<><path d="M12 21s-6.5-5.8-6.5-10.5a6.5 6.5 0 1 1 13 0C18.5 15.2 12 21 12 21z" /><circle cx="12" cy="10.3" r="2.3" /></>),
  gift: svg(<><rect x="4" y="9" width="16" height="11.5" rx="1.4" /><path d="M4 13h16M12 9v11.5" /><path d="M12 9c-1.1-2.9-4.6-2.7-4.6-.8C7.4 9 9.7 9 12 9zM12 9c1.1-2.9 4.6-2.7 4.6-.8C16.6 9 14.3 9 12 9z" /></>),
  box: svg(<><path d="M20.5 8L12 3.5 3.5 8 12 12.5 20.5 8z" /><path d="M3.5 8v8L12 20.5 20.5 16V8" /><path d="M12 12.5v8" /></>),
  warehouse: svg(<><path d="M3.5 20.5V9L12 4l8.5 5v11.5" /><path d="M3.5 20.5h17" /><rect x="8.6" y="13.6" width="6.8" height="6.9" /></>),
  check: svg(<path d="M20 6.5L9.2 17.3 4 12.1" />),
  weight: svg(<><circle cx="12" cy="6" r="2.4" /><path d="M8.4 8.4h7.2l1.9 10.8a1 1 0 0 1-1 1.3H7.5a1 1 0 0 1-1-1.3L8.4 8.4z" /></>),
  clock: svg(<><circle cx="12" cy="12" r="8.5" /><path d="M12 7.5V12l3 1.8" /></>),
  star: svg(<path d="M12 3.4l2.65 5.37 5.93.86-4.29 4.18 1.01 5.9L12 17.8l-5.3 2.79 1.01-5.9L3.42 9.63l5.93-.86L12 3.4z" />),
}
const initials = (n) => (n || '?').trim().split(/\s+/).slice(0, 2).map((w) => w[0]).join('').toUpperCase()
const fmt = (n) => new Intl.NumberFormat('ru-RU').format(Number(n) || 0)
const kg = (n) => `${Number(n).toLocaleString('ru-RU')} кг`
const som = (n) => `${fmt(Number(n).toFixed(2))} с`

// Публичная клиентская страница (по QR, без входа). Клиент вводит телефон, вписывает
// коды посылок и следит за статусом/ценой. Ветку определяет ?b= из QR.
export default function ClientApp() {
  const params = new URLSearchParams(window.location.search)
  const branchId = params.get('b') || ''
  const [branchName, setBranchName] = useState('')

  const [phone, setPhone] = useState(localStorage.getItem(PHONE_KEY) || '')
  const [name, setName] = useState(localStorage.getItem(NAME_KEY) || '')
  const [entered, setEntered] = useState(!!localStorage.getItem(PHONE_KEY))

  const [track, setTrack] = useState(null)   // { found, client, bonus, items }
  const [inputs, setInputs] = useState([''])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [toast, setToast] = useState('')
  const phoneRef = useRef(null)

  // Имя филиала из QR-метки.
  useEffect(() => {
    api.get('/public/branches/')
      .then((r) => {
        const b = (r.data || []).find((x) => String(x.id) === String(branchId))
        setBranchName(b ? b.name : '')
      })
      .catch(() => {})
  }, [branchId])

  const loadTrack = useCallback((ph) => {
    const digits = String(ph).replace(/\D/g, '')
    if (digits.length < 6) return
    api.get('/public/track/', { params: { phone: ph } })
      .then((r) => setTrack(r.data))
      .catch(() => {})
  }, [])

  useEffect(() => { if (entered && phone) loadTrack(phone) }, [entered, phone, loadTrack])
  useEffect(() => {
    if (!entered || !phone) return
    const t = setInterval(() => loadTrack(phone), 7000)
    return () => clearInterval(t)
  }, [entered, phone, loadTrack])

  function showToast(t) {
    setToast(t)
    setTimeout(() => setToast(''), 2400)
  }

  function enter(e) {
    e.preventDefault()
    if (String(phone).replace(/\D/g, '').length < 6) {
      setError('Введите номер телефона.'); phoneRef.current?.focus(); return
    }
    localStorage.setItem(PHONE_KEY, phone)
    localStorage.setItem(NAME_KEY, name.trim())
    setError(''); setEntered(true); loadTrack(phone)
  }

  function reset() {
    localStorage.removeItem(PHONE_KEY); localStorage.removeItem(NAME_KEY)
    setEntered(false); setPhone(''); setTrack(null); setInputs([''])
  }

  const codes = [...new Set(inputs.map((c) => c.trim()).filter(Boolean))]

  const knownCode = track?.client?.code || null
  const parcels = track?.parcels || []
  const inTransit = parcels.filter((p) => p.status === 'TRANSIT').length
  const arrived = parcels.filter((p) => p.status === 'ARRIVED').length
  const [manualCodes, setManualCodes] = useState(false)

  // Клиент с сайта kargoosh.kg: код известен, вводить не нужно — одна кнопка.
  async function submitKnown() {
    setBusy(true); setError('')
    try {
      await api.post('/public/intake/', { branch: branchId, phone, name: (track?.client?.name || name || '').trim() })
      showToast('Склад ищет ваши посылки')
      loadTrack(phone)
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  async function submitCodes() {
    if (!branchId) { setError('Не указан филиал — откройте страницу по QR филиала.'); return }
    if (!codes.length) { showToast('Впишите код'); return }
    setBusy(true); setError('')
    try {
      await api.post('/public/intake/', {
        branch: Number(branchId), phone,
        name: (track?.client?.name || name || '').trim(),
        client_codes: codes,
      })
      setInputs([''])
      showToast(`Отправлено на склад: ${codes.length}`)
      loadTrack(phone)
    } catch {
      setError('Не удалось отправить. Проверьте коды и попробуйте снова.')
    } finally {
      setBusy(false)
    }
  }

  async function rate(employeeId, stars) {
    setError('')
    try {
      await api.post('/public/rate/', { phone, employee: employeeId, stars })
      showToast('Спасибо за оценку!')
      loadTrack(phone)
    } catch {
      setError('Не удалось сохранить оценку.')
    }
  }

  const maker = <span className="maker">© 2026 <span className="mf">MFPro</span> — технический отдел · Все права защищены</span>

  // ---- Экран входа по телефону ----
  if (!entered) {
    return (
      <div className="client-app">
        <TopBar branchName={branchName} />
        <div className="wrap">
          <section className="gate rise">
            <span className="kick">Отсканирован QR{branchName ? ` · ${short(branchName)}` : ''}</span>
            <h1>Заберите груз<br />без очереди</h1>
            <p className="subt">Войдите по номеру телефона — впишите коды посылок, склад соберёт заказ, а вы заберёте без очереди.</p>
            <form className="gate-card" onSubmit={enter}>
              {error && <div className="err">{error}</div>}
              <div>
                <p className="lbl">Ваш телефон</p>
                <input ref={phoneRef} className="inp" type="tel" inputMode="tel" placeholder="+996 700 12 34 56"
                  value={phone} onChange={(e) => setPhone(e.target.value)} autoComplete="tel" />
              </div>
              <div>
                <p className="lbl">Имя (если впервые)</p>
                <input className="inp" style={{ fontFamily: 'var(--font)' }} placeholder="Как вас зовут"
                  value={name} onChange={(e) => setName(e.target.value)} />
              </div>
              <button className="btn" type="submit">Войти по телефону</button>
            </form>
            <p className="gate-note">Без пароля. По номеру мы узнаём вас и храним ваши коды и бонусы.</p>
          </section>
          <footer>{maker}</footer>
        </div>
      </div>
    )
  }

  // ---- Кабинет клиента ----
  const bonus = track?.bonus || { total_kg: '0', free_kg: '0' }
  const totalKg = parseFloat(bonus.total_kg) || 0
  const freeKg = parseFloat(bonus.free_kg) || 0
  const cycle = totalKg % 20
  const items = (track?.items || []).filter((i) => i.status !== 'EXPECTED')
  const foundTotal = items.filter((i) => FOUND.has(i.status)).reduce((s, i) => s + (parseFloat(i.price_som) || 0), 0)
  const greetName = track?.client?.name || name || 'Клиент'

  return (
    <div className="client-app">
      <TopBar branchName={branchName} onExit={reset} />
      <div className="wrap">
        {error && <div className="err">{error}</div>}

        <div className="hello rise">
          <div><div className="who">Привет, {greetName}!</div><div className="ph">{phone}</div></div>
        </div>

        <section className="sec rise">
          <div className="card bonus-card">
            <div className="bonus-top">
              <div className="bonus-lbl">{IC.gift} Бонус за вес</div>
              <div className="bonus-free">{fmt(freeKg)} кг <span>бесплатно</span></div>
            </div>
            <div className="bonus-bar"><div className="bonus-fill" style={{ width: `${Math.round((cycle / 20) * 100)}%` }} /></div>
            <div className="bonus-note">За каждые 20 кг — <b>0,5 кг в подарок</b>. До следующего: <b>{fmt((20 - cycle).toFixed(1))} кг</b> (накоплено {fmt(totalKg)} кг).</div>
          </div>
        </section>

        {knownCode && !manualCodes ? (
          <section className="sec rise">
            <div className="sec-h"><h2>Ваш код клиента</h2><span className="a">с сайта kargoosh.kg</span></div>
            <div className="card" style={{ padding: 16 }}>
              <div className="known-code">{knownCode}</div>
              <div className="known-sub">
                {parcels.length
                  ? <>В пути: <b>{inTransit}</b> · На складе: <b>{arrived}</b></>
                  : 'Посылок в пути сайт пока не сообщал'}
              </div>
              <button className="btn" disabled={busy} onClick={submitKnown}>{busy ? 'Отправка…' : 'Я пришёл за посылками'}</button>
              <button type="button" className="add-more" onClick={() => setManualCodes(true)}>Сдать посылки с другим кодом</button>
            </div>
          </section>
        ) : (
        <section className="sec rise">
          <div className="sec-h"><h2>Впишите коды посылок</h2><span className="a">{codes.length}/{MAX}</span></div>
          <div className="card" style={{ padding: 16 }}>
            {inputs.map((c, i) => (
              <div className="addrow" key={i}>
                <input className="inp code-inp" value={c} placeholder="Код клиента, напр. 29520" inputMode="numeric"
                  onChange={(e) => setInputs((xs) => xs.map((x, idx) => (idx === i ? e.target.value : x)))} />
                {inputs.length > 1 && (
                  <button type="button" className="code-x" title="Убрать"
                    onClick={() => setInputs((xs) => xs.filter((_, idx) => idx !== i))}>✕</button>
                )}
              </div>
            ))}
            {inputs.length < MAX && (
              <button type="button" className="add-more" onClick={() => setInputs((xs) => [...xs, ''])}>+ Ещё код</button>
            )}
            <button className="btn" disabled={busy} onClick={submitCodes}>{busy ? 'Отправка…' : 'Отправить на склад'}</button>
            {knownCode && <button type="button" className="add-more" onClick={() => setManualCodes(false)}>← Вернуться к своему коду</button>}
          </div>
        </section>
        )}

        {parcels.length > 0 && (
          <section className="sec rise">
            <div className="sec-h"><h2>Мои посылки с сайта</h2><span className="a">по данным kargoosh.kg</span></div>
            <div className="items">
              {parcels.map((p) => (
                <div className="card parcel" key={p.tracking_number}>
                  <div className="parcel-top"><span className="parcel-track">{p.tracking_number}</span><span className={`parcel-st st-${p.status.toLowerCase()}`}>{p.status_label}</span></div>
                  <div className="parcel-sub">
                    {p.status === 'ARRIVED'
                      ? <>{p.weight_kg ? `${fmt(p.weight_kg)} кг · ` : ''}{p.price_som ? som(p.price_som) : ''}</>
                      : <>отправлено {p.shipment_date ? p.shipment_date.split('-').reverse().join('.') : '—'}</>}
                  </div>
                </div>
              ))}
            </div>
          </section>
        )}

        <section className="sec rise">
          <div className="sec-h"><h2>Мои грузы</h2><span className="a">обновляется само</span></div>
          {!items.length ? (
            <div className="card empty">Пока пусто — впишите коды выше и отправьте на склад.</div>
          ) : (
            <>
              <div className="items">{items.map((it) => <ItemCard key={it.id} item={it} />)}</div>
              {foundTotal > 0 && (
                <div className="total"><span className="k">Итого к оплате · готово к выдаче</span><span className="v">{som(foundTotal)}</span></div>
              )}
            </>
          )}
        </section>

        {track?.staff?.length > 0 && (
          <section className="sec rise">
            <div className="sec-h"><h2>Оцените обслуживание</h2><span className="a">это важно для нас</span></div>
            <div className="card rate-card">
              {track.staff.map((s) => (
                <div className="rate-row" key={s.id}>
                  <div className="ava">{initials(s.name)}</div>
                  <div className="rate-main">
                    <div className="rate-role"><span className="rl">{s.role} ·</span> {s.name}</div>
                    <div className="stars">
                      {[1, 2, 3, 4, 5].map((n) => (
                        <button key={n} type="button" className={`star-btn ${n <= (s.my_stars || 0) ? 'on' : ''}`}
                          aria-label={`Оценка ${n}`} onClick={() => rate(s.id, n)}>{IC.star}</button>
                      ))}
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </section>
        )}

        <footer>{maker}</footer>
      </div>
      {toast && <div className="toast">{toast}</div>}
    </div>
  )
}

function TopBar({ branchName, onExit }) {
  return (
    <div className="topbar">
      <div className="wrap topbar-in">
        <div className="brand"><span className="logo">L</span> Loko Express</div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          {branchName && <span className="branch-pill">{IC.pin} {short(branchName)}</span>}
          {onExit && <button className="exit" onClick={onExit}>Выйти</button>}
        </div>
      </div>
    </div>
  )
}

function ItemCard({ item }) {
  const found = FOUND.has(item.status)
  const rail = (state) => {
    const steps = [[IC.box, 'Принято'], [IC.warehouse, 'На складе'], [IC.check, 'Готов']]
    const active = state === 'found' ? 2 : 1
    return (
      <div className="rail">
        {steps.map((s, i) => {
          const cls = i < active ? 'done' : (i === active && state !== 'found' ? 'now' : (state === 'found' ? 'done' : ''))
          return <div className={`step ${cls}`} key={i}><span className="lnk" /><span className="ic">{s[0]}</span><span className="cap">{s[1]}</span></div>
        })}
      </div>
    )
  }
  if (item.status === 'NOT_FOUND') {
    return (
      <div className="item rise">
        <div className="item-top"><div className="code"><span className="l">Код</span>{item.client_code}</div>
          <span className="badge b-miss"><span className="dot" />Не найден</span></div>
        <div className="note">Код не найден. Проверьте цифры на квитанции или напишите нам в WhatsApp.</div>
      </div>
    )
  }
  if (!found) {
    return (
      <div className="item rise">
        <div className="item-top"><div className="code"><span className="l">Код</span>{item.client_code}</div>
          <span className="badge b-wait"><span className="dot" />{item.status === 'LOCATED' ? 'Нашли · взвешиваем' : 'В пути · ищем'}</span></div>
        {rail('search')}
        <div className="note">{item.status === 'LOCATED' ? 'Посылка найдена, сотрудник взвешивает — сумма появится через минуту.' : 'Груз ещё не оприходован. Обычно 1–2 дня — статус обновится сам.'}</div>
      </div>
    )
  }
  return (
    <div className="item rise">
      <div className="item-top"><div className="code"><span className="l">Код</span>{item.client_code}</div>
        <span className="badge b-ok"><span className="dot" />Готов к выдаче</span></div>
      {rail('found')}
      <div className="pay"><span className="k">К оплате при получении</span><span className="v">{fmt(Number(item.price_som).toFixed(2))} <small>сом</small></span></div>
      <div className="meta">
        {item.weight_kg && <div className="r"><span className="i">{IC.weight}</span><span>Вес:&nbsp;<b>{kg(item.weight_kg)}</b></span></div>}
        {item.branch_name && <div className="r"><span className="i">{IC.pin}</span><span>Забрать:&nbsp;<b>{short(item.branch_name)}</b></span></div>}
      </div>
    </div>
  )
}

function short(name) {
  if (!name) return ''
  const tail = String(name).includes('—') ? String(name).split('—').slice(1).join('—') : name
  return tail.replace('улица,', '').replace(/\s+/g, ' ').trim()
}
