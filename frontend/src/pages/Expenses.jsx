import { useState } from 'react'
import api, { errorMessage } from '../api/client'
import { useFetch, asList } from '../lib/hooks'
import { firstOfMonth, today, money, dateRu, signClass } from '../lib/format'
import { Alert, Badge, EmptyState, Field, Modal, Segmented, Spinner } from '../components/ui'
import { IconPlus } from '../components/icons'

const MODULES = [
  { value: 'all', label: 'Всё' },
  { value: 'EXPRESS', label: 'Express' },
  { value: 'BUSINESS', label: 'Business' },
]
const PAGE_SIZE = 10000

export const EXPENSE_CATEGORIES = [
  { value: 'OPEX', label: 'Операционные расходы (OpEx)' },
  { value: 'COGS', label: 'Себестоимость / закуп товара' },
  { value: 'SUPPLIER', label: 'Оплата / аванс поставщику' },
  { value: 'OTHER', label: 'Неоперационная деятельность (Другое)' },
  { value: 'OWNER', label: 'Изъятие собственника' },
]

export const OPEX_ARTICLES = [
  { value: 'RENT', label: 'Аренда' },
  { value: 'PAYROLL', label: 'ФОТ (Фонд оплаты труда)' },
  { value: 'INCOME_TAX', label: 'Подоходный налог' },
  { value: 'SOCIAL_FUND', label: 'Соц.фонд' },
  { value: 'OTHER', label: 'Прочие расходы' },
]

const CAT_HINT = {
  OPEX: 'Влияет на ООПИУ и ОДДС',
  COGS: 'Закуп товара → себестоимость в ООПИУ и отток в ОДДС',
  SUPPLIER: 'Оплата/аванс поставщику → ОДДС (себестоимость учтена отдельно)',
  OTHER: 'Неоперационная деятельность',
  OWNER: 'Только ОДДС, уменьшает баланс денежных средств',
}

export default function Expenses() {
  const [from, setFrom] = useState(firstOfMonth())
  const [to, setTo] = useState(today())
  const [category, setCategory] = useState('')
  const [module, setModule] = useState('all')
  const [showForm, setShowForm] = useState(false)

  const params = {
    from,
    to,
    category: category || undefined,
    module: module !== 'all' ? module : undefined,
    page_size: PAGE_SIZE,
  }
  const expenses = useFetch('/expenses/', params)
  const accounts = useFetch('/accounts/', { page_size: PAGE_SIZE })
  const rows = asList(expenses.data)
  const total = expenses.data?.count ?? rows.length
  const totalSum = rows.reduce((acc, e) => acc + Number(e.amount || 0), 0)

  return (
    <>
      <div className="card">
        <div className="card-header">
          <div className="toolbar grow">
            <Field label="С даты">
              <input className="input" type="date" value={from} onChange={(e) => setFrom(e.target.value)} />
            </Field>
            <Field label="По дату">
              <input className="input" type="date" value={to} onChange={(e) => setTo(e.target.value)} />
            </Field>
            <Field label="Категория">
              <select className="select" value={category} onChange={(e) => setCategory(e.target.value)}>
                <option value="">Все категории</option>
                {EXPENSE_CATEGORIES.map((c) => (
                  <option key={c.value} value={c.value}>{c.label}</option>
                ))}
              </select>
            </Field>
            <div className="field">
              <span className="field-label">Направление</span>
              <Segmented value={module} onChange={setModule} options={MODULES} />
            </div>
          </div>
          <button className="btn btn-primary" onClick={() => setShowForm(true)}>
            <IconPlus size={18} /> Новый расход
          </button>
        </div>

        {!expenses.loading && rows.length > 0 && (
          <div className="caption" style={{ marginBottom: 8 }}>
            Показано {rows.length} из {total} · сумма начисления {money(totalSum)}
          </div>
        )}

        {expenses.loading ? (
          <Spinner />
        ) : rows.length === 0 ? (
          <EmptyState>Расходов за выбранный период нет.</EmptyState>
        ) : (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>Дата</th>
                  <th>Категория</th>
                  <th>Статья (OpEx)</th>
                  <th>Счёт списания</th>
                  <th className="num">Начислено</th>
                  <th className="num">Оплачено</th>
                  <th className="num">Кредиторка</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((e) => (
                  <tr key={e.id}>
                    <td>{dateRu(e.date)}</td>
                    <td><Badge>{e.category_display}</Badge></td>
                    <td className="muted">{e.opex_article_display || '—'}</td>
                    <td>{e.account_name}</td>
                    <td className="num neg">−{money(e.amount)}</td>
                    <td className="num">{money(e.paid_amount)}</td>
                    <td className={`num ${signClass(e.payable)}`}>{money(e.payable)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {showForm && (
        <ExpenseForm
          accounts={asList(accounts.data)}
          onClose={() => setShowForm(false)}
          onSaved={() => {
            setShowForm(false)
            expenses.reload()
          }}
        />
      )}
    </>
  )
}

function ExpenseForm({ accounts, onClose, onSaved }) {
  const [category, setCategory] = useState('OPEX')
  const [article, setArticle] = useState('RENT')
  const [accountId, setAccountId] = useState(accounts[0]?.id || '')
  const [amount, setAmount] = useState('')
  const [paid, setPaid] = useState('')
  const [paymentDate, setPaymentDate] = useState('')
  const [description, setDescription] = useState('')
  const [date, setDate] = useState(today())
  const [error, setError] = useState('')
  const [saving, setSaving] = useState(false)

  const isOpex = category === 'OPEX'
  const commentRequired = isOpex && article === 'OTHER'
  const acc = accounts.find((a) => String(a.id) === String(accountId))

  async function submit(e) {
    e.preventDefault()
    setError('')
    if (commentRequired && !description.trim()) {
      setError('Для «Прочих расходов» комментарий обязателен.')
      return
    }
    setSaving(true)
    try {
      await api.post('/expenses/', {
        category,
        opex_article: isOpex ? article : null,
        account: accountId,
        amount,
        paid_amount: paid !== '' ? paid : undefined,
        payment_date: paymentDate || date,
        description: description.trim(),
        date,
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
      title="Новый расход"
      onClose={onClose}
      footer={
        <>
          <button className="btn btn-secondary" onClick={onClose}>Отмена</button>
          <button className="btn btn-primary" onClick={submit} disabled={saving}>
            {saving ? 'Сохранение…' : 'Добавить расход'}
          </button>
        </>
      }
    >
      <form onSubmit={submit} className="col">
        {error && <Alert kind="error">{error}</Alert>}
        <Field label="Категория расхода" hint={CAT_HINT[category]}>
          <select className="select" value={category} onChange={(e) => setCategory(e.target.value)}>
            {EXPENSE_CATEGORIES.map((c) => (
              <option key={c.value} value={c.value}>{c.label}</option>
            ))}
          </select>
        </Field>

        {isOpex && (
          <Field label="Статья операционного расхода">
            <select className="select" value={article} onChange={(e) => setArticle(e.target.value)}>
              {OPEX_ARTICLES.map((a) => (
                <option key={a.value} value={a.value}>{a.label}</option>
              ))}
            </select>
          </Field>
        )}

        <Field label="Счёт списания" hint={acc ? `Валюта: ${acc.currency}` : 'Обязательно выберите счёт'}>
          <select className="select" value={accountId} onChange={(e) => setAccountId(e.target.value)} required>
            {accounts.map((a) => (
              <option key={a.id} value={a.id}>{a.name} · {a.currency} ({a.module === 'BUSINESS' ? 'Business' : 'Express'})</option>
            ))}
          </select>
        </Field>
        <div className="row row-wrap">
          <Field label={`Сумма начисления${acc ? ', ' + acc.currency : ''}`}>
            <input className="input" type="number" step="0.01" min="0" value={amount} onChange={(e) => setAmount(e.target.value)} placeholder="0.00" required autoFocus />
          </Field>
          <Field label="Оплачено" hint="Пусто = оплачено полностью">
            <input className="input" type="number" step="0.01" min="0" value={paid} onChange={(e) => setPaid(e.target.value)} placeholder={amount || '0.00'} />
          </Field>
        </div>
        <div className="row row-wrap">
          <Field label="Дата операции (ОПиУ)">
            <input className="input" type="date" value={date} onChange={(e) => setDate(e.target.value)} required />
          </Field>
          <Field label="Дата оплаты (ОДДС)" hint="Пусто = дата операции">
            <input className="input" type="date" value={paymentDate} onChange={(e) => setPaymentDate(e.target.value)} />
          </Field>
        </div>
        <Field
          label={commentRequired ? 'Комментарий (обязательно)' : 'Комментарий'}
          hint={commentRequired ? 'Детально распишите, на что ушли средства' : undefined}
          error={commentRequired && !description.trim() ? ' ' : undefined}
        >
          <input
            className="input"
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            placeholder={commentRequired ? 'Например: срочная закупка упаковки' : 'Назначение платежа…'}
            required={commentRequired}
          />
        </Field>
      </form>
    </Modal>
  )
}
