import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig(({ mode }) => {
  // Load .env files so VITE_BACKEND_URL is available here in the config.
  const env = loadEnv(mode, process.cwd(), '')
  const backend = env.VITE_BACKEND_URL || 'http://127.0.0.1:8000'

  return {
    plugins: [react()],
    // Production build settings for Cloudflare Pages (static assets in dist/).
    base: '/',
    build: {
      outDir: 'dist',
      sourcemap: false,
      chunkSizeWarningLimit: 1200,
    },
    server: {
      port: 5173,
      // Proxy API calls to the Django backend during DEVELOPMENT only.
      // In production the frontend calls VITE_API_BASE_URL directly (no proxy).
      proxy: {
        '/api': {
          target: backend,
          changeOrigin: true,
        },
      },
    },
  }
})
