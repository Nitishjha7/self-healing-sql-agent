# Single-service image: FastAPI serves both the API and the built React app.
#
# Why one container instead of two: Render's free tier gives one always-on-ish
# web service, and a split deployment would need CORS, a second deploy, and a
# second thing to keep warm. Serving the SPA from the same origin removes all
# three. `backend/Dockerfile` still exists for local docker-compose, where nginx
# serves the frontend separately.
#
# Build context is the repo root:  docker build -f Dockerfile .

# ---- stage 1: build the React app ----
FROM node:20-alpine AS frontend

WORKDIR /fe

COPY frontend/package.json frontend/package-lock.json* ./
RUN npm install

COPY frontend/ ./
# Empty API base => the SPA calls /api on its own origin, which is this same
# service. No CORS, no build-time backend URL to keep in sync.
ENV VITE_API_BASE=""
RUN npm run build

# ---- stage 2: python app + static files ----
FROM python:3.11-slim

WORKDIR /app

COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/app ./app
COPY --from=frontend /fe/dist ./static

EXPOSE 8000

# Render (and most PaaS) inject the port to bind as $PORT. Shell form so it
# expands; the default keeps `docker run` working locally.
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
