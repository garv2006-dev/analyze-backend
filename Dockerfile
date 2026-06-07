FROM python:3.12-slim

# Set working directory to app project root
WORKDIR /app

# Configure python environment flags
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1
ENV PYTHONPATH=/app

# Install curl and standard system tools
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy backend requirements list
COPY requirements.txt /app/backend/

# Install python modules
RUN pip install --no-cache-dir -r /app/backend/requirements.txt

# Download Playwright Chromium binaries and install system-level graphics/font dependencies
RUN playwright install --with-deps chromium

# Copy the entire backend workspace
COPY . /app/backend

# Expose server port
EXPOSE 5000

# Start Uvicorn pointing to main module from root working directory
CMD ["uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "5000"]
