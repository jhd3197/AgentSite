import { defineConfig } from 'astro/config'

// Protected file — managed by AgentSite.
// `build.format: 'file'` emits `about.html`-style pages (not directories) so
// plain relative links like `about.html` work identically in dev, in the
// build, and in exports. Do not change it.
// `build.inlineStylesheets: 'always'` inlines the compiled CSS into each page
// so the build contains no root-absolute asset URLs — it works when served
// from any subpath and when opened from an exported zip. Do not change it.
export default defineConfig({
  build: {
    format: 'file',
    inlineStylesheets: 'always',
  },
  outDir: 'dist',
})
