import { useState } from 'react'
import { Link } from 'react-router-dom'

// Every routed page gets an entry here (see TEMPLATE.md: adding a page).
const navLinks = [{ to: '/', label: 'Home' }]

export default function SiteHeader() {
  const [menuOpen, setMenuOpen] = useState(false)

  return (
    <header className="sticky top-0 z-10 border-b border-border bg-bg">
      <div className="mx-auto flex max-w-6xl items-center justify-between px-6 py-4">
        <Link
          to="/"
          className="font-heading text-lg font-bold text-text transition-colors hover:text-primary"
          onClick={() => setMenuOpen(false)}
        >
          AgentSite Project
        </Link>

        <button
          type="button"
          className="rounded-sm border border-border p-2 md:hidden"
          aria-expanded={menuOpen}
          aria-controls="site-nav"
          onClick={() => setMenuOpen((open) => !open)}
        >
          <span className="sr-only">Toggle navigation</span>
          <span aria-hidden="true" className="block h-0.5 w-5 rounded-full bg-text" />
          <span aria-hidden="true" className="mt-1 block h-0.5 w-5 rounded-full bg-text" />
          <span aria-hidden="true" className="mt-1 block h-0.5 w-5 rounded-full bg-text" />
        </button>

        <nav
          id="site-nav"
          aria-label="Main navigation"
          className={`${menuOpen ? 'block' : 'hidden'} absolute left-0 top-full w-full border-b border-border bg-bg px-6 pb-4 shadow-sm md:static md:block md:w-auto md:border-0 md:p-0 md:shadow-none`}
        >
          <ul className="flex flex-col gap-1 md:flex-row md:items-center md:gap-2">
            {navLinks.map((link) => (
              <li key={link.to}>
                <Link
                  to={link.to}
                  className="block rounded-sm px-3 py-2 font-medium text-text-secondary transition-colors hover:bg-surface hover:text-text"
                  onClick={() => setMenuOpen(false)}
                >
                  {link.label}
                </Link>
              </li>
            ))}
          </ul>
        </nav>
      </div>
    </header>
  )
}
