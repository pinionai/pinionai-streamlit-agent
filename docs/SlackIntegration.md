# Slack Integration Guide - PinionAI Agent Runner

This guide provides step-by-step instructions for setting up a Slack application, configuring the PinionAI Slack bot (`chat_slack.py`), and deploying it to various environments.

## Table of Contents

1. [Slack App Configuration](#1-slack-app-configuration)
2. [Environment Setup](#2-environment-setup)
3. [Local Deployment](#3-local-deployment)
4. [Cloud Deployment (Google Cloud Run)](#4-cloud-deployment-google-cloud-run)
5. [Usage Guide](#5-usage-guide)
6. [Troubleshooting](#6-troubleshooting)

---

## 1. Slack App Configuration

To use the Slack integration, you must first create and configure a Slack App in the [Slack API Dashboard](https://api.slack.com/apps).

### A. Create the App

1. Click **Create New App** > **From scratch**.
2. Name your app (e.g., "PinionAI Bot") and select your workspace.

### B. Enable Socket Mode

1. In the left sidebar, go to **Settings > Socket Mode**.
2. Toggle **Enable Socket Mode** to **On**.
3. You will be prompted to generate an **App-level token**.
   - **Token Name:** `socket_token`
   - **Scope:** `connections:write`
4. **Copy this token** (starts with `xapp-`). This is your environment variable: `SLACK_APP_TOKEN`.
5. **Interactivity & Shortcuts** set to `Yes`
6. **Slash Commands** set to `Yes` (See F. below)
7. **Enable Events** set to `Yes` (See D. below)

### C. Configure Bot Scopes

1. Go to **Features > OAuth & Permissions**.
2. Scroll down to **Scopes > Bot Token Scopes** and add:
   - `chat:write` (Allows the bot to send messages)
   - `files:read` (Allows the bot to process uploaded .aia files)
   - `im:history` (Allows the bot to see messages in DMs)
   - `channels:history` (Allows the bot to see messages in public channels)
   - `groups:history` (Allows the bot to see messages in private channels)
3. Scroll up and click **Install to Workspace**.
4. **Copy the Bot User OAuth Token** (starts with `xoxb-`). This is your environment variable: `SLACK_BOT_TOKEN`.

### D. Enable Events

1. Go to **Features > Event Subscriptions**.
2. Toggle **Enable Events** to **On**.
3. Under **Subscribe to bot events**, add:
   - `message.channels`
   - `message.groups`
   - `message.im`
4. Click **Save Changes**.

### E. Enable the Messages Tab (Critical for Direct Messages)

1. Go to **Features > App Home**.
2. Scroll to **Show Tabs**.
3. Ensure **Messages Tab** is checked.
4. Check **Allow users to send Slash commands and messages from the messages tab**.

### F. Add Slash Commands (Recommended)

1. Go to **Features > Slash Commands**.
2. Click **Create New Command**.
   - **Command:** `/end`
   - **Short Description:** Ends the PinionAI chat session.
3. Click **Save**.

---

## 2. Environment Setup

Copy `.env.example` to `.env` and fill in your credentials:

```env
# PinionAI Credentials
client_id=<YOUR_CLIENT_ID>
client_secret=<YOUR_CLIENT_SECRET>
agent_id=<YOUR_AGENT_ID>
host_url=https://microservice-72loomfx5q-uc.a.run.app

# Slack Credentials
SLACK_BOT_TOKEN=xoxb-...
SLACK_APP_TOKEN=xapp-...
```

---

## 3. Local Deployment

1. **Activate your environment:**
   ```bash
   source pinionai-streamlit/bin/activate
   ```
2. **Install Dependencies:**
   ```bash
   uv pip compile requirements.in -o requirements.txt
   uv pip sync requirements.txt
   ```
3. **Run the Bot:**
   ```bash
   python chat_slack.py
   ```

---

## 4. Cloud Deployment (Google Cloud Run)

For production, you can deploy the bot as a containerized service.

1. **Update `deploy/prod-slack/env.yaml`** with your production tokens.
2. **Build and Push the Image:**
   ```bash
   gcloud builds submit --tag gcr.io/YOUR_PROJECT_ID/pinionai-slack-bot
   ```
3. **Deploy to Cloud Run:**
   ```bash
   gcloud run deploy pinionai-slack-bot
       --image gcr.io/YOUR_PROJECT_ID/pinionai-slack-bot
       --env-vars-file deploy/prod-slack/env.yaml
       --no-allow-unauthenticated
   ```

---

## 5. Usage Guide

### Chatting

- **Direct Message:** Simply message the bot in its "Messages" tab.
- **Channels:** Invite the bot to a channel (`/invite @BotName`) and type a message.

### Dynamic Agent Loading

You can change the active agent for a channel at any time by **uploading a `.aia` file**.

1. Upload the `.aia` file to the chat.
2. The bot will automatically switch to that agent for all future messages in that channel.
3. **Private Agents:** If the file is encrypted, the bot will ask for the `key_secret`. Reply with the secret key to unlock the agent.

### Cleaning Slack Formatting

The bot automatically cleans Slack's specific formatting. If you type an email address or link, it strips wrappers like `<mailto:alan@example.com|alan@example.com>` into plain text before passing it to the AI.

### Ending a Session

To clear the chat history and reset the agent:

- Type the Slash command: `/end`
- OR type the message: `!end`

---

## 6. Troubleshooting

- **"Sending messages to this app has been turned off"**: Go to **App Home** and enable the **Messages Tab** and user messaging checkbox.
- **Bot doesn't reply in channels**: Ensure the bot has been invited to the channel (`/invite @BotName`).
- **Bot doesn't see messages**: Check **Event Subscriptions** and ensure `message.channels` is added and changes are saved.
- **SyntaxError or ModuleNotFoundError**: Ensure you have activated your virtual environment and installed `httpx`, `slack-bolt`, and `python-dotenv`.
