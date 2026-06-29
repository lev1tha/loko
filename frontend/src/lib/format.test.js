import { describe, it, expect } from 'vitest'
import { kg, num, firstOfMonth, today } from './format'

describe('kg() — вес с 2 знаками после запятой', () => {
  it('округляет до 2 знаков (0,00)', () => {
    expect(kg(2.5)).toBe('2,50 кг')
    expect(kg(0.8)).toBe('0,80 кг')
  })
  it('всегда ровно 2 знака после запятой', () => {
    expect(kg(100)).toMatch(/,\d{2} кг$/)
    expect(kg(1234.567)).toMatch(/,\d{2} кг$/) // округление, не 3 знака
  })
})

describe('num()', () => {
  it('целое без дробной части при digits=0', () => {
    expect(num(5, 0)).toBe('5')
  })
})

describe('даты периода', () => {
  it('firstOfMonth — это 1-е число текущего месяца', () => {
    expect(firstOfMonth()).toMatch(/^\d{4}-\d{2}-01$/)
  })
  it('today — корректный YYYY-MM-DD', () => {
    expect(today()).toMatch(/^\d{4}-\d{2}-\d{2}$/)
  })
  it('firstOfMonth и today в одном месяце (новый месяц → новая дата)', () => {
    expect(firstOfMonth().slice(0, 7)).toBe(today().slice(0, 7))
  })
})
