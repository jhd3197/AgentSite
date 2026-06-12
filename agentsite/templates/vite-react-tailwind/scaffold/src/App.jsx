import { HashRouter, Routes, Route } from 'react-router-dom'
import SiteHeader from './components/SiteHeader.jsx'
import SiteFooter from './components/SiteFooter.jsx'
import Home from './pages/Home.jsx'

// HashRouter is required: the built app is served from a subpath and from
// exported zips, where BrowserRouter route URLs would 404. Never switch it.
export default function App() {
  return (
    <HashRouter>
      <div className="flex min-h-screen flex-col bg-bg font-body text-text">
        <SiteHeader />
        <main className="flex-1">
          <Routes>
            <Route path="/" element={<Home />} />
          </Routes>
        </main>
        <SiteFooter />
      </div>
    </HashRouter>
  )
}
