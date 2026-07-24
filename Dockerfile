FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Set environment variables to prevent Python from writing .pyc files
# and to ensure stdout is logged immediately
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Install system dependencies
RUN apt-get update \
    && apt-get install -y --no-install-recommends gcc libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements file first to leverage Docker cache
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the backend codebase
COPY src/ /app/src/
COPY demo.py /app/

# Expose port 8000 for FastAPI
EXPOSE 8000

# Run the FastAPI server via Uvicorn
CMD ["uvicorn", "src.api.server:app", "--host", "0.0.0.0", "--port", "8000"]
