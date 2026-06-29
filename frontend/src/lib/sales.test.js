import { describe, it, expect } from 'vitest'
import { sortValue, compareRows } from './sales'

const A = { date: '2026-06-01', client_code: '29520', account_name: 'Наличные', weight_kg: '2.50', price_som: '1000', margin_som: '300' }
const B = { date: '2026-06-10', client_code: '10010', account_name: 'МБанк', weight_kg: null, est_weight_kg: '5.00', price_som: '500', margin_som: '900' }

describe('sortValue', () => {
  it('вес: берёт est_weight_kg, если weight_kg пуст', () => {
    expect(sortValue(B, 'weight')).toBe(5)
    expect(sortValue(A, 'weight')).toBe(2.5)
  })
  it('числовые колонки приводятся к числу', () => {
    expect(sortValue(A, 'price_som')).toBe(1000)
    expect(sortValue(A, 'margin_som')).toBe(300)
  })
})

describe('compareRows', () => {
  it('сортировка по сумме по возрастанию', () => {
    expect([A, B].sort((x, y) => compareRows(x, y, 'price_som', 'asc'))[0]).toBe(B)
  })
  it('сортировка по дате по убыванию', () => {
    expect([A, B].sort((x, y) => compareRows(x, y, 'date', 'desc'))[0]).toBe(B)
  })
  it('сортировка по коду клиента (строка)', () => {
    expect([A, B].sort((x, y) => compareRows(x, y, 'client_code', 'asc'))[0]).toBe(B) // '10010' < '29520'
  })
})
