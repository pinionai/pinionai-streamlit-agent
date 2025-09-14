# PinionAI Agent - Cloud Run application utilizing Streamlit Framework

This application uses the [Streamlit](https://streamlit.io/) framework, Pinionai python library to serve Agents you author in PinionAI studio.

## About the application

To run the Streamlit Application locally (on cloud shell), we need to perform the following steps:

1. Setup the Python virtual environment and install the dependencies:

   In Cloud Shell, execute the following commands:

For a new venv:

```bash
uv venv pinionai-streamlit # 1. Create a new virtual environment with uv
source pinionai-streamlit/bin/activate # 2. Activate the venv

# 3. Compile your dependencies from pyproject.toml into a lockfile.
#    This reads requirements.in and creates/updates requirements.txt.
uv pip compile requirements.in -o requirements.txt

# 4. Install the locked dependencies into your venv.
uv pip sync requirements.txt
```

> [!TIP]
> uv is a modern, extremely fast Python package installer from the creators of ruff. If you don't have it, you can install it with pip install uv or by following the official installation guide. Using uv can significantly speed up environment creation and dependency installation.

\*Key for ADC locally.

```bash
   gcloud auth application-default login
```

2. Your application requires access to a few environment variables, see the .env.example file. Use this dotenv file as a template. Copy it to `.env` and fill in your actual credentials, and do not commit it to version control.

   - client_id = '<YOUR_CLIENT_ID_HERE>'
   - client_secret = '<YOUR_CLIENT_SECRET_HERE>'
   - agent_id = '<YOUR_AGENT_ID_HERE>'
   - host_url = '<YOUR_HOST_URL_HERE>'
   - WEBSOCKET_URL = '<YOUR_WEBSOCKET_URL_HERE>'

   `client_id` and `client_secret` are found within your PinionAI Studio application. You can generate a new client secret in the PinionAI Studio portal if desired. `agent_id `is the unique identifier of the AI agent you create in PinionAI Studio and want to serve. `host_url` is the location of PinionAI API server. `WEBSOCKET_URL` is to facilitate live agent chats, and will match the Pinion AI gRPC server address and port.

   **NOTE**: AI Agent LLM keys, GCP_PROJECT and many other variables are set within PinionAI Studio itself. You will need to configure these to run your agent.

3. To run the application locally, execute the following command:

```bash
   streamlit run chat.py
```

Or with limited seurity:

```bash
streamlit run chat.py \
   --browser.serverAddress=localhost \
   --server.enableCORS=false \
   --server.enableXsrfProtection=false \
   --server.port 8080
```

The application will startup and you will be provided a URL to the application.

## Build and Deploy the Application to Cloud Run

> Ensure that you have cloned this repository and you are currently in the `pinionai-streamlit-agent` folder. This should be your active working directory for the rest of the commands.

To deploy the Streamlit Application in [Cloud Run](https://cloud.google.com/run/docs/quickstarts/deploy-container), we need to perform the following steps:

1. Your Cloud Run app requires access to two environment variables:

   - `GCP_PROJECT` : This the Google Cloud project ID.
   - `GCP_REGION` : This is the region in which you are deploying your Cloud Run app. For e.g. us-central1.

   These variables are needed since the Vertex AI initialization needs the Google Cloud project ID and the region. The specific code line from the `chat.py`

   In Cloud Shell, execute the following commands:

   ```bash
   export GCP_PROJECT='<Your GCP Project Id>'  # Change this
   export GCP_REGION='us-central1'             # If you change this, make sure the region is supported.
   ```

2. Now you can build the Docker image for the application and push it to Artifact Registry. To do this, you will need one environment variable set that will point to the Artifact Registry name. Included in the script below is a command that will create this Artifact Registry repository for you.

   In Cloud Shell, execute the following commands:

   ```bash
   export AR_REPO='<REPLACE_WITH_YOUR_ArifactRegistry_REPO_NAME>'  # Change this or perhaps use pinionai
   export SERVICE_NAME='pinionai-streamlit-agent' # This is the name of our Application and Cloud Run service. Change it if you like.

   # make sure you are in the active directory
   gcloud artifacts repositories create "$AR_REPO" --location="$GCP_REGION" --repository-format=Docker
   gcloud auth configure-docker "$GCP_REGION-docker.pkg.dev"
   gcloud builds submit --tag "$GCP_REGION-docker.pkg.dev/$GCP_PROJECT/$AR_REPO/$SERVICE_NAME"
   ```

````

   You may also want to build and deploy manually, by performing the following:

   ```bash
   docker build --platform linux/amd64 --tag $GCP_REGION-docker.pkg.dev/$GCP_PROJECT/pinionai/run:v1 .

   docker push $GCP_REGION-docker.pkg.dev/$GCP_PROJECT/pinionai/run:v1
   ```

3. The final step is to deploy the service in Cloud Run with the image that we had built and had pushed to the Artifact Registry in the previous step:

   In Cloud Shell, execute the following command:

   ```bash
   gcloud run deploy "$SERVICE_NAME" \
     --port=8080 \
     --image="$GCP_REGION-docker.pkg.dev/$GCP_PROJECT/$AR_REPO/$SERVICE_NAME" \
     --allow-unauthenticated \
     --region=$GCP_REGION \
     --platform=managed  \
     --project=$GCP_PROJECT \
     --set-env-vars=client_id=$YOUR_CLIENT_ID_HERE,GCP_REGION=$YOUR_CLIENT_SECRET_HERE, etc...
   ```

You may also choose to deploy manually in Google Cloud Console.

On successful deployment, you will be provided a URL to the Cloud Run service. You can visit that in the browser to view the Cloud Run application that you just deployed.


## Installing pinionai

By default, the application will install `pinionai` from PyPI.
If you want to install the latest development version from GitHub, comment out the `pinionai` line in `requirements.in` (or `requirements.txt`) and uncomment the GitHub line.

````
