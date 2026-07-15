import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  build: {
    chunkSizeWarningLimit: 900,
    rollupOptions: {
      output: {
        manualChunks: {
          react: ['react', 'react-dom', 'react-router-dom'],
          terminal: ['@xterm/xterm', '@xterm/addon-fit'],
          icons: ['lucide-react'],
          antd: ['antd'],
        },
      },
    },
  },
  server: {
    port: 5173,
    allowedHosts: true,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: false,
        ws: true,
      },
      '/health': 'http://127.0.0.1:8000',
    },
  },
})
