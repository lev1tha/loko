import { useState } from 'react'
import './Guide.css'

// Инструкция по системе для администраторов. Слева — собственная навигация по
// разделам (sticky), справа — текст со скриншотами. Скриншоты лежат в
// public/guide/<имя>.png; если файла нет — показываем аккуратную заглушку.
const SECTIONS = [
  { id: 'roles', title: 'Роли и доступ' },
  { id: 'dashboard', title: 'Сводка (дашборд)' },
  { id: 'sales', title: 'Продажи Express' },
  { id: 'client-prices', title: 'Цены клиентов' },
  { id: 'expenses', title: 'Расходы' },
  { id: 'income', title: 'Поступления и прочий доход' },
  { id: 'business', title: 'Business: депозиты, заказы, обмен' },
  { id: 'reports', title: 'Отчёты ОПиУ / ОДДС' },
  { id: 'users', title: 'Пользователи' },
  { id: 'settings', title: 'Настройки' },
]

function Figure({ src, caption }) {
  const [ok, setOk] = useState(true)
  return (
    <figure className="guide-figure">
      {ok ? (
        <img src={`/guide/${src}`} alt={caption} loading="lazy" onError={() => setOk(false)} />
      ) : (
        <div className="guide-figure-ph">
          <span className="guide-figure-ph-ico">🖼️</span>
          <span>Скриншот: {caption}</span>
          <code>public/guide/{src}</code>
        </div>
      )}
      {caption && <figcaption>{caption}</figcaption>}
    </figure>
  )
}

function Step({ n, children }) {
  return (
    <li className="guide-step">
      <span className="guide-step-n">{n}</span>
      <span>{children}</span>
    </li>
  )
}

// Описание модального окна (формы): какие поля и что делают.
function FormDoc({ title, intro, fields }) {
  return (
    <div className="guide-form">
      <div className="guide-form-title">Окно «{title}»</div>
      {intro && <p className="guide-form-intro">{intro}</p>}
      <ul className="guide-fields">
        {fields.map((f, i) => (
          <li key={i}><span className="guide-field-name">{f.name}</span> — {f.desc}</li>
        ))}
      </ul>
    </div>
  )
}

export default function Guide() {
  return (
    <div className="guide">
      <nav className="guide-toc">
        <div className="guide-toc-title">Разделы</div>
        {SECTIONS.map((s) => (
          <a key={s.id} href={`#${s.id}`} className="guide-toc-link">{s.title}</a>
        ))}
      </nav>

      <div className="guide-body">
        <div className="card">
          <h2 className="card-title">Инструкция по системе</h2>
          <p className="caption" style={{ margin: '6px 0 0', lineHeight: 1.6 }}>
            Краткое руководство для администратора: что делает каждый раздел и как им пользоваться.
            Слева — навигация по разделам. Money везде в сомах; юань пересчитывается по курсу из Настроек.
          </p>
        </div>

        <section id="roles" className="card guide-section">
          <h3>Роли и доступ</h3>
          <p>В системе четыре роли — каждая видит только своё:</p>
          <ul className="guide-list">
            <li><strong>Администратор</strong> — полный доступ: операции, отчёты, настройки, пользователи.</li>
            <li><strong>Кассир/Менеджер</strong> — вводит операции (продажи, расходы, депозиты, переводы) и смотрит отчёты.</li>
            <li><strong>Директор</strong> — только просмотр (read-only) отчётов ОПиУ/ОДДС <em>своего направления</em> (Express или Business). Ничего не меняет.</li>
            <li><strong>Сотрудник</strong> — только добавление продаж Express, без доступа к финансам.</li>
          </ul>
          <Figure src="roles.png" caption="Боковая навигация администратора" />
        </section>

        <section id="dashboard" className="card guide-section">
          <h3>Сводка (дашборд)</h3>
          <p>Стартовый экран: деньги на счетах, выручка и прибыль за месяц — отдельно по Express и Business.</p>
          <Figure src="dashboard.png" caption="Сводка: Express и Business рядом" />
        </section>

        <section id="sales" className="card guide-section">
          <h3>Продажи Express</h3>
          <p>Учёт карго (Китай → Кыргызстан). Два режима суммы:</p>
          <ul className="guide-list">
            <li><strong>Прямая сумма</strong> — вводите итоговую сумму; вес считается ориентировочно (показывается как «≈»).</li>
            <li><strong>По весу</strong> — вводите вес, сумма = вес × цена за кг × курс.</li>
          </ul>
          <ol className="guide-steps">
            <Step n="1">Нажмите «Новая продажа».</Step>
            <Step n="2">Выберите режим, укажите код клиента и сумму (или вес).</Step>
            <Step n="3">Выберите счёт зачисления (нал/безнал) и дату.</Step>
            <Step n="4">«Создать продажу». В списке колонки можно сортировать кликом по заголовку.</Step>
          </ol>
          <FormDoc
            title="Новая продажа"
            intro="Открывается кнопкой «Новая продажа». Создаёт запись продажи Express."
            fields={[
              { name: 'Режим суммы', desc: '«Прямая сумма» (ввод итога) или «По весу» (итог = вес × цена за кг).' },
              { name: 'Код клиента', desc: 'обязателен — номер/код клиента или товара.' },
              { name: 'Сумма / Вес', desc: 'в зависимости от режима; в «прямой сумме» рядом показывается расчётный вес.' },
              { name: 'Цена за кг (только админ/менеджер)', desc: 'индивидуальная цена; подставляется из «цены клиента», можно переопределить.' },
              { name: 'Кол-во мест', desc: 'число коробок (вес места × мест = итоговый вес).' },
              { name: 'Счёт зачисления', desc: 'касса/банк (нал/безнал) — куда поступила оплата.' },
              { name: 'Дата операции', desc: 'дата для ОПиУ (у сотрудника — всегда сегодня).' },
            ]}
          />
          <Figure src="sales.png" caption="Список продаж: сортировка по колонкам, расчётный вес «≈»" />
        </section>

        <section id="client-prices" className="card guide-section">
          <h3>Цены клиентов</h3>
          <p>
            По умолчанию цена за кг берётся из Настроек (≈270 сом). Для отдельных клиентов можно задать
            свою цену (например 250 или 220 сом/кг) — она подставится автоматически при новой продаже «по весу».
          </p>
          <ol className="guide-steps">
            <Step n="1">Раздел «Цены клиентов» → «Цена клиента».</Step>
            <Step n="2">Укажите код клиента и цену за кг.</Step>
            <Step n="3">В новой продаже при вводе этого кода цена подставится сама (её можно переопределить).</Step>
          </ol>
          <FormDoc
            title="Цена клиента"
            intro="Сохранение по коду — «upsert»: повторная запись для того же кода обновляет цену, а не создаёт дубль."
            fields={[
              { name: 'Код клиента', desc: 'точный код, как в продажах.' },
              { name: 'Цена за 1 кг, сом', desc: 'индивидуальная цена (например 250 или 220).' },
              { name: 'Комментарий', desc: 'необязательно — например «постоянный клиент».' },
            ]}
          />
          <p className="caption" style={{ marginTop: 8 }}>
            У сотрудника в форме продажи есть кнопка «Уникальная цена»: задаёт цену за кг для клиента — вес не меняется,
            пересчитывается стоимость, и выбор сохраняется в продаже (виден в системе). Сохранённая цена клиента также
            применяется автоматически в режиме «по весу».
          </p>
          <Figure src="client-prices.png" caption="Индивидуальные цены за кг по клиентам" />
        </section>

        <section id="expenses" className="card guide-section">
          <h3>Расходы</h3>
          <p>У каждого расхода — категория и статья, это определяет, как он попадает в отчёты:</p>
          <ul className="guide-list">
            <li><strong>Операционные (OpEx)</strong> — аренда, <strong>ФОТ (зарплата)</strong>, подоходный, соц.фонд, прочие → уменьшают прибыль (ОПиУ + ОДДС).</li>
            <li><strong>Себестоимость / закуп</strong>, <strong>Оплата поставщику</strong> — движение денег (ОДДС).</li>
            <li><strong>Изъятие собственника</strong> (вывод средств себе) — финансовая деятельность, прибыль <em>не</em> уменьшает.</li>
            <li><strong>Инвестиции</strong> и <strong>Финансовая</strong> (кредиты/проценты) — отдельные разделы ОДДС.</li>
          </ul>
          <FormDoc
            title="Новый расход"
            intro="Создаёт расход и списывает его со счёта. Разделение «начислено / оплачено» даёт кредиторку."
            fields={[
              { name: 'Категория расхода', desc: 'OpEx / Себестоимость / Поставщик / Изъятие / Инвестиции / Финансовая / Другое.' },
              { name: 'Статья', desc: 'для OpEx/Инвест/Финанс — Аренда, ФОТ, Подоходный, Соц.фонд и т.д. («Прочие» требует комментарий).' },
              { name: 'Счёт списания', desc: 'откуда уходят деньги (валюта счёта — сом или юань).' },
              { name: 'Сумма начисления', desc: 'сколько начислено (для ОПиУ).' },
              { name: 'Оплачено', desc: 'сколько фактически оплачено (пусто = полностью); разница = кредиторка.' },
              { name: 'Дата операции / Дата оплаты', desc: 'для ОПиУ и для ОДДС соответственно.' },
              { name: 'Комментарий', desc: 'назначение платежа.' },
            ]}
          />
          <Figure src="expenses.png" caption="Расход: выбор категории и статьи" />
        </section>

        <section id="income" className="card guide-section">
          <h3>Поступления и прочий доход</h3>
          <p>
            Доходы не от продаж/депозитов (возмещения, услуги). В Express — «Прочий доход», в Business — «Поступления».
            Входят в выручку ОПиУ (без себестоимости) и в приток ОДДС.
          </p>
          <FormDoc
            title="Поступление / Прочий доход"
            fields={[
              { name: 'Счёт зачисления', desc: 'куда поступили деньги.' },
              { name: 'Сумма', desc: 'в валюте счёта (юань пересчитается в сом по курсу).' },
              { name: 'Дата', desc: 'дата поступления.' },
              { name: 'Источник / комментарий', desc: 'например «возмещение», «услуга».' },
            ]}
          />
          <Figure src="income.png" caption="Поступления Business" />
        </section>

        <section id="business" className="card guide-section">
          <h3>Business: депозиты, заказы, обмен</h3>
          <ul className="guide-list">
            <li><strong>Депозиты</strong> — приходы клиентов. Создаются как аванс; выручкой становятся только после «признания».</li>
            <li><strong>Заказы</strong> — маржа по клиентам: выручка − закуп.</li>
            <li><strong>Обмен и переводы</strong> — покупка юаня и движение между счетами (мультивалютность).</li>
          </ul>
          <FormDoc
            title="Депозит"
            intro="Создаётся как аванс клиента (HELD). Действия в списке: «Признать выручкой» (попадёт в ОПиУ) или «Отправить поставщику» (создаст расход)."
            fields={[
              { name: 'Счёт / Источник', desc: 'куда принят депозит и от кого (клиент).' },
              { name: 'Сумма', desc: 'в валюте счёта.' },
              { name: 'Дата', desc: 'дата получения.' },
            ]}
          />
          <FormDoc
            title="Перевод / Конвертация"
            intro="Движение денег между счетами; при разных валютах — конвертация (покупка юаня)."
            fields={[
              { name: 'Со счёта / На счёт', desc: 'источник и получатель (разные счета).' },
              { name: 'Сумма списания / зачисления', desc: 'сколько ушло и сколько пришло.' },
              { name: 'Курс обмена', desc: 'сом за 1 юань — обязателен при конвертации.' },
            ]}
          />
          <Figure src="business.png" caption="Депозиты и признание выручки" />
        </section>

        <section id="reports" className="card guide-section">
          <h3>Отчёты ОПиУ / ОДДС</h3>
          <ul className="guide-list">
            <li><strong>ОПиУ (P&L)</strong> — прибыль по начислению (по дате операции).</li>
            <li><strong>ОДДС (Cash Flow)</strong> — движение денег по трём видам деятельности.</li>
            <li>Период, направление и канал оплаты — фильтрами сверху. Есть помесячный вид.</li>
            <li>Клик по строке («›») открывает расшифровку — все операции за ней, с типом/статьёй.</li>
          </ul>
          <Figure src="reports.png" caption="ОПиУ и расшифровка строки" />
        </section>

        <section id="users" className="card guide-section">
          <h3>Пользователи</h3>
          <ol className="guide-steps">
            <Step n="1">«Новый пользователь»: логин, имя, роль, пароль.</Step>
            <Step n="2">Для роли «Директор» обязательно укажите направление (Express или Business).</Step>
            <Step n="3">Удалить пользователя — корзиной в строке (свою учётку удалить нельзя).</Step>
          </ol>
          <FormDoc
            title="Новый пользователь"
            fields={[
              { name: 'Логин', desc: 'имя для входа.' },
              { name: 'Имя', desc: 'отображаемое имя (необязательно).' },
              { name: 'Роль', desc: 'Администратор / Кассир-менеджер / Директор / Сотрудник.' },
              { name: 'Направление директора', desc: 'появляется для роли «Директор» — Express или Business (обязательно).' },
              { name: 'Пароль', desc: 'минимум 6 символов.' },
            ]}
          />
          <Figure src="users.png" caption="Управление пользователями и ролями" />
        </section>

        <section id="settings" className="card guide-section">
          <h3>Настройки</h3>
          <p>
            Курсы (доллар, юань), цена и себестоимость за кг, ставки налога. Меняются без перевыпуска —
            новые операции считаются по актуальным значениям, история не «плывёт» (курс снапшотится на операции).
          </p>
          <Figure src="settings.png" caption="Ценообразование, курсы и налоги" />
        </section>
      </div>
    </div>
  )
}
