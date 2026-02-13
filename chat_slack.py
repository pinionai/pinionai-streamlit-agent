"""Slack-based chat client for PinionAI using AsyncPinionAIClient.

Usage:
    Set SLACK_BOT_TOKEN and SLACK_APP_TOKEN in your environment.
    python chat_slack.py

This client uses slack_bolt (AsyncApp) and interacts via Slack messages.
It supports loading agents from uploaded .aia files.
"""
import os
import asyncio
import logging
import httpx
import re
from slack_bolt.async_app import AsyncApp
from slack_bolt.adapter.socket_mode.async_handler import AsyncSocketModeHandler
from pinionai import AsyncPinionAIClient
from pinionai.exceptions import PinionAIConfigurationError, PinionAIError
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Logging setup
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Slack configuration
SLACK_BOT_TOKEN = os.environ.get("SLACK_BOT_TOKEN")
SLACK_APP_TOKEN = os.environ.get("SLACK_APP_TOKEN")

if not SLACK_BOT_TOKEN or not SLACK_APP_TOKEN:
    logger.error("SLACK_BOT_TOKEN and SLACK_APP_TOKEN must be set in environment variables.")
    exit(1)

app = AsyncApp(token=SLACK_BOT_TOKEN)

# Session management: channel_id -> AsyncPinionAIClient
sessions = {}

# State management for private AIA files: channel_id -> { "file_content": ..., "awaiting_secret": True }
pending_agents = {}

def clean_slack_text(text: str) -> str:
    """
    Removes Slack-specific formatting like <mailto:alan@westcompass.com|alan@westcompass.com>
    and <https://example.com|example.com>.
    """
    if not text:
        return ""
    # 1. Handle mailto links: <mailto:email|email> -> email
    text = re.sub(r'<mailto:([^|>]+)(\|[^>]+)?>', r'\1', text)
    # 2. Handle general links: <http://url|label> -> http://url
    text = re.sub(r'<([^|>]+)(\|[^>]+)?>', r'\1', text)
    return text

async def get_client(channel_id: str) -> AsyncPinionAIClient:
    """Gets or initializes the PinionAI client for a given channel."""
    if channel_id in sessions:
        return sessions[channel_id]
    
    # Try to initialize from environment variables
    agent_id = os.environ.get("agent_id")
    host_url = os.environ.get("host_url")
    client_id = os.environ.get("client_id")
    client_secret = os.environ.get("client_secret")
    
    if agent_id and host_url and client_id and client_secret:
        try:
            logger.info(f"Initializing default agent for channel {channel_id}")
            client = await AsyncPinionAIClient.create(
                agent_id=agent_id,
                host_url=host_url,
                client_id=client_id,
                client_secret=client_secret,
                version=os.environ.get("version", None),
            )
            # Add initial greeting if defined
            if not client.chat_messages and client.var.get("agentStart"):
                client.add_message_to_history("assistant", client.var["agentStart"])
            
            sessions[channel_id] = client
            return client
        except Exception as e:
            logger.error(f"Failed to auto-initialize client for {channel_id}: {e}")
    
    return None

@app.command("/end")
async def handle_end_command(ack, body, say):
    """Handles the /end slash command."""
    await ack()
    channel_id = body["channel_id"]
    if channel_id in sessions:
        await sessions[channel_id].end_grpc_chat_session()
        del sessions[channel_id]
        await say("Conversation ended and session cleared.")
    else:
        await say("No active session to end.")

@app.event("message")
async def handle_message_events(event, say):
    """Handles incoming messages and file uploads."""
    channel_id = event["channel"]
    user_id = event.get("user")
    raw_text = event.get("text", "").strip()
    text = clean_slack_text(raw_text)
    
    # Ignore bot messages to prevent loops
    if event.get("bot_id") or not user_id:
        return

    # 1. Handle Secret Key for private AIA files
    if channel_id in pending_agents and pending_agents[channel_id].get("awaiting_secret"):
        pending = pending_agents.pop(channel_id)
        try:
            await say("Decrypting and loading agent...")
            p_client, init_message = await AsyncPinionAIClient.create_from_stream(
                file_stream=pending["file_content"],
                host_url=os.environ.get("host_url"),
                key_secret=text
            )
            if p_client:
                sessions[channel_id] = p_client
                greeting = p_client.var.get("agentStart", "Agent loaded successfully!")
                await say(f"*{p_client.var.get('agentTitle', 'Agent')}* loaded.\n{greeting}")
            else:
                await say(f"Failed to load agent: {init_message}")
        except Exception as e:
            logger.error(f"Error loading agent with secret: {e}")
            await say(f"Error loading agent: {e}")
        return

    # 2. Handle AIA File Uploads
    if "files" in event:
        for file in event["files"]:
            if file["name"].endswith(".aia"):
                file_url = file["url_private"]
                headers = {"Authorization": f"Bearer {SLACK_BOT_TOKEN}"}
                async with httpx.AsyncClient() as http_client:
                    try:
                        response = await http_client.get(file_url, headers=headers)
                        response.raise_for_status()
                        file_content = response.text
                        
                        p_client, init_message = await AsyncPinionAIClient.create_from_stream(
                            file_stream=file_content,
                            host_url=os.environ.get("host_url")
                        )
                        
                        if init_message == 'key_secret required for private version':
                            pending_agents[channel_id] = {
                                "file_content": file_content,
                                "awaiting_secret": True
                            }
                            await say("This AIA file is private and requires a secret key. Please reply with the key.")
                            return
                        elif p_client:
                            sessions[channel_id] = p_client
                            greeting = p_client.var.get("agentStart", "Agent loaded successfully!")
                            await say(f"*{p_client.var.get('agentTitle', 'Agent')}* loaded from file.\n{greeting}")
                            return
                        else:
                            await say(f"Could not load agent: {init_message}")
                    except Exception as e:
                        logger.error(f"Error downloading/processing AIA file: {e}")
                        await say(f"Error processing AIA file: {e}")
                return

    if not text:
        return

    # 3. Handle Commands
    if text.lower() in ["/end", "!end"]:
        if channel_id in sessions:
            await sessions[channel_id].end_grpc_chat_session()
            del sessions[channel_id]
            await say("Conversation ended and session cleared.")
        else:
            await say("No active session to end.")
        return

    # 4. Process Message with PinionAI
    p_client = await get_client(channel_id)
    if not p_client:
        await say("No agent is active in this channel. Upload an `.aia` file or ensure environment variables are set.")
        return

    try:
        p_client.add_message_to_history("user", text)
        
        # In Slack, we don't have a 'spinner', so we can optionally send a 'typing' indicator or just wait.
        # Socket Mode doesn't support easy typing indicators via this API, so we just process.
        
        # AI Processing
        response_text = await p_client.process_user_input(text, sender="user")
        await say(response_text)
        await p_client.update_pinion_session()
        
        # Handle follow-up intents
        if p_client.next_intent:
             follow_up = await p_client.process_user_input("", sender="user")
             await say(follow_up)
             await p_client.update_pinion_session()
             
        # Note: gRPC live transfer is not fully implemented here as it would require
        # a long-running background task per channel to listen for gRPC updates
        # and push them to Slack.
             
    except PinionAIError as e:
        logger.error(f"PinionAI Error: {e}")
        await say(f"Agent Error: {e}")
    except Exception as e:
        logger.exception("Unexpected error during message processing")
        await say(f"An unexpected error occurred: {e}")

async def main():
    logger.info("Starting PinionAI Slack Bot in Socket Mode...")
    handler = AsyncSocketModeHandler(app, SLACK_APP_TOKEN)
    await handler.start_async()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user.")
