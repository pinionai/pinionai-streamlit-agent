---
title: Agent Deployment - Cloud Run
---

# Deploy AI Agent to Google Cloud Run

This guide provides step-by-step instructions on how to deploy the Pinion AI chat application to Google Cloud Run, including configuration of required environment variables using a `.env` file.

## Prerequisites

Before you begin, ensure you have the following installed and configured:

1.  **Google Cloud SDK (`gcloud` CLI):** Installation Guide
2.  **Docker:** Installation Guide
3.  A Google Cloud Project. If you don't have one, create one in the Google Cloud Console.

## Deployment Steps

### 1. Set Up Your Environment

First, log in to your Google Cloud account and set your project.

```bash
gcloud auth login
gcloud config set project YOUR_PROJECT_ID
```

Replace `YOUR_PROJECT_ID` with your actual Google Cloud project ID.

Next, define some environment variables to make the following commands easier to manage. Choose a region that supports Cloud Run.

```bash
export PROJECT_ID=$(gcloud config get-value project)
export REGION="us-central1" # Or your preferred region
export REPOSITORY="pinion-ai-chat-repo"
export IMAGE_NAME="pinion-ai-chat"
```

### 2. Configure Application Environment Variables

Create a `.env` file in your project root directory to store the environment variables required by your application (such as API keys, secrets, or configuration values). For example:

```env
# .env
client_id = "123456"
client_secret = "654321"
agent_id = '424242424242'
host_url = 'http://localhost:8080'
WEBSOCKET_URL = 'localhost:50051'
```

**Note:** Do not commit your `.env` file to version control if it contains sensitive information. Add `.env` to your `.gitignore`.

### 3. Enable Required APIs

You need to enable the Artifact Registry API (to store your Docker image) and the Cloud Run API (to run your service).

```bash
gcloud services enable artifactregistry.googleapis.com run.googleapis.com
```

### 4. Create an Artifact Registry Repository

Create a Docker repository in Artifact Registry to host your container image.

```bash
gcloud artifacts repositories create ${REPOSITORY} \
    --repository-format=docker \
    --location=${REGION} \
    --description="Docker repository for the PINION AI Chat application"
```

### 5. Configure Docker Authentication

Configure the Docker command-line tool to authenticate with Artifact Registry.

```bash
gcloud auth configure-docker ${REGION}-docker.pkg.dev
```

### 6. Build and Push the Docker Image

Build the Docker image from the `Dockerfile` in the project root, tag it, and push it to your Artifact Registry repository.

```bash
# Define the full image URI
export IMAGE_URI="${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPOSITORY}/${IMAGE_NAME}:latest"

# Build the Docker image from the project root
docker build -t ${IMAGE_URI} .

# Push the image to Artifact Registry
docker push ${IMAGE_URI}
```

### 7. Deploy to Google Cloud Run with Environment Variables

Deploy your container image to Cloud Run and pass the environment variables from your `.env` file. You can specify each variable using the `--set-env-vars` flag, or use the `--env-vars-file` flag with a YAML file.

**Option 1: Using `--set-env-vars`**

Extract the variables from your `.env` file and pass them as a comma-separated list:

```bash
gcloud run deploy ${IMAGE_NAME} \
    --image=${IMAGE_URI} \
    --port=8080 \
    --region=${REGION} \
    --platform=managed \
    --allow-unauthenticated \
    --set-env-vars client_id=123456,client_secret=654321,etc
```

**Option 2: Using an Environment Variables YAML File**

Convert your `.env` file to a YAML file (e.g., `env.yaml`):

```yaml
client_id: 123456
client_secret: 654321
agent_id: 424242424242
host_url: http://localhost:8080
WEBSOCKET_URL: localhost:50051
```

Then deploy with:

```bash
gcloud run deploy ${IMAGE_NAME} \
    --image=${IMAGE_URI} \
    --port=8080 \
    --region=${REGION} \
    --platform=managed \
    --allow-unauthenticated \
    --env-vars-file env.yaml
```

During the deployment process, `gcloud` will prompt you to confirm the settings. Once you confirm, it will deploy the service and provide you with a **Service URL**.

### 8. Access Your Application

Once the deployment is complete, you can access your Streamlit application by navigating to the **Service URL** provided in the command-line output.
