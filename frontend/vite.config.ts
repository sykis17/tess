import { fileURLToPath, URL } from 'node:url'
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  build: {
    rollupOptions: {
      input: {
        main: fileURLToPath(new URL('./index.html', import.meta.url)),
        opsUi: fileURLToPath(new URL('./ops-ui/index.html', import.meta.url)),
      },
    },
  },
  server: {
    proxy: {
      '/ops': 'http://127.0.0.1:8000',
    },
  },
})
