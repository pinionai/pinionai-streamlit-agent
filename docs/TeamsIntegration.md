# Microsoft Teams Integration Guide - PinionAI Agent Runner

This guide provides step-by-step instructions for setting up a Microsoft Teams Bot, configuring the PinionAI Teams bot (`chat_teams.py`), and establishing a secure tunnel for local testing.

## Table of Contents
1. [Registering the Azure Bot](#1-registering-the-azure-bot)
2. [Obtaining Credentials](#2-obtaining-credentials)
3. [Configuring Channels](#3-configuring-channels)
4. [Local Tunneling with ngrok](#4-local-tunneling-with-ngrok)
5. [Environment Setup](#5-environment-setup)
6. [Usage Guide](#6-usage-guide)

---

## 1. Registering the Azure Bot

Microsoft Teams bots are managed through the Azure Bot Service.

1.  Log in to the [Azure Portal](https://portal.azure.com/).
2.  Search for **"Azure Bot"** in the top search bar and select it.
3.  Click **Create**.
4.  **Bot Handle:** Give your bot a unique name.
5.  **Subscription/Resource Group:** Select your subscription and create/select a resource group.
6.  **Data Residency:** Select "Global".
7.  **Pricing Tier:** Select **F0 (Free)** for development and testing.
8.  **Type of App:** Select **Multi Tenant**.
9.  **Creation Type:** Select "Create new Microsoft App ID".
10. Click **Review + create**, then **Create**.

---

## 2. Obtaining Credentials

You need the Microsoft App ID and Client Secret to authenticate your bot.

1.  Navigate to your new **Azure Bot** resource.
2.  In the left sidebar, under **Settings**, click **Configuration**.
3.  **Microsoft App ID:** Copy this value. This is your `TEAMS_APP_ID`.
4.  Next to the App ID, click the **Manage Password** link.
5.  Under **Certificates & secrets**, click **+ New client secret**.
6.  Provide a description (e.g., "TeamsBotSecret") and click **Add**.
7.  **Value:** Copy the **Value** string immediately. This is your `TEAMS_APP_PASSWORD`. *Note: This value is hidden once you leave the page.*

---

## 3. Configuring Channels

By default, your bot is not connected to Microsoft Teams.

1.  In your Azure Bot resource, click **Channels** in the sidebar.
2.  Select the **Microsoft Teams** icon from the list of available channels.
3.  Agree to the Terms of Service and click **Apply**.
4.  Your bot is now authorized to communicate with Teams.

---

## 4. Local Tunneling with ngrok

Because Teams communicates via webhooks, your local development server needs a public HTTPS endpoint.

1.  **Install ngrok:**
    ```bash
    brew install ngrok/ngrok/ngrok  # macOS
    ```
2.  **Start the tunnel:**
    ```bash
    ngrok http 3978
    ```
3.  **Copy the Forwarding URL:** (e.g., `https://a1b2-c3d4.ngrok-free.app`).
4.  **Set Messaging Endpoint:**
    - Go back to **Azure Bot > Configuration**.
    - In **Messaging endpoint**, paste your ngrok URL and append `/api/messages`.
    - Example: `https://a1b2-c3d4.ngrok-free.app/api/messages`
    - Click **Apply**.

---

## 5. Environment Setup

Update your `.env` file with the Teams-specific variables:

```env
# Teams Credentials
TEAMS_APP_ID=your-microsoft-app-id
TEAMS_APP_PASSWORD=your-client-secret-value
PORT=3978

# PinionAI Base Config
host_url=https://microservice-72loomfx5q-uc.a.run.app
```

---

## 6. Usage Guide

### Starting the Bot
1. Activate your environment: `source pinionai-streamlit/bin/activate`
2. Run the bot: `python chat_teams.py`

### Testing in Teams
1. In the Azure Portal, go to **Azure Bot > Channels**.
2. Click **Open in Teams**.
3. Alternatively, search for your `TEAMS_APP_ID` directly in the Teams search bar.

### Features
- **Direct Chat:** Simply type a message to start a conversation.
- **AIA File Loading:** Upload a `.aia` file as an attachment to dynamically switch agents for that conversation.
- **Encrypted Agents:** If an uploaded AIA file is private, the bot will prompt you for the `key_secret`.
- **Session Reset:** Type `/end` to clear the current session.
