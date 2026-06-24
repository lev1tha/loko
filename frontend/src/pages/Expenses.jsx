import { useState } from 'react'
import api, { errorMessage } from '../api/client'
import { useFetch, asList } from '../lib/hooks'
import { firstOfMonth, today, money, dateRu, signClass } from '../lib/format'
import { Alert, Badge, EmptyState, Field, Modal, Segmented, Spinner } from '../components/ui'
import { IconPlus, IconEdit, IconTrash } from '../components/icons'

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
  { value: 'INVEST', label: 'Инвестиционная (оборудование/активы)' },
  { value: 'FINANCING', label: 'Финансовая (кредиты/проценты)' },
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
  OWNER: 'Финансовая деятельность (ОДДС): изъятие собственника',
  INVEST: 'Инвестиционная деятельность (ОДДС): покупка оборудования/активов',
  FINANCING: 'Финансовая деятельность (ОДДС): кредиты/проценты',
}

export default function Expenses() {
  const [from, setFrom] = useState(firstOfMonth())
  const [to, setTo] = useState(today())
  const [category, setCategory] = useState('')
  const [module, setModule] = useState('all')
  const [form, setForm] = useState(null) // null | 'new' | объект расхода
  const [busyId, setBusyId] = useState(null)
  const [error, setError] = useState('')

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

  async function remove(e) {
    if (!window.confirm(`Удалить расход «${e.category_display}» на ${money(e.amount)}?`)) return
    setBusyId(e.id)
    setError('')
    try {
      await api.delete(`/expenses/${e.id}/`)
      expenses.reload()
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setBusyId(null)
    }
  }

  return (
    <>
      {error && <Alert kind="error">{error}</Alert>}
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
          <button className="btn btn-primary" onClick={() => setForm('new')}>
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
                  <th></th>
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
                    <td className="num">
                      <div className="row gap-sm" style={{ justifyContent: 'flex-end' }}>
                        <button className="btn btn-icon btn-ghost btn-sm" title="Изменить" onClick={() => setForm(e)}>
                          <IconEdit size={16} />
                        </button>
                        <button className="btn btn-icon btn-danger btn-sm" title="Удалить" disabled={busyId === e.id} onClick={() => remove(e)}>
                          <IconTrash size={16} />
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {form && (
        <ExpenseForm
          editing={form === 'new' ? null : form}
          accounts={asList(accounts.data)}
          onClose={() => setForm(null)}
          onSaved={() => {
            setForm(null)
            expenses.reload()
          }}
        />
      )}
    </>
  )
}

function ExpenseForm({ editing, accounts, onClose, onSaved }) {
  const isEdit = !!editing
  const [category, setCategory] = useState(editing?.category || 'OPEX')
  const [article, setArticle] = useState(editing?.opex_article || 'RENT')
  const [accountId, setAccountId] = useState(editing?.account || accounts[0]?.id || '')
  const [amount, setAmount] = useState(editing?.amount || '')
  const [paid, setPaid] = useState(isEdit ? editing.paid_amount : '')
  // Дата оплаты по умолчанию — сегодня (новая); при редактировании — как в записи.
  const [paymentDate, setPaymentDate] = useState(editing?.payment_date || today())
  const [description, setDescription] = useState(editing?.description || '')
  const [date, setDate] = useState(editing?.date || today())
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
      const body = {
        category,
        opex_article: isOpex ? article : null,
        account: accountId,
        amount,
        paid_amount: paid !== '' ? paid : amount,
        payment_date: paymentDate || date,
        description: description.trim(),
        date,
      }
      if (isEdit) await api.patch(`/expenses/${editing.id}/`, body)
      else await api.post('/expenses/', body)
      onSaved()
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setSaving(false)
    }
  }

  return (
    <Modal
      title={isEdit ? 'Изменить расход' : 'Новый расход'}
      onClose={onClose}
      footer={
        <>
          <button className="btn btn-secondary" onClick={onClose}>Отмена</button>
          <button className="btn btn-primary" onClick={submit} disabled={saving}>
            {saving ? 'Сохранение…' : isEdit ? 'Сохранить' : 'Добавить расход'}
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
          <Field label="Дата оплаты (ОДДС)" hint="По умолчанию — сегодня">
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
