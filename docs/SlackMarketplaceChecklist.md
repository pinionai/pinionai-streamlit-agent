# Slack Marketplace Submission Checklist

Use this checklist before submitting your Slack app to the Slack Marketplace or App Directory.

## Required app settings

- [ ] The app has a clear name, icon, and description.
- [ ] Public distribution is enabled.
- [ ] The app is configured for App Directory submission rather than Socket Mode.
- [ ] Event Subscriptions are enabled.
- [ ] A public HTTPS Request URL is configured and verified.
- [ ] Interactivity is enabled with a verified Request URL.
- [ ] Slash commands use verified Request URLs when applicable.

## OAuth and permissions

- [ ] Bot scopes are correctly granted.
- [ ] The app is installed to the workspace where you tested it.
- [ ] The bot token is available in your deployment environment.
- [ ] Any required user scopes are listed in the app configuration.

## App profile and compliance

- [ ] Support URL is provided.
- [ ] Privacy policy URL is provided.
- [ ] App description and screenshots are complete.
- [ ] The app is ready for community/public distribution.

## Common blockers

If you still see submission errors, check the following first:

- Socket Mode is not being used as the app's submission path.
- Public distribution is enabled in the App Distribution settings.
- Your Request URLs are reachable and verified by Slack.
- You have completed the required app profile metadata.

## Recommended approach

If your app currently relies on Socket Mode for local development, keep that setup for private/internal use, but create a separate public HTTPS deployment for App Directory review.
