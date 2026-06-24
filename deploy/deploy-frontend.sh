#!/usr/bin/env bash
# Build and deploy the Loko ERP frontend to Cloudflare Pages.
# Usage:  ./deploy/deploy-frontend.sh
# Prereqs: npm, and a Cloudflare API token (CLOUDFLARE_API_TOKEN) with
#          "Cloudflare Pages: Edit" permission (or run `npx wrangler login`).
set -euo pipefail

PROJECT="loko-erp"          # Cloudflare Pages project name
cd "$(dirname "$0")/../frontend"

echo "▸ Installing deps…"
npm ci

echo "▸ Building production bundle (uses .env.production → VITE_API_BASE_URL)…"
npm run build

echo "▸ Deploying dist/ to Cloudflare Pages project '$PROJECT'…"
npx wrangler pages deploy dist --project-name "$PROJECT" --commit-dirty=true

echo "✅ Done. Production URL: https://$PROJECT.pages.dev (and your custom domain)."
