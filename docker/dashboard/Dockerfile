FROM node:20-alpine AS builder

WORKDIR /build
RUN corepack enable
COPY paperguide-dashboard/package.json paperguide-dashboard/pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile
COPY paperguide-dashboard/ ./

ARG VITE_PAPERGUIDE_API_BASE_URL=http://localhost
ENV VITE_PAPERGUIDE_API_BASE_URL=$VITE_PAPERGUIDE_API_BASE_URL
RUN pnpm run build

FROM nginx:1.27-alpine AS runtime

COPY docker/dashboard/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=builder /build/dist /usr/share/nginx/html

EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
