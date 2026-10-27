import { loadEnv } from 'vite'
import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')

  const AI_NAME = env.AI_NAME || ''
  const DEV_API_TARGET = env.VITE_DEV_API_TARGET || 'http://localhost:8080'

  return {
    plugins: [react()],
    base: AI_NAME ? `/${AI_NAME}/` : '/',
    server: {
      proxy: {
        '/api/upload-document': {
          target: DEV_API_TARGET,
          changeOrigin: true,
          secure: false,
          rewrite: (path: string) => path.replace(/^\/api/, ''),
          // LlamaParse and other loaders can take several minutes for large PDFs.
          timeout: 600_000,
        },
        '/api': {
          target: DEV_API_TARGET,
          changeOrigin: true,
          secure: false,
          rewrite: (path: string) => path.replace(/^\/api/, ''),
        },
      },
    },
    test: {
      environment: 'jsdom',
      setupFiles: './src/tests/setupTests.ts',
      include: ['src/**/*.{test,spec}.{ts,tsx}'],
      exclude: ['e2e/**', 'node_modules/**', 'dist/**'],
      coverage: {
        reporter: ['text', 'json-summary', 'lcov', 'html'],
        reportsDirectory: './coverage',
      },
    },
  }
})
