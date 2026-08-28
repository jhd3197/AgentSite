<script setup>
import { ref } from 'vue'
import { RouterLink } from 'vue-router'

// Every routed page gets an entry here (see TEMPLATE.md: adding a page).
const navLinks = [{ to: '/', label: 'Home' }]

const menuOpen = ref(false)
</script>

<template>
  <header class="sticky top-0 z-10 border-b border-border bg-bg">
    <div class="mx-auto flex max-w-6xl items-center justify-between px-6 py-4">
      <RouterLink
        to="/"
        class="font-heading text-lg font-bold text-text transition-colors hover:text-primary"
        @click="menuOpen = false"
      >
        AgentSite Project
      </RouterLink>

      <button
        type="button"
        class="rounded-sm border border-border p-2 md:hidden"
        :aria-expanded="menuOpen"
        aria-controls="site-nav"
        @click="menuOpen = !menuOpen"
      >
        <span class="sr-only">Toggle navigation</span>
        <span aria-hidden="true" class="block h-0.5 w-5 rounded-full bg-text" />
        <span aria-hidden="true" class="mt-1 block h-0.5 w-5 rounded-full bg-text" />
        <span aria-hidden="true" class="mt-1 block h-0.5 w-5 rounded-full bg-text" />
      </button>

      <nav
        id="site-nav"
        aria-label="Main navigation"
        :class="[
          menuOpen ? 'block' : 'hidden',
          'absolute left-0 top-full w-full border-b border-border bg-bg px-6 pb-4 shadow-sm md:static md:block md:w-auto md:border-0 md:p-0 md:shadow-none',
        ]"
      >
        <ul class="flex flex-col gap-1 md:flex-row md:items-center md:gap-2">
          <li v-for="link in navLinks" :key="link.to">
            <RouterLink
              :to="link.to"
              class="block rounded-sm px-3 py-2 font-medium text-text-secondary transition-colors hover:bg-surface hover:text-text"
              @click="menuOpen = false"
            >
              {{ link.label }}
            </RouterLink>
          </li>
        </ul>
      </nav>
    </div>
  </header>
</template>
