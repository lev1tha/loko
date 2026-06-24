import { useState } from 'react'
import api, { errorMessage } from '../api/client'
import { useFetch } from '../lib/hooks'
import { money, signClass } from '../lib/format'
import { useAuth } from '../auth/AuthContext'
import { Alert, Badge, Field, Modal, Segmented, Spinner, Stat } from '../components/ui'
import { IconPlus } from '../components/icons'

const DISPLAY = [
  { value: 'KGS', label: 'В сомах' },
  { value: 'CNY', label: 'В юанях' },
]

// module: 'EXPRESS' | 'BUSINESS' | undefined (all)
export default function Accounts({ module }) {
  const { isAdmin } = useAuth()
  const isBusiness = module === 'BUSINESS'
  const balances = useFetch('/reports/balances/', module ? { module } : undefined)
  const settings = useFetch('/settings/')
  const [showForm, setShowForm] = useState(false)
  const [display, setDisplay] = useState('KGS')

  if (balances.loading || settings.loading) return <Spinner full />

  const rate = Number(settings.data?.cny_to_kgs_rate || 12.5)
  const rows = balances.data || []

  // Convert a KGS amount into the chosen display currency.
  const inDisplay = (kgs) => (display === 'CNY' ? Number(kgs) / rate : Number(kgs))
  const total = rows.reduce((acc, a) => acc + Number(a.current_balance_kgs || 0), 0)

  return (
    <>
      <div className="spread row-wrap" style={{ marginBottom: 4 }}>
        <Stat
          label={`Итого по счетам${module ? '' : ' (оба направления)'}`}
          value={money(inDisplay(total), display)}
          tone={signClass(total)}
        />
        {isBusiness && (
          <div className="field" style={{ alignItems: 'flex-end' }}>
            <span className="field-label">Отображение</span>
            <Segmented value={display} onChange={setDisplay} options={DISPLAY} />
          </div>
        )}
      </div>

      <div className="grid">
        {rows.map((a) => (
          <Stat
            key={a.id}
            label={a.name}
            value={money(inDisplay(a.current_balance_kgs), display)}
            tone={signClass(a.current_balance_kgs)}
            sub={`${money(a.current_balance, a.currency)} · ${a.currency}`}
          />
        ))}
      </div>

      <div className="card">
        <div className="card-header">
          <span className="card-title">Движение по счетам</span>
          {isAdmin && (
            <button className="btn btn-primary btn-sm" onClick={() => setShowForm(true)}>
              <IconPlus size={16} /> Новый счёт
            </button>
          )}
        </div>
        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th>Счёт</th>
                <th>Валюта</th>
                <th className="num">Начальный</th>
                <th className="num">Поступления</th>
                <th className="num">Расходы</th>
                <th className="num">Переводы +/−</th>
                <th className="num">Текущий остаток</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((a) => {
                const net = Number(a.transfers_in) - Number(a.transfers_out)
                const income = Number(a.income) + Number(a.deposits)
                return (
                  <tr key={a.id}>
                    <td><strong>{a.name}</strong></td>
                    <td>
                      <Badge variant={a.currency === 'KGS' ? 'badge-cash' : 'badge-bank'}>
                        {a.currency}
                      </Badge>
                    </td>
                    <td className="num">{money(a.initial_balance, a.currency)}</td>
                    <td className="num pos">+{money(income, a.currency)}</td>
                    <td className="num neg">−{money(a.expense, a.currency)}</td>
                    <td className={`num ${signClass(net)}`}>
                      {net >= 0 ? '+' : '−'}{money(Math.abs(net), a.currency)}
                    </td>
                    <td className={`num ${signClass(a.current_balance)}`}>
                      <strong>{money(a.current_balance, a.currency)}</strong>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      </div>

      {showForm && (
        <AccountForm
          module={module || 'EXPRESS'}
          onClose={() => setShowForm(false)}
          onSaved={() => {
            setShowForm(false)
            balances.reload()
          }}
        />
      )}
    </>
  )
}

function AccountForm({ module, onClose, onSaved }) {
  const [name, setName] = useState('')
  const [kind, setKind] = useState('BANK')
  const [currency, setCurrency] = useState(module === 'BUSINESS' ? 'CNY' : 'KGS')
  const [initial, setInitial] = useState('0')
  const [error, setError] = useState('')
  const [saving, setSaving] = useState(false)

  async function submit(e) {
    e.preventDefault()
    setError('')
    setSaving(true)
    try {
      await api.post('/accounts/', {
        name: name.trim(),
        kind,
        currency,
        module,
        initial_balance: initial,
      })
      onSaved()
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setSaving(false)
    }
  }

  return (
    <Modal
      title={`Новый счёт · ${module === 'BUSINESS' ? 'Business' : 'Express'}`}
      onClose={onClose}
      footer={
        <>
          <button className="btn btn-secondary" onClick={onClose}>Отмена</button>
          <button className="btn btn-primary" onClick={submit} disabled={saving}>
            {saving ? 'Сохранение…' : 'Создать счёт'}
          </button>
        </>
      }
    >
      <form onSubmit={submit} className="col">
        {error && <Alert kind="error">{error}</Alert>}
        <Field label="Название">
          <input className="input" value={name} onChange={(e) => setName(e.target.value)} placeholder="ICBC" required autoFocus />
        </Field>
        <div className="row row-wrap">
          <Field label="Тип счёта">
            <select className="select" value={kind} onChange={(e) => setKind(e.target.value)}>
              <option value="CASH">Наличные</option>
              <option value="BANK">Банк (безналичный)</option>
            </select>
          </Field>
          <Field label="Валюта">
            <select className="select" value={currency} onChange={(e) => setCurrency(e.target.value)}>
              <option value="KGS">Сом (KGS)</option>
              <option value="CNY">Юань (CNY)</option>
            </select>
          </Field>
        </div>
        <Field label={`Начальный остаток, ${currency}`}>
          <input className="input" type="number" step="0.01" value={initial} onChange={(e) => setInitial(e.target.value)} />
        </Field>
      </form>
    </Modal>
  )
}
