import { Component } from 'react'
import { ErrorTruck } from './states'

// Ловит ошибки рендера в дереве и показывает состояние «фура застряла».
export default class ErrorBoundary extends Component {
  constructor(props) {
    super(props)
    this.state = { error: null }
  }

  static getDerivedStateFromError(error) {
    return { error }
  }

  componentDidCatch(error, info) {
    // eslint-disable-next-line no-console
    console.error('UI error boundary:', error, info)
  }

  render() {
    if (this.state.error) {
      return (
        <ErrorTruck
          title="Груз застрял в пути"
          text="Что-то пошло не так при загрузке страницы. Попробуйте обновить — мы уже разворачиваем фуру обратно."
          action={
            <button className="btn btn-primary" onClick={() => window.location.reload()}>
              Обновить страницу
            </button>
          }
        />
      )
    }
    return this.props.children
  }
}
