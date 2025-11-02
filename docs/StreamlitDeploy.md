---
title: Agent Production Deployment - Streamlit Community Cloud
---

# Deploy AI Agent to Streamlit Community Cloud

This guide provides step-by-step instructions on how to deploy the Pinion AI chat application to Streamlit Community Cloud, including configuration of required environment variables using a `.env` file, or `env.yaml`.

## Why Streamlit Community Cloud:

Streamlit Community Cloud is a free, web-based platform for building and sharing data apps created with the Streamlit framework. It allows users to easily deploy their apps from GitHub repositories and share them with a public or private audience with minimal configuration. The platform handles containerization and provides a simple interface for managing apps, and it can be integrated with tools like GitHub Codespaces for browser-based development.

**Key Features**

- **Free deployment**: It is a free service for sharing Streamlit apps, with a free resource limit of 1GB.
- **Fast deployment**: Apps can be deployed in minutes with just a few clicks by connecting a GitHub repository.
- **App sharing**: Users can share their apps publicly with the world or with specific individuals through private sharing.
- **GitHub integration**: It connects to GitHub repositories for version control and deployment.
- **App management**: It provides a dashboard for managing apps, accessing logs, and updating them.
- **Browser-based development**: It integrates with GitHub Codespaces to allow users to write and edit code directly in their browser.

## Deployment Process: 

This is the most straightforward method for quick deployments, especially for demos or applications without strict enterprise requirements.

1. **Copy PinionAI Agent Github**: Copy [Example PinionAI Agent Github](https://github.com/pinionai/pinionai-streamlit-agent): A Streamlit PinionAI Github project, ready for use with PinionAI Studio and Streamlit Cloud.
2. **Your Public GitHub**: Host your Streamlit app files (including chat.py and requirements.txt) in a public GitHub repository.
3. **Sign Up for Streamlit Community Cloud**: Using your GitHub account, Sign up for [Streamlit Community Cloud](https://streamlit.io/cloud)
4. **Connect Repository** Connect your GitHub repository and specify the main app file (e.g.,chat.py).

- Fill out form
- Click `Advanced` and Configure any necessary environment variables in TOML format.

```bash
client_id = "<YOUR_CLIENT_ID_HERE>"
client_secret = "<YOUR_CLIENT_SECRET_HERE>"
agent_id = "<YOUR_AGENT_ID_HERE>"
host_url = "https://microservice-72loomfx5q-uc.a.run.app"
'''
```

5. Deploy the app.

- **Advantages**: Free, easy to set up, good for sharing and testing.
- **Disadvantages:** Limited control over infrastructure, not ideal for highly sensitive data or strict compliance needs.

## Service Account Permissions:

#### Gemini/Vertex AI Connectors (for non-GCP hosted agents)

    To allow PinionAI agents to use Gemini/Vertex AI when not hosted in GCP, you must add a service account with the appropriate permissions to the Agent configuration in Pinion AI (Connectors Tab). A service account is a special type of Google account intended to represent a non-human user (like an application) that needs to authenticate and be authorized to access data in Google APIs. Configure connectors with the following special grant types:

        **For Google Gemini/Vertex AI Access (non-GCP hosted):**
        *   `connector_grant_type`: Set this to `gcs_service_account`.
        *   `connector_client_id`: Can be left blank or used for the GCP Project ID.
        *   `connector_client_secret`: Paste the **entire JSON content** of your GCP service account key file here.

        **Note on GCP Permissions:** Ensure that the service account associated with the provided key has the necessary permissions you desire. Use Gemini/Vertex AI User (`roles/aiplatform.user`) for example.

#### Steps to Create a Google Service Account and Download Key File

1. Go to the [Google Cloud Console](https://console.cloud.google.com/).
2. Select your project or create a new one.
3. Navigate to "IAM & Admin" > "Service Accounts".
4. Click "Create Service Account".
5. Fill in the service account details and click "Create".
6. Grant the service account the necessary roles (e.g., Vertex AI User).
7. Click "Done" to finish creating the service account.
8. Find your service account in the list and click on it.
9. Go to the "Keys" tab and click "Add Key" > "JSON".
10. A JSON key file will be downloaded to your computer. This file contains the credentials needed to authenticate as the service account.
11. Use the contents of this file in the `Client Secret` field of your connector in Pinion AI and save, and select the connector in your desired Agent

## iframe Embedding with Streamlit Community Cloud

Streamlit Community Cloud supports embedding public apps using the subdomain scheme. To embed a public app, add the query parameter /?embed=true to the end of your \*.streamlit.app URL.

For example, say you want to embed the PinionAI app. The URL to include in your iframe is: `https://youragent.streamlit.app/?embed=true`

```bash
<iframe
  src="https://youragent.streamlit.app?embed=true"
  style="height: 450px; width: 100%;"
></iframe>
```
