import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
// Ops admin page is static: public/ops-ui/index.html → dist/ops-ui/index.html
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/ops': 'http://127.0.0.1:8000',
    },
  },
})
