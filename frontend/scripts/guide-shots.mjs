// Генерация скриншотов для страницы «Инструкция» (public/guide/*.png).
// Запуск: node scripts/guide-shots.mjs  (нужны запущенные dev-сервер :5174 и backend :8009)
import { chromium } from 'playwright'
import { mkdirSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

const APP = 'http://localhost:5174'
const API = 'http://127.0.0.1:8009/api'
const OUT = join(dirname(fileURLToPath(import.meta.url)), '..', 'public', 'guide')

const SHOTS = [
  { file: 'dashboard.png', path: '/' },
  { file: 'roles.png', path: '/', selector: '.sidebar' },
  { file: 'sales.png', path: '/sales' },
  { file: 'client-prices.png', path: '/express/client-prices' },
  { file: 'expenses.png', path: '/express/expenses' },
  { file: 'income.png', path: '/business/other-income' },
  { file: 'business.png', path: '/business/deposits' },
  { file: 'reports.png', path: '/reports' },
  { file: 'users.png', path: '/users' },
  { file: 'settings.png', path: '/settings' },
]

const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

async function main() {
  mkdirSync(OUT, { recursive: true })
  const res = await fetch(`${API}/auth/login/`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username: 'admin', password: 'admin123' }),
  })
  const { access, refresh } = await res.json()
  if (!access) throw new Error('login failed')

  const browser = await chromium.launch()
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 2 })
  await ctx.addInitScript(([a, r]) => {
    localStorage.setItem('loko_access', a)
    localStorage.setItem('loko_refresh', r)
  }, [access, refresh])
  const page = await ctx.newPage()

  for (const s of SHOTS) {
    await page.goto(`${APP}${s.path}`, { waitUntil: 'networkidle' })
    await sleep(900) // дать таблицам/графикам дорисоваться
    const target = s.selector ? page.locator(s.selector) : page
    await target.screenshot({ path: join(OUT, s.file) })
    console.log('✓', s.file)
  }

  await browser.close()
}

main().catch((e) => { console.error(e); process.exit(1) })
