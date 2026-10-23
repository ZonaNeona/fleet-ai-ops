# Frontend: tsc + esbuild bundle, served by nginx that also proxies /api to the API container.
FROM node:22-alpine AS build
WORKDIR /web
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY tsconfig.json index.html vite.config.ts ./
COPY scripts/bundle.mjs scripts/prebundle.mjs scripts/
COPY docs docs
COPY public public
COPY web web
COPY n8n n8n
RUN npm run build

FROM nginx:1.27-alpine
COPY infra/docker/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /web/dist /usr/share/nginx/html
