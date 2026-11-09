FROM node:22-bookworm-slim AS build
WORKDIR /opt/verifex
ARG API_ORIGIN=http://api:8000
ENV API_ORIGIN=$API_ORIGIN NEXT_TELEMETRY_DISABLED=1
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM node:22-bookworm-slim
WORKDIR /opt/verifex
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1 API_ORIGIN=http://api:8000
COPY --from=build --chown=node:node /opt/verifex/ ./
USER node
EXPOSE 3000
CMD ["npm", "start", "--", "--hostname", "0.0.0.0"]
