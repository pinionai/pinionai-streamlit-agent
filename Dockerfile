# syntax=docker/dockerfile:1

# Use a slim Python image as the base
FROM python:3.13-slim as base

# Set environment variables to prevent writing .pyc files and to buffer output
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

# Install uv using a dedicated layer to improve caching.
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install uv

# Set the PATH to include uv's binary location
ENV PATH="/root/.local/bin:$PATH"

WORKDIR /app

# Create a virtual environment using uv. This is a good practice for isolation.
RUN uv venv

# Activate the virtual environment for subsequent RUN commands.
ENV VIRTUAL_ENV=/app/.venv
ENV PATH="$VIRTUAL_ENV/bin:$PATH"

# Copy dependency definitions to leverage Docker's layer caching.
COPY pyproject.toml requirements.txt ./

# Install dependencies using the locked requirements.txt file.
# Using `sync` is faster and ensures the environment exactly matches the lockfile.
RUN --mount=type=cache,target=/root/.cache/uv \
    uv pip sync --no-cache requirements.txt

# Copy the rest of the application code into the container
COPY . .

# Expose the port that Streamlit will run on
EXPOSE 8080

# The command to run the application when the container starts.
CMD ["streamlit", "run", "chat.py", "--server.port=8080", "--server.address=0.0.0.0"]
