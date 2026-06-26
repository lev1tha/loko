import { Link } from 'react-router-dom'
import { ErrorTruck } from '../components/states'

// Страница 404 — «такого груза нет».
export default function NotFound() {
  return (
    <ErrorTruck
      title="Такого груза нет"
      text="Кажется, ты где-то ошибся — такой страницы нет. Проверь адрес или вернись на главную."
      action={
        <Link className="btn btn-primary" to="/">
          Вернуться на главную
        </Link>
      }
    />
  )
}
