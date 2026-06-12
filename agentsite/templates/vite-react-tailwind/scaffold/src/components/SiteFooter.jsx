export default function SiteFooter() {
  return (
    <footer className="border-t border-border bg-surface">
      <div className="mx-auto flex max-w-6xl flex-col items-center justify-between gap-2 px-6 py-8 text-sm text-text-secondary md:flex-row">
        <p>&copy; 2026 AgentSite Project. All rights reserved.</p>
        <p>
          Built with <span className="font-medium text-text">AgentSite</span>
        </p>
      </div>
    </footer>
  )
}
