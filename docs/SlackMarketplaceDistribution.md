# Slack Marketplace / App Directory Distribution Guide

This guide covers the extra setup required when you want to submit a Slack app to the Slack Marketplace or App Directory.

> The Socket Mode approach described in the existing Slack integration documentation is appropriate for internal or private Slack bots. It is not suitable for public App Directory submission.

For Slack Marketplace submission, use an HTTP-based Slack app configuration instead of Socket Mode:

1. Create or update the Slack app in the Slack API dashboard.
2. Do not rely on Socket Mode for the public submission flow.
3. Enable HTTP Request URLs for the app.
4. Enable public distribution in the app settings.

## Recommended setup for App Directory submission

### 1. Create the app

1. Go to https://api.slack.com/apps.
2. Create a new app or reopen your existing app.
3. Choose a public-facing name, description, and icon.

### 2. Use HTTP Request URLs instead of Socket Mode

For App Directory submission, Slack expects a publicly reachable HTTPS endpoint.

1. Open Settings > Basic Information.
2. Configure your app's Request URL(s) for:
   - Event Subscriptions
   - Interactivity & Shortcuts
   - Slash Commands
3. Make sure the endpoint is publicly reachable over HTTPS.
4. Verify the Request URL in Slack before submitting.

### 3. Enable Event Subscriptions

1. Open Features > Event Subscriptions.
2. Turn on Event Subscriptions.
3. Add the events your bot needs, such as:
   - `message.channels`
   - `message.groups`
   - `message.im`
4. Save the Request URL and verify it.

### 4. Configure bot scopes

In Features > OAuth & Permissions, add the permissions your app needs, for example:

- `chat:write`
- `files:read`
- `im:history`
- `channels:history`
- `groups:history`
- `commands` (if you expose slash commands)

Install the app to one or more workspaces and collect the bot token.

### 5. Enable public distribution

1. Open Settings > App Distribution.
2. Turn on public distribution.
3. Complete the app profile fields, including:
   - short description
   - long description
   - support email or URL
   - privacy policy URL
   - app icon
4. Make sure the app is marked as available for other workspaces.

## Important note for this repository

The current sample in this repository uses Socket Mode and is therefore best suited for private or internal Slack deployments. If you want to submit to the Slack App Directory, you will need a public HTTPS-based Slack integration that receives Slack events over HTTP and forwards them to your bot logic.

In other words:

- Existing Socket Mode flow: good for private/internal bots.
- Marketplace / App Directory flow: requires HTTP Request URLs and public distribution.

## Submission checklist before review

Before submitting to the Slack Marketplace, confirm that:

- Socket Mode is not being used as the public submission path.
- Event Subscriptions have a verified HTTPS Request URL.
- Interactivity and slash commands have verified Request URLs.
- Public distribution is enabled.
- Your app has a support URL and privacy policy.
- The app has been tested in a real workspace.

## Suggested deployment pattern

For a marketplace-ready setup, use a public HTTPS service such as:

- Cloud Run
- GCP Compute Engine
- DigitalOcean droplet
- any other public HTTPS host with a valid TLS certificate

Your deployment should expose endpoints for Slack event handling and serve the Slack app through the standard HTTP-based flow.
