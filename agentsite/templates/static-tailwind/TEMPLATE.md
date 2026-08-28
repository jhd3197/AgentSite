# Static + Tailwind (CDN) — Template Contract

Read this file before writing any code. It defines how this project is structured.
Follow it exactly so the preview, exports, and future edits keep working.

## 1. Stack & how it runs

- Plain HTML + Tailwind CSS 4 (browser CDN build) + vanilla JavaScript.
  No build step, no framework, no npm.
- Files are served directly from the project root. `index.html` is the entry
  page; every other page is simply another `.html` file next to it.
- A change is live the moment the file is saved — there is nothing to compile.
- Tailwind is loaded from a CDN script and compiles the utilities each page
  uses at load time in the browser. **Viewing the site requires internet
  access** (the CDN and Google Fonts). Never swap the CDN for an npm setup —
  this template is deliberately buildless.

## 2. Directory layout

| Path                | Purpose                                                                  |
| ------------------- | ------------------------------------------------------------------------ |
| `*.html` (root)     | One file per page: `index.html`, `about.html`, `contact.html`, ...        |
| `styles/tokens.css` | Design tokens (CSS custom properties). The Designer agent owns this file. |
| `styles/conventions.css` | AgentSite house system (platform-owned): `.ph` image-placeholder blocks, `[data-reveal]`/`[data-reveal-group]` load choreography, focus rings. Use its classes; never edit it. |
| `styles/main.css`   | The few styles utilities can't express: JS-toggled nav state hooks.      |
| `scripts/main.js`   | Sitewide JS: mobile nav toggle + current-page nav highlighting.           |
| `scripts/*.js`      | Additional page-specific scripts if needed (vanilla JS only).             |
| `uploads/`          | User-uploaded files. Never delete, rename, or overwrite anything here.    |
| `assets/`           | Images, icons, and other static files you add yourself.                   |

## 3. Conventions

### Pages
- Every page is a root-level `*.html` file, lowercase and hyphenated
  (`our-work.html`).
- Every page MUST share the exact same `<head>` tail and `<header>`/`<footer>`
  markup. When creating a page, copy `index.html` and change only the `<title>`,
  meta description, and `<main>` content. Update shared blocks in lockstep
  everywhere if they ever change.
- Every page's `<head>` includes, in this order (copy verbatim):
  1. the Tailwind browser CDN script
     (`https://cdn.jsdelivr.net/npm/@tailwindcss/browser@4`),
  2. the `<style type="text/tailwindcss">@theme inline { ... }</style>` block
     that maps tokens onto utilities,
  3. `styles/tokens.css`, then `styles/main.css`, then `styles/conventions.css`,
  4. `<script src="scripts/main.js" defer></script>`.
- Adding or removing a page means updating the nav `<ul>` on ALL pages, not
  just one.

### Styling
- Style with Tailwind utility classes that reference the theme tokens:
  `bg-primary`, `hover:bg-secondary`, `text-text`, `text-text-secondary`,
  `bg-surface`, `bg-bg`, `border-border`, `bg-accent`, `font-heading`,
  `font-body`, `rounded-sm`, `rounded-lg`, and so on. These exist because the
  inline `@theme inline` block maps them to `styles/tokens.css` variables.
- `styles/tokens.css` is the single source of design truth — colors, fonts,
  sizes, spacing, radii, shadows. The Designer agent rewrites it; do not fight
  its values. Because utilities read the tokens at runtime, a Designer token
  update restyles the whole site with zero markup changes.
- Never hardcode hex values in HTML or CSS, and never use arbitrary-value
  utilities (`bg-[#1f2937]`) — if a needed token is missing, append it to
  `styles/tokens.css` AND to the `@theme inline` mapping in every page's head.
- `styles/conventions.css` is platform-owned and regenerated per generation.
  Use its classes instead of hand-rolling equivalents:
  - Missing/placeholder images: a `<div class="ph">` block (optionally with an
    inner caption) — never an empty gray box or broken `<img>`.
  - Page-load entrance: `data-reveal-group` on a hero/section container
    staggers its direct children; single elements take `data-reveal`.
  - Focus rings and selection color come from it — keep them intact.
- `styles/main.css` holds ONLY the JS-toggled nav states (`.site-nav.is-open`,
  `.site-nav__link.is-active`). These are unlayered so they beat Tailwind's
  layered utilities — do not move them into utilities, and do not add anything
  Tailwind already provides.
- Mobile-first: base utilities target small screens; enhance with `md:`
  (768px) variants.

### JavaScript
- Vanilla JS only. No frameworks or additional CDN libraries unless the user
  explicitly asks.
- `scripts/main.js` highlights the current page's nav link (adds `.is-active`)
  by matching link `href`s to the URL — keep nav hrefs as plain filenames
  (`about.html`) and keep the `site-nav`, `site-nav__link`, `nav-toggle`
  classes in the markup so the script keeps working.
- Keep the `aria-expanded` wiring on the nav toggle intact when editing the
  header.

## 4. Protected files

- This template locks no files, but treat `styles/tokens.css` as
  Designer-owned: read it and reference it; only append a token when a needed
  one truly doesn't exist (and mirror it into the `@theme inline` block on
  every page).

## 5. User uploads

- Files the user uploads land in `uploads/`. Reference them with relative
  paths: `<img src="uploads/team-photo.jpg" alt="The team outside the studio">`.
- When the user has provided images, use them instead of placeholders.

## 6. Quality bar

- Semantic HTML5: `header`, `nav`, `main`, `section`, `footer`, headings in
  order, one `<h1>` per page.
- Responsive and mobile-first; sanity-check layouts at ~375px and ~1280px.
- Accessible: alt text on every image, visible focus states, sufficient color
  contrast, `aria-expanded` kept in sync on the nav toggle.
- Real content for the user's request — no lorem-ipsum walls, no `TODO`
  comments, no half-finished sections. Every page you create must be complete
  and reachable from the nav.

## 7. Workflow

- Read existing files before editing them; match the patterns already there.
- Prefer targeted edits (`edit_file`) over rewriting whole files.
- When you change shared markup (`<head>` tail, header/nav/footer), apply the
  same change to every page in the same task so the site never drifts out of
  sync.
