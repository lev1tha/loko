import { useEffect, useMemo, useState } from 'react'
import api, { errorMessage } from '../api/client'
import { useFetch, asList } from '../lib/hooks'
import { useAuth } from '../auth/AuthContext'
import { num, today, dateRu } from '../lib/format'
import { Alert, EmptyState, Field, Modal, Spinner, Stat } from '../components/ui'

function shortBranch(name) {
  if (!name) return ''
  const tail = String(name).includes('—') ? String(name).split('—').slice(1).join('—') : name
  return tail.replace('улица,', '').replace(/\s+/g, ' ').trim()
}

const kg3 = (v) => `${num(v, 3)} кг`

// Остаток веса на складе: директор вносит приход (кг) за день, расход считается
// из веса, который сотрудники указали при оприходовании. Остаток переносится
// на следующий день: 40 кг + 150 кг = 190 кг.
export default function WarehouseStock() {
  const { user, isAdmin } = useAuth()
  const branches = asList(useFetch('/warehouse-stock/branches/').data)
  const [branch, setBranch] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [modal, setModal] = useState(null) // 'intake' | 'adjust'
  const [form, setForm] = useState({ date: today(), kg: '', note: '' })

  useEffect(() => {
    if (!branch && branches.length) {
      const def = branches.find((b) => b.is_default) || branches[0]
      setBranch(String(def.id))
    }
  }, [branches, branch])

  const params = useMemo(() => (branch ? { branch } : null), [branch])
  const req = useFetch('/warehouse-stock/summary/', params || {})
  const d = req.data
  const balance = parseFloat(d?.balance_kg || 0)

  function open(kind) {
    setError('')
    setForm({ date: today(), kg: '', note: '' })
    setModal(kind)
  }

  async function submit(e) {
    e?.preventDefault?.()
    const v = parseFloat(String(form.kg).replace(',', '.'))
    if (modal === 'intake' && !(v > 0)) { setError('Укажите вес прихода больше нуля.'); return }
    if (modal === 'adjust' && !(v >= 0)) { setError('Укажите фактический остаток (0 или больше).'); return }
    setBusy(true); setError('')
    try {
      const payload = modal === 'intake'
        ? { branch, date: form.date, kind: 'INTAKE', kg: v.toFixed(3), note: form.note }
        : { branch, date: form.date, kind: 'ADJUST', kg: (v - balance).toFixed(3), note: form.note || 'пересчёт остатка' }
      if (modal === 'adjust' && Math.abs(v - balance) < 0.0005) { setError('Фактический остаток совпадает с расчётным.'); setBusy(false); return }
      await api.post('/warehouse-stock/', payload)
      setModal(null)
      req.reload()
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  async function remove(entry) {
    if (!window.confirm(`Удалить запись ${dateRu(entry.date)} · ${entry.kind_display} ${num(entry.kg, 3)} кг?`)) return
    setError('')
    try {
      await api.delete(`/warehouse-stock/${entry.id}/`)
      req.reload()
    } catch (err) {
      setError(errorMessage(err))
    }
  }

  const canDelete = (e) => isAdmin || (e.created_by && e.created_by === user?.id)

  return (
    <div className="wh-page">
      {error && !modal && <Alert kind="error">{error}</Alert>}
      <div className="wh-head">
        <div>
          <h2 className="card-title">Склад · остаток веса</h2>
          <p className="muted" style={{ margin: '2px 0 0' }}>
            Приход вносите каждый день; расход считается из веса оприходованных заказов. Остаток переносится на следующий день.
          </p>
        </div>
        <div className="row gap-sm wh-head-actions" style={{ flexWrap: 'wrap' }}>
          <select className="select" value={branch} onChange={(e) => setBranch(e.target.value)}>
            {branches.map((b) => <option key={b.id} value={b.id}>{shortBranch(b.name)}</option>)}
          </select>
          <button className="btn btn-primary" onClick={() => open('intake')} disabled={!branch}>+ Приход на склад</button>
          <button className="btn btn-secondary" onClick={() => open('adjust')} disabled={!branch}>Указать фактический остаток</button>
        </div>
      </div>

      {req.loading && !d ? <Spinner full /> : d && (
        <>
          <div className="grid" style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(min(100%, 200px), 1fr))' }}>
            <Stat label="Сейчас на складе" value={kg3(d.balance_kg)} tone={balance < 0 ? 'negative' : 'positive'}
              sub={d.since ? `учёт с ${dateRu(d.since)}` : 'приходов ещё нет'} />
            <Stat label="Всего пришло" value={kg3(d.added_kg)} />
            <Stat label="Всего передано клиентам" value={kg3(d.consumed_kg)} sub="вес из оприходованных заказов" />
          </div>
          {balance < 0 && (
            <Alert kind="error">Остаток отрицательный: передано больше, чем внесено приходов. Внесите недостающий приход или укажите фактический остаток.</Alert>
          )}

          <div className="grid" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(min(100%, 380px), 1fr))' }}>
            <div className="card">
              <h3 className="card-title">По дням</h3>
              {!d.days.length ? <EmptyState>Внесите первый приход — с этого дня начнётся учёт.</EmptyState> : (
                <div className="table-wrap">
                  <table className="table">
                    <thead><tr><th>Дата</th><th className="num">Пришло</th><th className="num">Передано</th><th className="num">Остаток</th></tr></thead>
                    <tbody>
                      {d.days.map((r) => (
                        <tr key={r.date}>
                          <td>{dateRu(r.date)}</td>
                          <td className="num positive">{parseFloat(r.added_kg) ? `+${num(r.added_kg, 3)}` : '—'}</td>
                          <td className="num negative">{parseFloat(r.consumed_kg) ? `−${num(r.consumed_kg, 3)}` : '—'}</td>
                          <td className="num"><strong>{num(r.balance_kg, 3)}</strong></td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>

            <div className="card">
              <h3 className="card-title">Записи прихода</h3>
              {!d.entries.length ? <EmptyState>Записей нет.</EmptyState> : (
                <div className="table-wrap">
                  <table className="table">
                    <thead><tr><th>Дата</th><th>Тип</th><th className="num">Кг</th><th>Комментарий</th><th>Кто</th><th></th></tr></thead>
                    <tbody>
                      {d.entries.map((e) => (
                        <tr key={e.id}>
                          <td>{dateRu(e.date)}</td>
                          <td className="muted">{e.kind_display}</td>
                          <td className={`num ${parseFloat(e.kg) < 0 ? 'negative' : ''}`}>{num(e.kg, 3)}</td>
                          <td className="muted">{e.note || '—'}</td>
                          <td className="muted">{e.created_by_name || '—'}</td>
                          <td className="num">
                            {canDelete(e) && (
                              <button className="btn btn-ghost btn-sm" onClick={() => remove(e)}>Удалить</button>
                            )}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          </div>
        </>
      )}

      {modal && (
        <Modal
          title={modal === 'intake' ? 'Приход на склад' : 'Фактический остаток'}
          onClose={() => setModal(null)}
          footer={
            <>
              <button className="btn btn-secondary" onClick={() => setModal(null)}>Отмена</button>
              <button className="btn btn-primary" disabled={busy} onClick={submit}>{busy ? 'Сохранение…' : 'Сохранить'}</button>
            </>
          }
        >
          {error && <Alert kind="error">{error}</Alert>}
          <p className="caption" style={{ margin: 0, lineHeight: 1.5 }}>
            {modal === 'intake'
              ? 'Сколько кг пришло на склад. Прибавится к текущему остатку.'
              : `Сколько кг реально лежит на складе. Расчётный остаток сейчас: ${kg3(d?.balance_kg || 0)} — разница запишется корректировкой.`}
          </p>
          <Field label="Дата">
            <input className="input" type="date" value={form.date} onChange={(e) => setForm({ ...form, date: e.target.value })} />
          </Field>
          <Field label={modal === 'intake' ? 'Пришло, кг' : 'Фактический остаток, кг'}>
            <input className="input" type="number" step="0.001" min="0" autoFocus
              value={form.kg} onChange={(e) => setForm({ ...form, kg: e.target.value })} placeholder="200" />
          </Field>
          <Field label="Комментарий">
            <input className="input" value={form.note} onChange={(e) => setForm({ ...form, note: e.target.value })} placeholder="фура из Китая, пересчёт…" />
          </Field>
        </Modal>
      )}
    </div>
  )
}
