// Состояния «фура»: загрузка (грузовик едет, ищет груз) и ошибка/404 (пустой кузов).
// Тема — карго Loko: «груз» = данные. SVG на токенах дизайна, анимация по CSS.

function CargoTruck({ animated = false, empty = false }) {
  return (
    <svg
      className={`truck-svg${animated ? ' is-driving' : ''}${empty ? ' is-empty' : ''}`}
      viewBox="0 0 280 160"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      role="img"
      aria-hidden="true"
    >
      {/* тень */}
      <ellipse className="truck-shadow" cx="140" cy="142" rx="112" ry="8" fill="var(--ink)" opacity="0.06" />

      {/* линии движения (анимируются при загрузке) */}
      <g className="truck-motion" stroke="var(--muted-soft)" strokeWidth="3" strokeLinecap="round">
        <line x1="6" y1="56" x2="28" y2="56" />
        <line x1="0" y1="84" x2="20" y2="84" />
        <line x1="8" y1="108" x2="26" y2="108" />
      </g>

      <g className="truck-body">
        {/* грузовой кузов */}
        <rect x="34" y="40" width="138" height="72" rx="8" fill="var(--surface-soft)" stroke="var(--ink)" strokeWidth="3" />

        {/* содержимое кузова: пусто (?) для ошибки, посылка для загрузки */}
        {empty ? (
          <>
            <rect x="54" y="56" width="98" height="40" rx="6" fill="none" stroke="var(--muted-soft)" strokeWidth="2.5" strokeDasharray="7 7" />
            <text x="103" y="86" textAnchor="middle" fontSize="34" fontWeight="700" fill="var(--muted)" fontFamily="inherit">?</text>
          </>
        ) : (
          <g className="truck-parcel">
            <rect x="80" y="58" width="46" height="42" rx="5" fill="var(--canvas)" stroke="var(--ink)" strokeWidth="2.5" />
            <line x1="103" y1="58" x2="103" y2="100" stroke="var(--ink)" strokeWidth="2.5" />
            <line x1="80" y1="79" x2="126" y2="79" stroke="var(--ink)" strokeWidth="2.5" />
          </g>
        )}

        {/* кабина */}
        <path d="M172 112 V72 H200 V60 H221 L247 90 V112 Z" fill="var(--primary)" stroke="var(--ink)" strokeWidth="3" strokeLinejoin="round" />
        {/* лобовое окно */}
        <path d="M205 74 H220 L239 90 H205 Z" fill="var(--canvas)" stroke="var(--ink)" strokeWidth="2" strokeLinejoin="round" />
        {/* фара */}
        <circle cx="243" cy="104" r="3.2" fill="#f5a623" />

        {/* колёса со спицами (крутятся при загрузке) */}
        <g className="truck-wheel">
          <circle cx="74" cy="120" r="18" fill="var(--ink)" />
          <circle cx="74" cy="120" r="7" fill="var(--canvas)" />
          <path d="M74 104 V112 M74 128 V136 M58 120 H66 M82 120 H90" stroke="var(--canvas)" strokeWidth="3" strokeLinecap="round" />
        </g>
        <g className="truck-wheel">
          <circle cx="214" cy="120" r="18" fill="var(--ink)" />
          <circle cx="214" cy="120" r="7" fill="var(--canvas)" />
          <path d="M214 104 V112 M214 128 V136 M198 120 H206 M222 120 H230" stroke="var(--canvas)" strokeWidth="3" strokeLinecap="round" />
        </g>
      </g>
    </svg>
  )
}

// Полноэкранная загрузка: «Ща найдём мы твой груз, не грусти…»
export function LoadingTruck({ text = 'Ща найдём мы твой груз, не грусти…' }) {
  return (
    <div className="state-screen" role="status" aria-live="polite">
      <CargoTruck animated />
      <p className="state-text">{text}</p>
    </div>
  )
}

// Состояние ошибки/404: «Такого груза нет — ты где-то ошибся».
export function ErrorTruck({
  title = 'Такого груза нет',
  text = 'Кажется, ты где-то ошибся — мы не нашли то, что искали.',
  action = null,
}) {
  return (
    <div className="state-screen" role="alert">
      <CargoTruck empty />
      <h2 className="state-title">{title}</h2>
      <p className="state-text">{text}</p>
      {action && <div className="state-action">{action}</div>}
    </div>
  )
}
