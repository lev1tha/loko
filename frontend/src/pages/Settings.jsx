import { useEffect, useState } from 'react'
import api, { errorMessage } from '../api/client'
import { Alert, Field, Spinner, Stat } from '../components/ui'
import { som } from '../lib/format'

export default function Settings() {
  const [form, setForm] = useState(null)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [ok, setOk] = useState('')

  useEffect(() => {
    api
      .get('/settings/')
      .then((res) => setForm(res.data))
      .catch((err) => setError(errorMessage(err)))
      .finally(() => setLoading(false))
  }, [])

  if (loading) return <Spinner full />
  if (!form) return <Alert kind="error">{error || 'Не удалось загрузить настройки'}</Alert>

  function update(field, value) {
    setForm((f) => ({ ...f, [field]: value }))
    setOk('')
  }

  async function save(e) {
    e.preventDefault()
    setError('')
    setOk('')
    setSaving(true)
    try {
      const { data } = await api.patch('/settings/', {
        base_cost_per_kg_som: form.base_cost_per_kg_som,
        price_per_kg_usd: form.price_per_kg_usd,
        usd_rate_som: form.usd_rate_som,
        cny_to_kgs_rate: form.cny_to_kgs_rate,
        cash_tax_rate: form.cash_tax_rate,
        noncash_tax_rate: form.noncash_tax_rate,
      })
      setForm(data)
      setOk('Настройки сохранены. Новые продажи будут считаться по обновлённым параметрам.')
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setSaving(false)
    }
  }

  // Live preview: cost of an example 0.50 kg parcel must be proportional.
  const exampleCost = (Number(form.base_cost_per_kg_som) * 0.5).toFixed(2)
  const examplePrice = (Number(form.price_per_kg_usd) * Number(form.usd_rate_som) * 0.5).toFixed(2)

  return (
    <>
      <div className="card" style={{ maxWidth: 640 }}>
        <div className="card-header">
          <span className="card-title">Ценообразование и себестоимость</span>
        </div>

        {error && <Alert kind="error">{error}</Alert>}
        {ok && <Alert kind="success">{ok}</Alert>}

        <form onSubmit={save} className="col" style={{ marginTop: 8 }}>
          <Field
            label="Динамическая себестоимость за 1 кг, сом"
            hint="Базовая себестоимость. Пересчитывается строго пропорционально весу."
          >
            <input
              className="input"
              type="number"
              step="0.01"
              min="0"
              value={form.base_cost_per_kg_som}
              onChange={(e) => update('base_cost_per_kg_som', e.target.value)}
              required
            />
          </Field>
          <div className="row row-wrap">
            <Field label="Цена за 1 кг, $">
              <input
                className="input"
                type="number"
                step="0.01"
                min="0"
                value={form.price_per_kg_usd}
                onChange={(e) => update('price_per_kg_usd', e.target.value)}
                required
              />
            </Field>
            <Field label="Внутренний курс доллара, сом" hint="Фиксированный (1$ = 90 сом)">
              <input
                className="input"
                type="number"
                step="0.01"
                min="0"
                value={form.usd_rate_som}
                onChange={(e) => update('usd_rate_som', e.target.value)}
                required
              />
            </Field>
          </div>
          <div className="row row-wrap">
            <Field label="Курс юаня для отчётов, сом за 1 ¥" hint="Loko Business: пересчёт CNY → сом">
              <input
                className="input"
                type="number"
                step="0.0001"
                min="0"
                value={form.cny_to_kgs_rate}
                onChange={(e) => update('cny_to_kgs_rate', e.target.value)}
                required
              />
            </Field>
            <Field label="Налог — наличные, %" hint="На прибыль до налогов, нал-канал">
              <input
                className="input"
                type="number"
                step="0.01"
                min="0"
                value={form.cash_tax_rate}
                onChange={(e) => update('cash_tax_rate', e.target.value)}
                required
              />
            </Field>
            <Field label="Налог — безнал, %" hint="На прибыль до налогов, безнал-канал">
              <input
                className="input"
                type="number"
                step="0.01"
                min="0"
                value={form.noncash_tax_rate}
                onChange={(e) => update('noncash_tax_rate', e.target.value)}
                required
              />
            </Field>
          </div>
          <button className="btn btn-primary" disabled={saving} style={{ alignSelf: 'flex-start' }}>
            {saving ? 'Сохранение…' : 'Сохранить настройки'}
          </button>
        </form>
      </div>

      <div className="card card-soft" style={{ maxWidth: 640 }}>
        <div className="caption" style={{ marginBottom: 12 }}>
          Пример расчёта для посылки 0.50 кг
        </div>
        <div className="row row-wrap">
          <Stat label="Цена для клиента" value={som(examplePrice)} />
          <Stat label="Себестоимость" value={som(exampleCost)} />
          <Stat label="Маржа" value={som((examplePrice - exampleCost).toFixed(2))} />
        </div>
      </div>
    </>
  )
}
