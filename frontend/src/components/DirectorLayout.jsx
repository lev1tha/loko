import Layout from './Layout'
import { useAuth } from '../auth/AuthContext'
import { IconBox, IconDashboard, IconReports, IconUsers } from './icons'

const DIRECTION_LABEL = {
  EXPRESS: 'Loko Express',
  BUSINESS: 'Loko Business',
}

const TITLES = {
  '/': ['Сводка', 'Как идут дела сегодня и с начала месяца'],
  '/reports': ['Финансы', 'ОПиУ и ОДДС направления за период'],
  '/workflow': ['Процесс работы', 'Кто что обрабатывает и что осталось на вечерний допоиск'],
  '/stock': ['Остаток на складе', 'Приход веса и расход по оприходованным заказам'],
}

// Кабинет директора — та же оболочка, что у всех (светлая боковая панель),
// но со своим набором разделов. Склад есть только у Loko Express.
export default function DirectorLayout() {
  const { user } = useAuth()
  const hasWarehouse = user?.module === 'EXPRESS'
  const items = [
    { to: '/', label: 'Сводка', icon: IconDashboard, end: true },
    { to: '/reports', label: 'Финансы', icon: IconReports },
  ]
  if (hasWarehouse) {
    items.push({ to: '/workflow', label: 'Процесс работы', icon: IconUsers })
    items.push({ to: '/stock', label: 'Остаток на складе', icon: IconBox })
  }
  return (
    <Layout
      groups={[{ title: null, items }]}
      titles={TITLES}
      brand={{ title: DIRECTION_LABEL[user?.module] || 'Loko ERP', sub: 'Кабинет директора' }}
    />
  )
}
