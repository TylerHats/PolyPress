# Use an official lightweight Python runtime based on Alpine
FROM python:3.14-alpine

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PORT=8000
ENV PYTHONPATH=/app/backend

# Set the working directory in the container
WORKDIR /app

# Install system dependencies (like Git, which PolyPress uses for self-updating and version tracking)
RUN apk add --no-cache git

# Copy requirements and install dependencies
COPY backend/requirements.txt /app/backend/requirements.txt
RUN pip install --no-cache-dir -r /app/backend/requirements.txt

# Copy the rest of the application code
COPY . /app

# Expose port 8000
EXPOSE 8000

# Define persistent storage locations
VOLUME ["/app/data", "/app/backups", "/app/certs", "/app/branding"]

# Start Uvicorn when the container starts
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
