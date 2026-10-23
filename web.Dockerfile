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

FROM node:22-alpine AS widget
WORKDIR /widget
COPY b24app/widget/package.json b24app/widget/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY b24app/widget ./
RUN npx vue-tsc --noEmit && npx vite build --outDir /widget-dist

FROM nginx:1.27-alpine
COPY infra/docker/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /web/dist /usr/share/nginx/html
COPY --from=widget /widget-dist /usr/share/nginx/html/b24app/widget
