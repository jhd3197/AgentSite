# Vite + React + Tailwind — Template Contract

Read this file before writing any code. It defines how this project is structured.
Follow it exactly so dev, build, preview, and exports keep working.

## 1. Stack & how it runs

- Vite 6 + React 19 + Tailwind CSS 4 (CSS-first config) + react-router-dom 7.
- `npm install` once, then `npm run build` produces the deployable static site in
  `dist/`; `npm run dev` starts a hot-reload dev server. The platform runs these.
- Routing uses **HashRouter** (URLs like `/#/pricing`). The built app is served
  from a subpath and from exported zips, where BrowserRouter URLs would 404.
  **NEVER switch to BrowserRouter**, and never remove `base: './'` from
  `vite.config.js` — both are required for relative-path hosting.
- Avoid raw in-page anchors (`<a href="#section">`): the `#` fragment is owned by
  the router. To scroll within a page, call `element.scrollIntoView()` instead.

## 2. Directory layout

| Path                     | Purpose                                                              |
| ------------------------ | -------------------------------------------------------------------- |
| `index.html`             | Vite entry shell (protected): fonts + `<div id="root">`.              |
| `src/main.jsx`           | Bootstraps React and imports `src/index.css`.                         |
| `src/App.jsx`            | HashRouter + `<Routes>` wrapped by SiteHeader/SiteFooter. Routes are registered here. |
| `src/pages/`             | One file per routed page (`Home.jsx`, `Pricing.jsx`, ...).            |
| `src/components/`        | Shared UI (SiteHeader, SiteFooter, cards, buttons, ...).              |
| `src/index.css`          | Imports Tailwind, then the tokens file. Rarely needs changes.         |
| `src/styles/tokens.css`  | Tailwind 4 `@theme` design tokens. The Designer agent owns this file. |
| `public/uploads/`        | User-uploaded files, copied verbatim into the build.                  |
| `public/`                | Other static assets that should ship unprocessed.                     |

## 3. Conventions

### Adding a page — all three steps, every time
1. Create `src/pages/PageName.jsx` with a default-export component.
2. Register it in `src/App.jsx`: `<Route path="/page-name" element={<PageName />} />`.
3. Add it to the `navLinks` array in `src/components/SiteHeader.jsx`.

A page missing any step is broken: unreachable, unrouted, or invisible in the nav.

### Components & styling
- Shared or repeated UI goes in `src/components/`; keep components small and focused.
- Style with Tailwind utilities that reference the theme tokens: `bg-primary`,
  `hover:bg-secondary`, `text-text`, `text-text-secondary`, `bg-surface`,
  `border-border`, `bg-accent`, `font-heading`, `font-body`, `rounded-sm`,
  `rounded-lg`, and so on.
- Design tokens (colors, fonts, radii) live ONLY in the `@theme` block of
  `src/styles/tokens.css`. Never hardcode hex values in JSX or CSS; if a needed
  token is missing, add it to that file's `@theme` block.
- Use `Link` (or `NavLink`) from react-router-dom for internal navigation —
  never a raw `<a href>` for in-app routes.

## 4. Protected files (from the manifest)

`package.json`, `vite.config.js`, `index.html`

- Edit only when strictly necessary (for example, the user's feature genuinely
  requires a new npm dependency). Never rewrite them wholesale.
- Never change: the `scripts` in `package.json`; the plugins, `base`, or `outDir`
  in `vite.config.js`; the `#root` div or module script tag in `index.html`.

## 5. User uploads

- Files the user uploads land in `public/uploads/`. Reference them with relative
  paths: `<img src="./uploads/logo.png" alt="Acme logo">`. This works in dev, in
  the built app, and in exports (thanks to `base: './'` plus hash routing).
- When the user has provided images, use them instead of stock placeholders.

## 6. Quality bar

- Semantic HTML inside JSX: `header`, `nav`, `main`, `section`, `footer`,
  ordered headings, one `<h1>` per page.
- Responsive and mobile-first; `md:` (768px) is the primary breakpoint.
- Accessible: alt text on every image, `focus-visible` states preserved,
  `aria-expanded` kept in sync on the mobile menu, WCAG AA contrast.
- Real content per the user's request — no lorem-ipsum walls, no `TODO` comments,
  no dead links: every `Route` reachable from the nav, every nav item resolving
  to a real `Route`.
- Code must build cleanly with `npm run build`: valid JSX, correct import paths,
  no unused leftover files.

## 7. Workflow

- Read existing files before editing them; match the patterns already there.
- Prefer targeted edits (`edit_file`) over rewriting whole files.
- Keep components small; extract repeated JSX into `src/components/`.
- After structural changes, trace the chain: page file exists → `Route` in
  `App.jsx` → entry in `navLinks` — all three or it isn't done.
