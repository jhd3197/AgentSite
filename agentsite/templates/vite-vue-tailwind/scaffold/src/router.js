import { createRouter, createWebHashHistory } from 'vue-router'
import Home from './pages/Home.vue'

// Hash history is required: the built app is served from a subpath and from
// exported zips, where history-mode route URLs would 404. Never switch it.
// Every routed page gets an entry here (see TEMPLATE.md: adding a page).
const routes = [{ path: '/', name: 'home', component: Home }]

export default createRouter({
  history: createWebHashHistory(),
  routes,
})
