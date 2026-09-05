import { useMemo, useState } from 'react'
import { useAuth } from '../auth/AuthContext'
import api, { errorMessage } from '../api/client'
import { useFetch, asList } from '../lib/hooks'
import { confirm } from '../lib/dialogs'
import { money, today, dateRu, firstOfMonth } from '../lib/format'
import { Alert, Field, Segmented } from '../components/ui'
import '../director.css'

const DIRECTIONS = [
  { value: 'EXPRESS', label: 'Loko Express' },
  { value: 'BUSINESS', label: 'Loko Business' },
]

// Три раздела расходов директора → категория/статья Loko.
const SECTIONS = [
  { value: 'OPERATING', label: 'Операционный' },
  { value: 'INVESTING', label: 'Инвестиционный' },
  { value: 'FINANCING', label: 'Финансовый' },
]
const ITEMS = {
  OPERATING: [
    { key: 'RENT', label: 'Аренда помещения', category: 'OPEX', article: 'RENT' },
    { key: 'INCOME_TAX', label: 'Подоходный налог', category: 'OPEX', article: 'INCOME_TAX' },
    { key: 'PAYROLL', label: 'Зарплата сотрудникам', category: 'OPEX', article: 'PAYROLL', employee: true },
  ],
  INVESTING: [
    { key: 'REPAIR', label: 'Ремонт', category: 'INVEST', article: 'REPAIR' },
    { key: 'EQUIPMENT', label: 'Мебель', category: 'INVEST', article: 'EQUIPMENT' },
    { key: 'PURCHASE', label: 'Закуп', category: 'INVEST', article: 'PURCHASE' },
    { key: 'INVEST_OTHER', label: 'Прочее', category: 'INVEST', article: 'INVEST_OTHER', commentRequired: true },
  ],
  FINANCING: [
    { key: 'OWNER', label: 'Изъятие собственника', category: 'OWNER', article: null },
    { key: 'SINGLE_TAX', label: 'Единый налог', category: 'FINANCING', article: 'SINGLE_TAX' },
  ],
}
const SECTION_HINT = {
  OPERATING: 'Уменьшает прибыль в ОПиУ и остаток на счёте.',
  INVESTING: 'Только движение денег: в прибыль не попадает, уменьшает остаток на счёте.',
  FINANCING: 'Только движение денег: вывод владельцу и налог, в прибыль не попадает.',
}

export default function DirectorExpense() {
  const { user } = useAuth()
  const [module, setModule] = useState(user?.module || 'EXPRESS')
  const accounts = asList(useFetch('/expenses/accounts/', { module }).data)
  const employees = asList(useFetch('/expenses/employees/').data)
  const list = useFetch('/expenses/', { from: firstOfMonth(), to: today(), page_size: 100, module })
  const [section, setSection] = useState('OPERATING')
  const [item, setItem] = useState('RENT')
  const [form, setForm] = useState({ amount: '', comment: '', account: '', employee: '', date: today() })
  const [error, setError] = useState('')
  const [saved, setSaved] = useState('')
  const [busy, setBusy] = useState(false)

  const def = useMemo(() => ITEMS[section].find((i) => i.key === item) || ITEMS[section][0], [section, item])
  const accountId = form.account || (accounts.find((a) => a.kind === 'CASH') || accounts[0])?.id || ''
  const rows = asList(list.data)
  const total = rows.reduce((s, r) => s + Number(r.amount_kgs ?? r.amount), 0)

  function changeSection(v) { setSection(v); setItem(ITEMS[v][0].key); setError('') }

  async function submit(e) {
    e.preventDefault()
    setError(''); setSaved('')
    const amount = parseFloat(String(form.amount).replace(',', '.'))
    if (!(amount > 0)) { setError('Сумма должна быть больше нуля.'); return }
    if (def.employee && !form.employee) { setError('Укажите, кому выплачена зарплата.'); return }
    if (def.commentRequired && !form.comment.trim()) { setError('Для «Прочее» комментарий обязателен: что именно куплено или оплачено.'); return }
    if (!accountId) { setError('Нет счёта для списания, обратитесь к администратору.'); return }
    setBusy(true)
    try {
      const emp = def.employee ? employees.find((u) => String(u.id) === String(form.employee)) : null
      const description = [def.employee && emp ? `Зарплата: ${emp.name}` : def.label, form.comment.trim()].filter(Boolean).join(' — ')
      await api.post('/expenses/', {
        category: def.category, opex_article: def.article, account: accountId,
        amount: amount.toFixed(2), paid_amount: amount.toFixed(2), date: form.date, payment_date: form.date,
        description, employee: def.employee ? form.employee : null,
      })
      setSaved(`Записано: ${def.label}${emp ? `, ${emp.name}` : ''}, ${money(amount)}`)
      setForm({ amount: '', comment: '', account: form.account, employee: '', date: today() })
      list.reload()
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  async function remove(r) {
    if (!(await confirm(`Удалить расход «${r.description || r.category_display}» на ${money(r.amount)}?`))) return
    try { await api.delete(`/expenses/${r.id}/`); list.reload() } catch (err) { setError(errorMessage(err)) }
  }

  return (
    <div className="dir-page">
      <div className="dir-cols wide-left">
        <section className="dir-panel">
          <div className="dir-panel-head"><h3>Новый расход</h3><Segmented value={module} onChange={(v) => { setModule(v); setForm({ ...form, account: '' }) }} options={DIRECTIONS} /></div>
          <p className="dir-note">{SECTION_HINT[section]}</p>
          {error && <Alert kind="error">{error}</Alert>}
          {saved && <Alert kind="success">{saved}</Alert>}
          <form onSubmit={submit} style={{ display: 'grid', gap: 12, gridTemplateColumns: 'repeat(auto-fit, minmax(min(100%, 220px), 1fr))' }}>
            <div style={{ gridColumn: '1 / -1' }}>
              <Field label="Раздел">
                <Segmented value={section} onChange={changeSection} options={SECTIONS} />
              </Field>
            </div>
            <div style={{ gridColumn: '1 / -1' }}>
              <Field label="Статья">
                <div className="dir-choice">
                  {ITEMS[section].map((i) => (
                    <button type="button" key={i.key} className={`dir-choice-btn ${item === i.key ? 'active' : ''}`} onClick={() => { setItem(i.key); setError('') }}>{i.label}</button>
                  ))}
                </div>
              </Field>
            </div>
            {def.employee && (
              <div style={{ gridColumn: '1 / -1' }}>
                <Field label="Кому">
                  <select className="select" value={form.employee} onChange={(e) => setForm({ ...form, employee: e.target.value })}>
                    <option value="">Выберите сотрудника…</option>
                    {employees.map((u) => <option key={u.id} value={u.id}>{u.name} · {u.role}</option>)}
                  </select>
                </Field>
              </div>
            )}
            <Field label="Сумма, сом">
              <input className="input" type="number" step="0.01" min="0" value={form.amount} onChange={(e) => setForm({ ...form, amount: e.target.value })} placeholder="0.00" autoFocus />
            </Field>
            <Field label="Дата">
              <input className="input" type="date" value={form.date} onChange={(e) => setForm({ ...form, date: e.target.value })} />
            </Field>
            <Field label="Откуда списано">
              <select className="select" value={accountId} onChange={(e) => setForm({ ...form, account: e.target.value })}>
                {accounts.map((a) => <option key={a.id} value={a.id}>{a.name}{a.kind === 'CASH' ? ' (наличные)' : ''}</option>)}
              </select>
            </Field>
            <div style={{ gridColumn: '1 / -1' }}>
              <Field label={def.commentRequired ? 'Комментарий (обязательно)' : 'Комментарий'} hint={def.commentRequired ? 'Что именно оплачено' : 'Необязательно'}>
                <input className="input" value={form.comment} onChange={(e) => setForm({ ...form, comment: e.target.value })} placeholder={def.commentRequired ? 'Например: вывеска на фасад' : ''} />
              </Field>
            </div>
            <div style={{ gridColumn: '1 / -1' }}>
              <button className="btn btn-primary" type="submit" disabled={busy}>{busy ? 'Сохраняю…' : 'Записать расход'}</button>
            </div>
          </form>
        </section>

        <section className="dir-panel">
          <div className="dir-panel-head"><h3>Расходы за месяц</h3><span>{rows.length ? money(total) : ''}</span></div>
          {!rows.length ? <div className="empty">За этот месяц расходов ещё нет.</div> : (
            <div className="table-wrap">
              <table className="table">
                <thead><tr><th>Дата</th><th>Статья</th><th className="num">Сумма</th><th></th></tr></thead>
                <tbody>
                  {rows.map((r) => (
                    <tr key={r.id}>
                      <td>{dateRu(r.date)}</td>
                      <td>{r.opex_article_display || r.category_display}{r.description && <div className="muted" style={{ fontSize: 12 }}>{r.description}</div>}</td>
                      <td className="num"><strong>{money(r.amount, r.account_currency)}</strong></td>
                      <td className="num"><button className="btn btn-ghost btn-sm" onClick={() => remove(r)}>Удалить</button></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
      </div>
    </div>
  )
}
