import { useEffect, useState } from 'react'
import api, { errorMessage } from '../api/client'
import { useFetch, asList } from '../lib/hooks'
import { Alert, Badge, EmptyState, Field, Modal, Spinner } from '../components/ui'
import { IconPlus, IconEdit, IconTrash, IconQr } from '../components/icons'

// Админ-страница управления филиалами Loko Express (точки приёма карго).
// Продажи/расходы тегируются филиалом для раздельной аналитики; история (branch=NULL)
// остаётся в выборке «Все филиалы».
export default function Branches() {
  const req = useFetch('/branches/')
  const [form, setForm] = useState(null) // null | 'new' | branch object
  const [qr, setQr] = useState(null)     // филиал, для которого открыт QR
  const [error, setError] = useState('')
  const [busyId, setBusyId] = useState(null)

  const rows = asList(req.data)

  async function remove(b) {
    if (!window.confirm(`Удалить филиал «${b.name}»?`)) return
    setBusyId(b.id)
    setError('')
    try {
      await api.delete(`/branches/${b.id}/`)
      req.reload()
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setBusyId(null)
    }
  }

  if (req.loading) return <Spinner full />

  return (
    <>
      {error && <Alert kind="error">{error}</Alert>}
      <div className="card">
        <div className="card-header">
          <span className="card-title">Филиалы Loko Express</span>
          <button className="btn btn-primary btn-sm" onClick={() => setForm('new')}>
            <IconPlus size={16} /> Новый филиал
          </button>
        </div>
        <p className="caption" style={{ margin: '0 0 12px', lineHeight: 1.5 }}>
          Филиалы — точки приёма карго Express. Продажи и расходы тегируются филиалом для
          раздельной и сводной аналитики. Неактивный филиал не предлагается в формах, но его
          история сохраняется. Удалить филиал с операциями нельзя — отметьте его неактивным.
        </p>
        {rows.length === 0 ? (
          <EmptyState>Филиалов пока нет. Добавьте первый.</EmptyState>
        ) : (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>Название</th>
                  <th>Адрес</th>
                  <th>Статус</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {rows.map((b) => (
                  <tr key={b.id}>
                    <td><strong>{b.name}</strong></td>
                    <td className="muted">{b.address || '—'}</td>
                    <td>
                      <Badge variant={b.is_active ? 'badge-success' : 'badge-manager'}>
                        {b.is_active ? 'Активен' : 'Неактивен'}
                      </Badge>
                      {b.is_default && <Badge variant="badge-bank">по умолчанию</Badge>}
                    </td>
                    <td className="num">
                      <div className="row gap-sm" style={{ justifyContent: 'flex-end' }}>
                        <button className="btn btn-icon btn-ghost btn-sm" title="QR филиала" onClick={() => setQr(b)}>
                          <IconQr size={16} />
                        </button>
                        <button className="btn btn-icon btn-ghost btn-sm" title="Изменить" onClick={() => setForm(b)}>
                          <IconEdit size={16} />
                        </button>
                        <button
                          className="btn btn-icon btn-danger btn-sm"
                          title="Удалить"
                          disabled={busyId === b.id}
                          onClick={() => remove(b)}
                        >
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
        <BranchForm
          editing={form === 'new' ? null : form}
          onClose={() => setForm(null)}
          onSaved={() => {
            setForm(null)
            req.reload()
          }}
        />
      )}

      {qr && <QrModal branch={qr} onClose={() => setQr(null)} />}
    </>
  )
}

// QR филиала: превью + копируемая ссылка + скачивание SVG (для печати) / PNG.
// Картинка тянется через axios (JWT в заголовке) как blob — эндпоинт закрыт для
// оператора/директора, поэтому обычный <img src> без токена не подошёл бы.
function QrModal({ branch, onClose }) {
  const [imgUrl, setImgUrl] = useState('')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState('')
  const [copied, setCopied] = useState(false)

  useEffect(() => {
    let objUrl
    let alive = true
    api.get(`/branches/${branch.id}/qr/`, { params: { fmt: 'svg' }, responseType: 'blob' })
      .then((res) => {
        if (!alive) return
        objUrl = URL.createObjectURL(res.data)
        setImgUrl(objUrl)
      })
      .catch((err) => alive && setError(errorMessage(err)))
      .finally(() => alive && setLoading(false))
    return () => {
      alive = false
      if (objUrl) URL.revokeObjectURL(objUrl)
    }
  }, [branch.id])

  async function download(fmt) {
    setBusy(fmt)
    setError('')
    try {
      const res = await api.get(`/branches/${branch.id}/qr/`, { params: { fmt }, responseType: 'blob' })
      const url = URL.createObjectURL(res.data)
      const a = document.createElement('a')
      a.href = url
      a.download = `loko-qr-filial-${branch.id}.${fmt}`
      document.body.appendChild(a)
      a.click()
      a.remove()
      URL.revokeObjectURL(url)
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setBusy('')
    }
  }

  function copyLink() {
    navigator.clipboard?.writeText(branch.track_url)
      .then(() => {
        setCopied(true)
        setTimeout(() => setCopied(false), 1500)
      })
      .catch(() => {})
  }

  return (
    <Modal
      title={`QR · ${branch.name}`}
      onClose={onClose}
      footer={<button className="btn btn-secondary" onClick={onClose}>Закрыть</button>}
    >
      <div className="col" style={{ alignItems: 'center', gap: 14 }}>
        {error && <Alert kind="error">{error}</Alert>}
        <p className="caption" style={{ textAlign: 'center', margin: 0, lineHeight: 1.5 }}>
          Клиент сканирует код и попадает на страницу этого филиала — вписывает коды посылок,
          а склад их принимает. Печатайте на баннере из <strong>SVG</strong> (не мылится при увеличении).
        </p>
        <div
          style={{
            background: '#fff', border: '1px solid #e8ebf0', borderRadius: 14,
            padding: 16, width: 272, height: 272, display: 'flex',
            alignItems: 'center', justifyContent: 'center',
          }}
        >
          {loading ? <Spinner /> : imgUrl && (
            <img src={imgUrl} alt={`QR ${branch.name}`} width={240} height={240} />
          )}
        </div>
        {branch.track_url && (
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap', justifyContent: 'center' }}>
            <code style={{ fontSize: 13, color: '#78808c', wordBreak: 'break-all' }}>{branch.track_url}</code>
            <button className="btn btn-ghost btn-sm" onClick={copyLink}>{copied ? 'Скопировано' : 'Копировать'}</button>
          </div>
        )}
        <div className="row gap-sm">
          <button className="btn btn-primary btn-sm" onClick={() => download('svg')} disabled={busy === 'svg'}>
            {busy === 'svg' ? 'Готовим…' : 'Скачать SVG (печать)'}
          </button>
          <button className="btn btn-secondary btn-sm" onClick={() => download('png')} disabled={busy === 'png'}>
            {busy === 'png' ? 'Готовим…' : 'Скачать PNG'}
          </button>
        </div>
      </div>
    </Modal>
  )
}

function BranchForm({ editing, onClose, onSaved }) {
  const isEdit = !!editing
  const [name, setName] = useState(editing?.name || '')
  const [address, setAddress] = useState(editing?.address || '')
  const [isActive, setIsActive] = useState(editing ? editing.is_active : true)
  const [isDefault, setIsDefault] = useState(editing ? editing.is_default : false)
  const [error, setError] = useState('')
  const [saving, setSaving] = useState(false)

  async function submit(e) {
    e.preventDefault()
    setError('')
    setSaving(true)
    try {
      const body = { name: name.trim(), address: address.trim(), is_active: isActive, is_default: isDefault }
      if (isEdit) await api.patch(`/branches/${editing.id}/`, body)
      else await api.post('/branches/', body)
      onSaved()
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setSaving(false)
    }
  }

  return (
    <Modal
      title={isEdit ? `Филиал · ${editing.name}` : 'Новый филиал'}
      onClose={onClose}
      footer={
        <>
          <button className="btn btn-secondary" onClick={onClose}>Отмена</button>
          <button className="btn btn-primary" onClick={submit} disabled={saving}>
            {saving ? 'Сохранение…' : isEdit ? 'Сохранить' : 'Создать филиал'}
          </button>
        </>
      }
    >
      <form onSubmit={submit} className="col">
        {error && <Alert kind="error">{error}</Alert>}
        <Field label="Название">
          <input
            className="input"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Loko Express — Гульчинская, 13/1"
            required
            autoFocus
          />
        </Field>
        <Field label="Адрес" hint="Необязательно">
          <input
            className="input"
            value={address}
            onChange={(e) => setAddress(e.target.value)}
            placeholder="ул. Гульчинская, 13/1"
          />
        </Field>
        <label className="check-row">
          <input type="checkbox" checked={isActive} onChange={(e) => setIsActive(e.target.checked)} />
          <span>Активен (предлагается в формах продаж и фильтрах)</span>
        </label>
        <label className="check-row">
          <input type="checkbox" checked={isDefault} onChange={(e) => setIsDefault(e.target.checked)} />
          <span>Филиал по умолчанию (подставляется в продажи без явно выбранного филиала)</span>
        </label>
      </form>
    </Modal>
  )
}
