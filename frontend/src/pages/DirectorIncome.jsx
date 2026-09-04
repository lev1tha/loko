import { useState } from 'react'
import api, { errorMessage } from '../api/client'
import { useFetch, asList } from '../lib/hooks'
import { useAuth } from '../auth/AuthContext'
import { money, today, dateRu, firstOfMonth } from '../lib/format'
import { Alert, Field, Segmented } from '../components/ui'
import '../director.css'

const DIRECTIONS = [
  { value: 'EXPRESS', label: 'Loko Express' },
  { value: 'BUSINESS', label: 'Loko Business' },
]

// «Доход» в кабинете директора: наименование, сумма, комментарий. Записывается
// как прочий доход направления (в выручку ОПиУ и приток ОДДС, без себестоимости).
export default function DirectorIncome() {
  const { user } = useAuth()
  const [module, setModule] = useState(user?.module || 'EXPRESS')
  const accounts = asList(useFetch('/expenses/accounts/', { module }).data)
  const list = useFetch('/other-income/', { from: firstOfMonth(), to: today(), page_size: 50, module })
  const [form, setForm] = useState({ title: '', amount: '', comment: '', account: '', date: today() })
  const [error, setError] = useState('')
  const [saved, setSaved] = useState('')
  const [busy, setBusy] = useState(false)

  const accountId = form.account || (accounts.find((a) => a.kind === 'CASH') || accounts[0])?.id || ''
  const rows = asList(list.data)
  const total = rows.reduce((s, r) => s + Number(r.amount_kgs ?? r.amount), 0)

  async function submit(e) {
    e.preventDefault()
    setError(''); setSaved('')
    const amount = parseFloat(String(form.amount).replace(',', '.'))
    if (!form.title.trim()) { setError('Укажите наименование дохода.'); return }
    if (!(amount > 0)) { setError('Сумма должна быть больше нуля.'); return }
    if (!accountId) { setError('Нет счёта для зачисления, обратитесь к администратору.'); return }
    setBusy(true)
    try {
      const description = form.comment.trim() ? `${form.title.trim()} — ${form.comment.trim()}` : form.title.trim()
      await api.post('/other-income/', { account: accountId, amount: amount.toFixed(2), description, date: form.date })
      setSaved(`Записано: ${form.title.trim()}, ${money(amount)}`)
      setForm({ title: '', amount: '', comment: '', account: form.account, date: today() })
      list.reload()
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  async function remove(r) {
    if (!window.confirm(`Удалить доход «${r.description}» на ${money(r.amount)}?`)) return
    try { await api.delete(`/other-income/${r.id}/`); list.reload() } catch (err) { setError(errorMessage(err)) }
  }

  return (
    <div className="dir-page">
      <div className="dir-cols wide-left">
        <section className="dir-panel">
          <div className="dir-panel-head"><h3>Новый доход</h3><Segmented value={module} onChange={(v) => { setModule(v); setForm({ ...form, account: '' }) }} options={DIRECTIONS} /></div>
          {error && <Alert kind="error">{error}</Alert>}
          {saved && <Alert kind="success">{saved}</Alert>}
          <form onSubmit={submit} style={{ display: 'grid', gap: 12, gridTemplateColumns: 'repeat(auto-fit, minmax(min(100%, 220px), 1fr))' }}>
            <div style={{ gridColumn: '1 / -1' }}>
              <Field label="Наименование дохода">
                <input className="input" value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} placeholder="Например: упаковка, хранение, возврат" autoFocus />
              </Field>
            </div>
            <Field label="Сумма, сом">
              <input className="input" type="number" step="0.01" min="0" value={form.amount} onChange={(e) => setForm({ ...form, amount: e.target.value })} placeholder="0.00" />
            </Field>
            <Field label="Дата">
              <input className="input" type="date" value={form.date} onChange={(e) => setForm({ ...form, date: e.target.value })} />
            </Field>
            <Field label="Куда зачислено">
              <select className="select" value={accountId} onChange={(e) => setForm({ ...form, account: e.target.value })}>
                {accounts.map((a) => <option key={a.id} value={a.id}>{a.name}{a.kind === 'CASH' ? ' (наличные)' : ''}</option>)}
              </select>
            </Field>
            <div style={{ gridColumn: '1 / -1' }}>
              <Field label="Комментарий" hint="Необязательно">
                <input className="input" value={form.comment} onChange={(e) => setForm({ ...form, comment: e.target.value })} placeholder="От кого, за что" />
              </Field>
            </div>
            <div style={{ gridColumn: '1 / -1' }}>
              <button className="btn btn-primary" type="submit" disabled={busy}>{busy ? 'Сохраняю…' : 'Записать доход'}</button>
            </div>
          </form>
        </section>

        <section className="dir-panel">
          <div className="dir-panel-head"><h3>Доходы за месяц</h3><span>{rows.length ? money(total) : ''}</span></div>
          {!rows.length ? <div className="empty">За этот месяц доходов ещё нет.</div> : (
            <div className="table-wrap">
              <table className="table">
                <thead><tr><th>Дата</th><th>Наименование</th><th className="num">Сумма</th><th></th></tr></thead>
                <tbody>
                  {rows.map((r) => (
                    <tr key={r.id}>
                      <td>{dateRu(r.date)}</td>
                      <td>{r.description || '—'}<div className="muted" style={{ fontSize: 12 }}>{r.account_name}</div></td>
                      <td className="num positive"><strong>{money(r.amount, r.account_currency)}</strong></td>
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
