import { useEffect, useState } from 'react'
import { Alert, Field, Modal } from '../components/ui'

// Модальные окна вместо системных window.confirm / window.prompt.
// Функции глобальные (промисы), окно рисует один <DialogHost/> в App.jsx:
//   if (!(await confirm('Удалить запись?'))) return
//   const reason = await prompt({ title: 'Не найдено', label: 'Что не найдено / где искали' })  // null = отмена

let listener = null
let queue = []

function push(req) {
  return new Promise((resolve) => {
    queue.push({ ...req, resolve })
    listener?.()
  })
}

export function confirm(text, opts = {}) {
  return push({ kind: 'confirm', text, title: opts.title || 'Подтвердите действие', okLabel: opts.okLabel || 'Удалить', danger: opts.danger !== false })
}

export function prompt(opts = {}) {
  return push({
    kind: 'prompt', title: opts.title || 'Введите значение', label: opts.label || '', hint: opts.hint,
    placeholder: opts.placeholder || '', okLabel: opts.okLabel || 'Сохранить', required: opts.required !== false, initial: opts.initial || '',
  })
}

export function DialogHost() {
  const [current, setCurrent] = useState(null)
  const [value, setValue] = useState('')
  const [error, setError] = useState('')

  useEffect(() => {
    listener = () => {
      if (!current && queue.length) {
        const next = queue.shift()
        setCurrent(next)
        setValue(next.initial || '')
        setError('')
      }
    }
    listener()
    return () => { listener = null }
  }, [current])

  if (!current) return null

  const finish = (result) => {
    current.resolve(result)
    setCurrent(null)
  }

  if (current.kind === 'confirm') {
    return (
      <Modal
        title={current.title}
        onClose={() => finish(false)}
        footer={
          <>
            <button className="btn btn-secondary" onClick={() => finish(false)}>Отмена</button>
            <button className={`btn ${current.danger ? 'btn-danger' : 'btn-primary'}`} onClick={() => finish(true)} autoFocus>{current.okLabel}</button>
          </>
        }
      >
        <p style={{ margin: 0, lineHeight: 1.5 }}>{current.text}</p>
      </Modal>
    )
  }

  const submit = (e) => {
    e?.preventDefault?.()
    if (current.required && !value.trim()) { setError('Поле обязательно.'); return }
    finish(value.trim())
  }
  return (
    <Modal
      title={current.title}
      onClose={() => finish(null)}
      footer={
        <>
          <button className="btn btn-secondary" onClick={() => finish(null)}>Отмена</button>
          <button className="btn btn-primary" onClick={submit}>{current.okLabel}</button>
        </>
      }
    >
      <form onSubmit={submit}>
        {error && <Alert kind="error">{error}</Alert>}
        <Field label={current.label} hint={current.hint}>
          <input className="input" value={value} onChange={(e) => setValue(e.target.value)} placeholder={current.placeholder} autoFocus />
        </Field>
      </form>
    </Modal>
  )
}
