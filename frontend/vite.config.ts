import { fileURLToPath, URL } from 'node:url'
import vue from '@vitejs/plugin-vue'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  server: {
    port: 5173,
    proxy: {
      // 后端 FastAPI 起在 8000，前端只写 /api/xxx，dev 阶段由 Vite 转发
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
      // WebSocket 长连接同样转发，后端路径为 /ws/device
      '/ws': {
        target: 'ws://127.0.0.1:8000',
        ws: true,
      },
    },
  },
})
