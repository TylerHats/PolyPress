# Use an official lightweight Python runtime based on Alpine
FROM python:3.14-alpine

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PORT=8000
ENV PYTHONPATH=/app/backend
ENV POLYPRESS_DOCKER=1
ENV FORWARDED_ALLOW_IPS="127.0.0.1,::1,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16"

ARG POLYPRESS_VERSION=""
ARG POLYPRESS_COMMIT=""
ENV POLYPRESS_VERSION=${POLYPRESS_VERSION}
ENV POLYPRESS_COMMIT=${POLYPRESS_COMMIT}

# Set the working directory in the container
WORKDIR /app

# Upgrade system packages and install dependencies (like Git, which PolyPress uses for self-updating and version tracking)
RUN apk update && \
    apk upgrade --no-cache && \
    apk add --no-cache git && \
    (apk add --no-cache --repository=https://dl-cdn.alpinelinux.org/alpine/edge/main 'nghttp2-libs>=1.70.0-r0' || true)

# Copy requirements, upgrade pip, and install dependencies
COPY backend/requirements.txt /app/backend/requirements.txt
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r /app/backend/requirements.txt

# Copy the rest of the application code
COPY . /app

# Expose port 8000
EXPOSE 8000

# Define persistent storage locations
VOLUME ["/app/data", "/app/backups", "/app/certs", "/app/branding"]

# Start Uvicorn when the container starts (respects FORWARDED_ALLOW_IPS env var safely)
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log", "--proxy-headers"]
