import { Link } from 'react-router-dom'

const features = [
  {
    title: 'Routed pages',
    description:
      'Add a file in src/pages and a Route in App.jsx — the hash router handles the rest.',
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

export default function Home() {
  return (
    <>
      <section className="bg-surface">
        <div className="mx-auto max-w-6xl px-6 py-20 text-center">
          <h1 className="font-heading text-4xl font-bold text-text md:text-5xl">
            Your new site starts here
          </h1>
          <p className="mx-auto mt-4 max-w-xl text-lg text-text-secondary">
            This is the starter scaffold. Replace this hero with real content for
            your project.
          </p>
          <div className="mt-8 flex justify-center">
            <Link
              to="/"
              className="rounded-lg bg-primary px-6 py-3 font-medium text-white shadow-sm transition-colors hover:bg-secondary"
            >
              Get started
            </Link>
          </div>
        </div>
      </section>

      <section className="mx-auto max-w-6xl px-6 py-16">
        <h2 className="text-center font-heading text-2xl font-bold text-text">
          How this template works
        </h2>
        <div className="mt-10 grid gap-6 md:grid-cols-3">
          {features.map((feature) => (
            <div
              key={feature.title}
              className="rounded-lg border border-border bg-bg p-6 shadow-sm"
            >
              <h3 className="font-heading text-lg font-bold text-primary">
                {feature.title}
              </h3>
              <p className="mt-2 text-sm text-text-secondary">
                {feature.description}
              </p>
            </div>
          ))}
        </div>
      </section>
    </>
  )
}
