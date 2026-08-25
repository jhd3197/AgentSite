import { Lightning, ShieldCheck, Eye } from "@phosphor-icons/react";

export const PROVIDERS = [
  {
    id: "vercel",
    name: "Vercel",
    desc: "Edge network, instant rollbacks",
    color: "from-white to-slate-200 text-slate-900",
    accent: "border-white/20",
  },
  {
    id: "netlify",
    name: "Netlify",
    desc: "Atomic deploys, deploy previews",
    color: "from-teal-400 to-cyan-500 text-slate-950",
    accent: "border-teal-400/30",
  },
  {
    id: "cloudflare",
    name: "Cloudflare Pages",
    desc: "Free unlimited bandwidth",
    color: "from-orange-400 to-amber-500 text-slate-950",
    accent: "border-orange-400/30",
  },
  {
    id: "github",
    name: "GitHub Pages",
    desc: "Static hosting on your repo",
    color: "from-slate-700 to-slate-900 text-white",
    accent: "border-slate-500/30",
  },
];

export const ENVS = [
  { id: "production", label: "Production", icon: Lightning },
  { id: "staging", label: "Staging", icon: ShieldCheck },
  { id: "preview", label: "Preview", icon: Eye },
];

export const DEPLOY_STAGES = [
  { id: "queue", label: "Queued", duration: 400 },
  { id: "build", label: "Building", duration: 2400 },
  { id: "upload", label: "Uploading assets", duration: 1600 },
  { id: "deploy", label: "Deploying to edge", duration: 1400 },
  { id: "live", label: "Live", duration: 0 },
];

export const DEFAULT_CFG = {
  provider: null,
  branch: "main",
  auto_deploy: true,
  build_command: "agentsite build",
  output_dir: "dist",
};
