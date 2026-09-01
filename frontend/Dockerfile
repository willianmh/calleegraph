# syntax=docker/dockerfile:1

# --- build stage -----------------------------------------------------------
# Runs exactly the same command as `npm run build` on a developer machine,
# against the committed lockfile, so the image contains the same bundle a
# local build produces.
FROM node:22-alpine AS build
WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

COPY tsconfig.json vite.config.ts index.html ./
COPY src ./src

# `npm run build` = `tsc --noEmit && vite build` — a type error fails the image.
RUN npm run build

# --- runtime stage ---------------------------------------------------------
FROM nginx:1.27-alpine AS runtime

RUN rm -f /etc/nginx/conf.d/default.conf
COPY nginx.conf /etc/nginx/conf.d/calleegraph.conf
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 80

HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
  CMD wget --quiet --spider http://localhost/ || exit 1

CMD ["nginx", "-g", "daemon off;"]
