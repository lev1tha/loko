import { useState } from 'react'
import { useFetch } from '../lib/hooks'
import { firstOfMonth, today, money, num, dateRu, signClass } from '../lib/format'
import { Badge, EmptyState, Field, Segmented, Spinner, Stat } from '../components/ui'

const MODULES = [
  { value: 'all', label: 'Всё' },
  { value: 'EXPRESS', label: 'Express' },
  { value: 'BUSINESS', label: 'Business' },
]

// Цвет бейджа «как влияет на отчёты»
const EFFECT_VARIANT = {
  'Выручка': 'badge-success',
  'Себестоимость': 'badge-danger',
  'Опер. расход': 'badge-danger',
  'Аванс (не выручка)': 'badge-manager',
  'Аванс (не расход)': 'badge-manager',
  'Вывод (не расход)': 'badge-admin',
  'Перемещение': 'badge-bank',
  'Не влияет на прибыль': 'badge-manager',
  'Прочее': 'badge-manager',
}

// Плитки «как сложились цифры дашборда» — клик фильтрует журнал по этим операциям
const TILES = [
  { key: 'revenue', label: 'Выручка', effect: 'Выручка', sub: 'продажи + приходы' },
  { key: 'cogs', label: 'Себестоимость', effect: 'Себестоимость', sub: 'закуп товара', neg: true },
  { key: 'opex', label: 'Опер. расходы', effect: 'Опер. расход', sub: 'прочее', neg: true },
]
const REF_TILES = [
  { key: 'advance_client', label: 'Авансы клиентов', effect: 'Аванс (не выручка)', sub: 'не выручка' },
  { key: 'advance_supplier', label: 'Авансы поставщику', effect: 'Аванс (не расход)', sub: 'не расход' },
  { key: 'owner', label: 'Изъятия собственника', effect: 'Вывод (не расход)', sub: 'вывод' },
  { key: 'repayment', label: 'Погашение долгов', effect: 'Не влияет на прибыль', sub: 'не выручка' },
]

export default function Journal() {
  const [from, setFrom] = useState(firstOfMonth())
  const [to, setTo] = useState(today())
  const [module, setModule] = useState('all')
  const [filter, setFilter] = useState(null) // фильтр по «эффекту»

  const params = { from, to, ...(module !== 'all' ? { module } : {}) }
  const data = useFetch('/reports/journal/', params)

  if (data.loading) return <Spinner full />
  const d = data.data || { operations: [], totals: {} }
  const t = d.totals || {}
  const all = d.operations || []
  const ops = filter ? all.filter((o) => o.effect === filter) : all
  const shownKgs = ops.reduce((acc, o) => acc + Number(o.amount_kgs || 0), 0)

  return (
    <>
      <div className="card card-soft">
        <div className="spread row-wrap">
          <p className="muted" style={{ margin: 0, lineHeight: 1.6, flex: '1 1 320px' }}>
            <strong>Каждое событие</strong> — как в Excel-журнале — и видно, <strong>как из них сложились цифры
            дашборда</strong>. Нажмите на плитку, чтобы оставить только операции, из которых эта цифра состоит.
          </p>
          <div className="field" style={{ alignItems: 'flex-end' }}>
            <span className="field-label">Направление</span>
            <Segmented value={module} onChange={(v) => { setModule(v); setFilter(null) }} options={MODULES} />
          </div>
        </div>
      </div>

      {/* Как сложилась прибыль */}
      <div className="grid">
        {TILES.map((tile) => (
          <button
            key={tile.key}
            className="stat"
            style={{ cursor: 'pointer', textAlign: 'left', border: filter === tile.effect ? '1px solid var(--ink)' : undefined }}
            onClick={() => setFilter(filter === tile.effect ? null : tile.effect)}
          >
            <span className="stat-label">{tile.label} ›</span>
            <span className={`stat-value ${tile.neg ? 'neg' : ''}`}>{tile.neg ? '−' : ''}{money(t[tile.key])}</span>
            <span className="stat-sub">{tile.sub}</span>
          </button>
        ))}
        <Stat label="Прибыль до налога" value={money(t.pre_tax_profit)} tone={signClass(t.pre_tax_profit)} sub="выручка − себест. − опер." />
      </div>

      {/* Справочно — показываем только ненулевые */}
      {REF_TILES.some((tile) => Number(t[tile.key])) && (
        <div className="grid">
          {REF_TILES.filter((tile) => Number(t[tile.key])).map((tile) => (
            <button
              key={tile.key}
              className="stat"
              style={{ cursor: 'pointer', textAlign: 'left', border: filter === tile.effect ? '1px solid var(--ink)' : undefined }}
              onClick={() => setFilter(filter === tile.effect ? null : tile.effect)}
            >
              <span className="stat-label">{tile.label} ›</span>
              <span className="stat-value">{money(t[tile.key])}</span>
              <span className="stat-sub">{tile.sub}</span>
            </button>
          ))}
        </div>
      )}

      <div className="card">
        <div className="card-header">
          <span className="card-title">Журнал операций · {filter || 'все события'}</span>
          <div className="toolbar">
            <Field label="С даты">
              <input className="input" type="date" value={from} onChange={(e) => setFrom(e.target.value)} />
            </Field>
            <Field label="По дату">
              <input className="input" type="date" value={to} onChange={(e) => setTo(e.target.value)} />
            </Field>
          </div>
        </div>

        <div className="caption" style={{ marginBottom: 8 }}>
          Показано {num(ops.length, 0)} {filter ? '' : `из ${num(d.count || 0, 0)} `}операций · сумма {money(shownKgs)}
          {filter && <> · <button className="btn btn-ghost btn-sm" onClick={() => setFilter(null)}>сбросить фильтр</button></>}
          {d.truncated && <> · загружены первые {num(d.shown, 0)} из {num(d.count, 0)} — сузьте период{filter ? ' (фильтр и сумма по загруженным, не по всем)' : ' для полного списка'}</>}
        </div>

        {ops.length === 0 ? (
          <EmptyState>Операций за период нет.</EmptyState>
        ) : (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>№</th>
                  <th>Дата</th>
                  <th>Напр.</th>
                  <th>Тип</th>
                  <th>Контрагент / описание</th>
                  <th>Счёт</th>
                  <th className="num">Сумма</th>
                  <th className="num">В сомах</th>
                  <th>Как влияет</th>
                </tr>
              </thead>
              <tbody>
                {ops.map((o) => (
                  <tr key={o.ref}>
                    <td className="caption muted">{o.ref}</td>
                    <td>{dateRu(o.date)}</td>
                    <td><Badge variant={o.module === 'EXPRESS' ? 'badge-cash' : 'badge-bank'}>{o.module === 'EXPRESS' ? 'Exp' : 'Biz'}</Badge></td>
                    <td>{o.type}</td>
                    <td><strong>{o.party}</strong></td>
                    <td className="muted">{o.account}</td>
                    <td className="num">{money(o.amount, o.currency)}</td>
                    <td className="num">{money(o.amount_kgs)}</td>
                    <td><Badge variant={EFFECT_VARIANT[o.effect] || 'badge-manager'}>{o.effect}</Badge></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <p className="caption mt-lg" style={{ lineHeight: 1.5 }}>
          «Как влияет» показывает, куда идёт операция в отчётах: <strong>Выручка</strong> и <strong>Себестоимость</strong> формируют
          прибыль; авансы, изъятия, переводы и конвертации деньги перемещают, но прибыль не меняют.
        </p>
      </div>
    </>
  )
}
