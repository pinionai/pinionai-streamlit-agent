# syntax=docker/dockerfile:1

### 1. Build Stage ###
# Use a slim Python image as the builder
FROM python:3.13-slim as builder

# Set environment variables to prevent writing .pyc files and to buffer output
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

# Install uv, our package manager
RUN pip install --no-cache-dir uv

# Set the PATH to include uv's binary location
ENV PATH="/root/.local/bin:$PATH"

WORKDIR /app

# Create and activate a virtual environment
RUN uv venv
ENV VIRTUAL_ENV=/app/.venv
ENV PATH="$VIRTUAL_ENV/bin:$PATH"

# Copy dependency definitions to leverage Docker's layer caching.
COPY pyproject.toml requirements.txt ./

# Install dependencies using uv. `install` is used for requirements files.
RUN uv pip install --no-cache -r requirements.txt

### 2. Final Stage ###
FROM python:3.13-slim as final

# Set same environment variables
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

# Create a non-root user and group
RUN addgroup --system --gid 999 appgroup && \
    adduser --system --uid 999 --ingroup appgroup appuser

WORKDIR /app

# Copy the virtual environment from the builder stage
COPY --from=builder /app/.venv ./.venv

# Activate the virtual environment
ENV VIRTUAL_ENV=/app/.venv
ENV PATH="$VIRTUAL_ENV/bin:$PATH"

# Copy application code as the non-root user
COPY . .

RUN chown -R appuser:appgroup /app

# Set HOME to a writable directory for the non-root user.
ENV HOME=/tmp
RUN mkdir -p /tmp && chown 999:999 /tmp

# Switch to the non-root user
USER appuser

# Expose the port that Streamlit will run on
EXPOSE 8080

# Run the Streamlit application
CMD ["streamlit", "run", "chat.py", "--server.port=8080", "--server.address=0.0.0.0", "--server.headless=true"]
