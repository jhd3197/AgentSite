# Astro Multi-Page Site — Template Contract

Read this file before writing any code. It defines how this project is structured.
Follow it exactly so dev, build, preview, and exports keep working.

## 1. Stack & how it runs

- Astro 7 (no UI framework, no Tailwind) compiling to a plain static site.
- `npm install` once, then `npm run build` produces the deployable static site in
  `dist/`; `npm run dev` starts a hot-reload dev server. The platform runs these.
- `astro.config.mjs` sets `build.format: 'file'` (pages emit as `about.html`,
  not `about/index.html`) and `build.inlineStylesheets: 'always'` (compiled CSS
  is inlined into each page, so the build has no root-absolute asset URLs).
  Together they make the built site work from any subpath and from exported
  zips. **NEVER change them.**
- Because pages build to sibling `.html` files, internal links are plain
  relative filenames: `href="about.html"` — never `/about` or `/about/`.
- Keep media in `public/` and reference it relatively (`./uploads/photo.jpg`)
  so it stays unprocessed and subpath-safe. Never import images through
  `src/assets` — processed assets get root-absolute URLs that break exports.

## 2. Directory layout

| Path                     | Purpose                                                              |
| ------------------------ | -------------------------------------------------------------------- |
| `src/pages/*.astro`      | One file per page: `index.astro`, `about.astro`, `contact.astro`, ... |
| `src/layouts/Base.astro` | The shared site shell: `<head>`, header + nav, footer, mobile-nav script. Every page uses it. |
| `src/components/`        | Optional reusable `.astro` partials (cards, sections, ...). Create the folder when you need it. |
| `src/styles/tokens.css`  | Design tokens (CSS custom properties). The Designer agent owns this file. |
| `src/styles/conventions.css` | AgentSite house system (platform-owned): `.ph` image-placeholder blocks, `[data-reveal]`/`[data-reveal-group]` load choreography, focus rings. Use its classes; never edit it. |
| `src/styles/main.css`    | All site styles. Consumes tokens via `var(--...)` only.               |
| `public/uploads/`        | User-uploaded files, copied verbatim into the build.                  |
| `public/`                | Other static assets that should ship unprocessed.                     |

## 3. Conventions

### Adding a page — both steps, every time
1. Create `src/pages/page-name.astro` (lowercase, hyphenated). Its entire body
   is wrapped in the shared layout:
   ```astro
   ---
   import Base from '../layouts/Base.astro'
   ---
   <Base title="Page Name" current="page-name">
     ...
   </Base>
   ```
2. Add it to the `navLinks` array in `src/layouts/Base.astro`
   (`{ href: 'page-name.html', label: 'Page Name', key: 'page-name' }`).

A page missing step 2 is unreachable; a nav entry without a page is a dead link.
The `current` prop drives the `.is-active` nav highlight and `aria-current="page"`.

### Styling
- `src/styles/tokens.css` is the single source of design truth — colors, fonts,
  sizes, spacing, radii, shadows. The Designer agent rewrites it; do not fight
  its values. The layout imports it (then `main.css`, then `conventions.css`)
  in its frontmatter — never import styles anywhere else.
- `main.css` must consume tokens only: `color: var(--color-text)`, never
  `#1f2937`. If a token you need does not exist, use the closest existing one.
- Reuse the class patterns already in `main.css` (`.container`, `.hero`,
  `.btn`, `.site-header`, ...) instead of inventing parallel systems.
- `src/styles/conventions.css` is platform-owned and regenerated per
  generation. Use its classes instead of hand-rolling equivalents:
  - Missing/placeholder images: a `<div class="ph">` block (optionally with an
    inner caption) — never an empty gray box or broken `<img>`.
  - Page-load entrance: `data-reveal-group` on a hero/section container
    staggers its direct children; single elements take `data-reveal`.
  - Focus rings and selection color come from it — keep them intact.
- Mobile-first: base styles target small screens; enhance inside
  `@media (min-width: 768px)`.

### JavaScript
- Vanilla JS only, and almost none is needed. The mobile-nav toggle lives in
  `Base.astro` as an `is:inline` script — keep its `aria-expanded` wiring
  intact. Add page-specific behavior the same way (`<script is:inline>`),
  never by linking external files.

## 4. Protected files (from the manifest)

`package.json`, `astro.config.mjs`

- Edit only when strictly necessary (for example, the user's feature genuinely
  requires a new npm dependency). Never rewrite them wholesale.
- Never change: the `scripts` in `package.json`; `build.format`,
  `build.inlineStylesheets`, or `outDir` in `astro.config.mjs`.

## 5. User uploads

- Files the user uploads land in `public/uploads/`. Reference them with
  relative paths: `<img src="./uploads/team-photo.jpg" alt="The team">`. This
  works in dev, in the built site, and in exports (files in `public/` are
  copied verbatim and pages are siblings, so relative paths stay valid).
- When the user has provided images, use them instead of placeholders.

## 6. Quality bar

- Semantic HTML5: `header`, `nav`, `main`, `section`, `footer`, headings in
  order, one `<h1>` per page. The layout already provides header/nav/footer —
  pages supply `<main>` content only.
- Responsive and mobile-first; sanity-check layouts at ~375px and ~1280px.
- Accessible: alt text on every image, visible focus states, sufficient color
  contrast, `aria-current`/`aria-expanded` kept in sync.
- Real content for the user's request — no lorem-ipsum walls, no `TODO`
  comments, no half-finished sections. Every page you create must be complete
  and reachable from the nav.
- Code must build cleanly with `npm run build`: valid `.astro` syntax, correct
  import paths, no unused leftover files.

## 7. Workflow

- Read existing files before editing them; match the patterns already there.
- Prefer targeted edits (`edit_file`) over rewriting whole files.
- The header/nav/footer exist exactly once (in `Base.astro`) — never copy them
  into pages, and never create a second layout without a strong reason.
- After structural changes, trace the chain: page file exists in `src/pages/`
  → entry in `navLinks` — both or it isn't done. Then `run_command('build')`.
