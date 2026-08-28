<script setup>
import SiteHeader from './components/SiteHeader.vue'
import SiteFooter from './components/SiteFooter.vue'
</script>

<template>
  <div class="flex min-h-screen flex-col bg-bg font-body text-text">
    <SiteHeader />
    <main class="flex-1">
      <router-view />
    </main>
    <SiteFooter />
  </div>
</template>
