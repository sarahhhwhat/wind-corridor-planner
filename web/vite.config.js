import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// base '/' so all data fetches use root-relative paths (works on Amplify)
export default defineConfig({
  plugins: [react()],
  base: '/',
})
