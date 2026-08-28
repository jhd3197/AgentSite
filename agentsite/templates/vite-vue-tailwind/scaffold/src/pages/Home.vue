<script setup>
import { RouterLink } from 'vue-router'

const features = [
  {
    title: 'Routed pages',
    description:
      'Add a file in src/pages and a route in src/router.js — the hash router handles the rest.',
  },
  {
    title: 'Design tokens',
    description:
      'Colors, fonts, and radii live in src/styles/tokens.css and flow into every Tailwind utility.',
  },
  {
    title: 'Component-driven',
    description:
      'Shared UI like the header and footer lives in src/components, ready to extend.',
  },
]
</script>

<template>
  <section class="bg-surface">
    <div class="mx-auto max-w-6xl px-6 py-20 text-center">
      <h1 class="font-heading text-4xl font-bold text-text md:text-5xl">
        Your new site starts here
      </h1>
      <p class="mx-auto mt-4 max-w-xl text-lg text-text-secondary">
        This is the starter scaffold. Replace this hero with real content for
        your project.
      </p>
      <div class="mt-8 flex justify-center">
        <RouterLink
          to="/"
          class="rounded-lg bg-primary px-6 py-3 font-medium text-white shadow-sm transition-colors hover:bg-secondary"
        >
          Get started
        </RouterLink>
      </div>
    </div>
  </section>

  <section class="mx-auto max-w-6xl px-6 py-16">
    <h2 class="text-center font-heading text-2xl font-bold text-text">
      How this template works
    </h2>
    <div class="mt-10 grid gap-6 md:grid-cols-3">
      <div
        v-for="feature in features"
        :key="feature.title"
        class="rounded-lg border border-border bg-bg p-6 shadow-sm"
      >
        <h3 class="font-heading text-lg font-bold text-primary">
          {{ feature.title }}
        </h3>
        <p class="mt-2 text-sm text-text-secondary">
          {{ feature.description }}
        </p>
      </div>
    </div>
  </section>
</template>
