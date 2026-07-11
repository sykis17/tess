FROM node:20-alpine AS build

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

COPY . .

ARG VITE_WS_BASE_URL
ENV VITE_WS_BASE_URL=${VITE_WS_BASE_URL}

RUN npm run build

FROM alpine:3.20

COPY --from=build /app/dist /dist

# Static assets only; Caddy mounts frontend/dist from a host volume in production.
