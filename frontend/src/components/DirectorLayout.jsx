import Layout from './Layout'
import { useAuth } from '../auth/AuthContext'
import { IconBox, IconDashboard, IconExpense, IconReports, IconSales, IconUsers } from './icons'

const DIRECTION_LABEL = {
  EXPRESS: 'Loko Express',
  BUSINESS: 'Loko Business',
}

const TITLES = {
  '/': ['Сводка', 'Как идут дела сегодня и с начала месяца'],
  '/reports': ['Финансы', 'ОПиУ и ОДДС направления за период'],
  '/workflow': ['Процесс работы', 'Кто что обрабатывает и что осталось на вечерний допоиск'],
  '/stock': ['Остаток на складе', 'Приход веса и расход по оприходованным заказам'],
  '/income': ['Доход', 'Поступления не от карго: наименование, сумма, комментарий'],
  '/expense': ['Расход', 'Операционные, инвестиционные и финансовые расходы'],
}

// Кабинет директора — та же оболочка, что у всех (светлая боковая панель),
// но со своим набором разделов. Директор видит оба направления; его направление
// в профиле — то, что открывается по умолчанию. Склад относится к Express.
export default function DirectorLayout() {
  const { user } = useAuth()
  const items = [
    { to: '/', label: 'Сводка', icon: IconDashboard, end: true },
    { to: '/reports', label: 'Финансы', icon: IconReports },
    { to: '/workflow', label: 'Процесс работы', icon: IconUsers },
    { to: '/stock', label: 'Остаток на складе', icon: IconBox },
    { to: '/income', label: 'Доход', icon: IconSales },
    { to: '/expense', label: 'Расход', icon: IconExpense },
  ]
  return (
    <Layout
      groups={[{ title: null, items }]}
      titles={TITLES}
      brand={{ title: 'Loko Express · Business', sub: `Кабинет директора${DIRECTION_LABEL[user?.module] ? ' · ' + DIRECTION_LABEL[user?.module] : ''}` }}
    />
  )
}
