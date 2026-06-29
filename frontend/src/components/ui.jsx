// Small reusable UI primitives styled by index.css (Cal.com design tokens).
import { IconClose } from './icons'

export function Spinner({ full }) {
  if (full) {
    return (
      <div className="center-screen">
        <div className="spinner" />
      </div>
    )
  }
  return <div className="spinner" />
}

export function Field({ label, hint, error, children }) {
  return (
    <label className="field">
      {label && <span className="field-label">{label}</span>}
      {children}
      {hint && !error && <span className="field-hint">{hint}</span>}
      {error && <span className="field-error">{error}</span>}
    </label>
  )
}

export function Stat({ label, value, sub, tone }) {
  return (
    <div className="stat">
      <span className="stat-label">{label}</span>
      <span className={`stat-value ${tone || ''}`}>{value}</span>
      {sub != null && <span className="stat-sub">{sub}</span>}
    </div>
  )
}

export function Badge({ children, variant = '' }) {
  return <span className={`badge ${variant}`}>{children}</span>
}

export function Alert({ kind = 'error', children }) {
  if (!children) return null
  return <div className={`alert alert-${kind}`}>{children}</div>
}

export function EmptyState({ children }) {
  return <div className="empty">{children}</div>
}

export function Modal({ title, onClose, children, footer, wide }) {
  return (
    <div className="modal-overlay" onMouseDown={onClose}>
      <div className={`modal ${wide ? 'modal-wide' : ''}`} onMouseDown={(e) => e.stopPropagation()}>
        <div className="modal-head">
          <h3 className="card-title">{title}</h3>
          <button className="btn btn-icon btn-ghost" onClick={onClose} aria-label="Закрыть">
            <IconClose />
          </button>
        </div>
        <div className="modal-body">{children}</div>
        {footer && <div className="modal-foot">{footer}</div>}
      </div>
    </div>
  )
}

export function Segmented({ value, onChange, options }) {
  return (
    <div className="segmented" role="tablist">
      {options.map((opt) => (
        <button
          key={opt.value}
          className={value === opt.value ? 'active' : ''}
          onClick={() => onChange(opt.value)}
          type="button"
        >
          {opt.label}
        </button>
      ))}
    </div>
  )
}
