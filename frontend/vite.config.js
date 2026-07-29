import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      // 本機開發時把 /api 與 /health 轉發到後端，前端因此可以用相對路徑呼叫，
      // 不需要設定 VITE_API_BASE_URL，也不會遇到 CORS。
      // 埠號 8000 是 uvicorn 的預設值（Flask 版是 5000）。
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
      '/health': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/tests/setup.js'],
  },
})
