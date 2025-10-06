# Embedding PinionAI with iframes

## Overview

PinionAI is designed for seamless integration. Both the PinionAI Studio and PinionAI clients can be embedded directly into your existing websites, applications, and internal infrastructure using a simple HTML `<iframe>` tag. This allows you to bring the power of PinionAI to your users exactly where they need it.

This guide provides the basic code and explanation for embedding these components.

---

## Embedding a PinionAI Client

You can embed a PinionAI chat client to provide direct interaction capabilities within your application. This is useful for customer support portals, internal helpdesks, or any page where you want to offer AI-assisted chat.

### Example

To embed the chat client, add the following HTML snippet to your webpage's `<body>`.

```html
<!DOCTYPE html>
<html>
  <head>
    <title>PinionAI Client Embed</title>
    <style>
      /* Basic responsive styling for the iframe */
      iframe {
        border: 1px solid #ccc; /* Optional: adds a border */
        width: 100%;
        max-width: 800px; /* Optional: sets a max width */
        aspect-ratio: 16 / 12;
      }
    </style>
  </head>
  <body>
    <h1>PinionAI Chat Client</h1>
    <iframe
      id="chat"
      src="https://pinion-ai-chat-72loomfx5q-uc.a.run.app"
      allow="clipboard-write"
      frameborder="0"
    >
    </iframe>
  </body>
</html>
```

### Key Attributes

- **`id`**: A unique identifier for the iframe element.
- **`src`**: The most important attribute. This is the URL for the PinionAI client you wish to embed.
- **`allow="clipboard-write"`**: This permission is recommended as it allows users to copy text from the chat interface to their clipboard.
- **`frameborder="0"`**: Removes the default border from the iframe for a cleaner, more integrated look.

---

## Embedding PinionAI Studio

For administrators and developers, the entire PinionAI Studio can be embedded into an internal dashboard or admin panel. This provides a centralized location to manage, configure, and monitor your AI models and agents without leaving your own environment.

### Example

To embed the PinionAI Studio, use the following HTML snippet.

```html
<!DOCTYPE html>
<html>
  <head>
    <title>PinionAI Studio Embed</title>
    <style>
      /* Full-screen iframe styling */
      html,
      body {
        margin: 0;
        padding: 0;
        height: 100%;
        overflow: hidden; /* Prevents scrollbars on the body */
      }
      iframe {
        width: 100%;
        height: 100%;
        border: none; /* Ensures no border */
      }
    </style>
  </head>
  <body>
    <iframe
      id="pinionaiStudio"
      src="https://pinionai-grpc-server-72loomfx5q-uc.a.run.app"
      allow="clipboard-write"
      frameborder="0"
    >
    </iframe>
  </body>
</html>
```

### Key Attributes

- **`id`**: A unique identifier for the studio iframe.
- **`src`**: The URL for the PinionAI Studio.
- **`allow`**: You may need to add other permissions depending on the studio's features (e.g., `microphone`, `camera`). `clipboard-write` is a good starting point.
- **`frameborder="0"`**: Essential for making the studio feel like a native part of your dashboard.

The CSS in this example is designed to make the iframe take up the entire viewport, which is a common use case for embedding a full application like the studio.
