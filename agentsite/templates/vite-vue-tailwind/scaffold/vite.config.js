import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import tailwindcss from '@tailwindcss/vite'

// Protected file — managed by AgentSite.
// `base: './'` keeps built asset URLs relative so the app works when served
// from any subpath and when opened from an exported zip. Do not change it.
export default defineConfig({
  plugins: [vue(), tailwindcss()],
  base: './',
  build: {
    outDir: 'dist',
  },
})
