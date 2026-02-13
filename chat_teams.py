"""Microsoft Teams chat client for PinionAI using AsyncPinionAIClient.

Usage:
    Set TEAMS_APP_ID and TEAMS_APP_PASSWORD in your environment.
    python chat_teams.py

This client uses botbuilder-core and botbuilder-integration-aiohttp.
It supports loading agents from uploaded .aia files.
"""
import os
import sys
import asyncio
import logging
import httpx
from aiohttp import web
from botbuilder.core import (
    BotFrameworkAdapter,
    BotFrameworkAdapterSettings,
    TurnContext,
    ActivityHandler,
)
from botbuilder.schema import Activity, ActivityTypes
from pinionai import AsyncPinionAIClient
from pinionai.exceptions import PinionAIConfigurationError, PinionAIError
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Logging setup
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Teams configuration
APP_ID = os.environ.get("TEAMS_APP_ID", "")
APP_PASSWORD = os.environ.get("TEAMS_APP_PASSWORD", "")
PORT = int(os.environ.get("PORT", 3978))

SETTINGS = BotFrameworkAdapterSettings(APP_ID, APP_PASSWORD)
ADAPTER = BotFrameworkAdapter(SETTINGS)

# Session management: conversation_id -> AsyncPinionAIClient
sessions = {}

# State management for private AIA files: conversation_id -> { "file_content": ..., "awaiting_secret": True }
pending_agents = {}

async def get_client(conversation_id: str) -> AsyncPinionAIClient:
    """Gets or initializes the PinionAI client for a given conversation."""
    if conversation_id in sessions:
        return sessions[conversation_id]
    
    # Try to initialize from environment variables
    agent_id = os.environ.get("agent_id")
    host_url = os.environ.get("host_url")
    client_id = os.environ.get("client_id")
    client_secret = os.environ.get("client_secret")
    
    if agent_id and host_url and client_id and client_secret:
        try:
            logger.info(f"Initializing default agent for conversation {conversation_id}")
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
            
            sessions[conversation_id] = client
            return client
        except Exception as e:
            logger.error(f"Failed to auto-initialize client for {conversation_id}: {e}")
    
    return None

class PinionAIBot(ActivityHandler):
    async def on_message_activity(self, turn_context: TurnContext):
        conversation_id = turn_context.activity.conversation.id
        text = turn_context.activity.text.strip() if turn_context.activity.text else ""
        
        # 1. Handle Secret Key for private AIA files
        if conversation_id in pending_agents and pending_agents[conversation_id].get("awaiting_secret"):
            pending = pending_agents.pop(conversation_id)
            try:
                await turn_context.send_activity("Decrypting and loading agent...")
                p_client, init_message = await AsyncPinionAIClient.create_from_stream(
                    file_stream=pending["file_content"],
                    host_url=os.environ.get("host_url"),
                    key_secret=text
                )
                if p_client:
                    sessions[conversation_id] = p_client
                    greeting = p_client.var.get("agentStart", "Agent loaded successfully!")
                    await turn_context.send_activity(f"**{p_client.var.get('agentTitle', 'Agent')}** loaded.\n\n{greeting}")
                else:
                    await turn_context.send_activity(f"Failed to load agent: {init_message}")
            except Exception as e:
                logger.error(f"Error loading agent with secret: {e}")
                await turn_context.send_activity(f"Error loading agent: {e}")
            return

        # 2. Handle AIA File Uploads
        if turn_context.activity.attachments:
            for attachment in turn_context.activity.attachments:
                if attachment.name and attachment.name.endswith(".aia"):
                    file_url = attachment.content_url
                    async with httpx.AsyncClient() as http_client:
                        try:
                            # Note: Teams file downloads might require Auth headers if not public
                            # For simplicity, we assume the URL is accessible or handle it here
                            response = await http_client.get(file_url)
                            response.raise_for_status()
                            file_content = response.text
                            
                            p_client, init_message = await AsyncPinionAIClient.create_from_stream(
                                file_stream=file_content,
                                host_url=os.environ.get("host_url")
                            )
                            
                            if init_message == 'key_secret required for private version':
                                pending_agents[conversation_id] = {
                                    "file_content": file_content,
                                    "awaiting_secret": True
                                }
                                await turn_context.send_activity("This AIA file is private and requires a secret key. Please reply with the key.")
                                return
                            elif p_client:
                                sessions[conversation_id] = p_client
                                greeting = p_client.var.get("agentStart", "Agent loaded successfully!")
                                await turn_context.send_activity(f"**{p_client.var.get('agentTitle', 'Agent')}** loaded from file.\n\n{greeting}")
                                return
                            else:
                                await turn_context.send_activity(f"Could not load agent: {init_message}")
                        except Exception as e:
                            logger.error(f"Error downloading/processing AIA file: {e}")
                            await turn_context.send_activity(f"Error processing AIA file: {e}")
                    return

        if not text:
            return

        # 3. Handle Commands
        if text.lower() == "/end":
            if conversation_id in sessions:
                await sessions[conversation_id].end_grpc_chat_session()
                del sessions[conversation_id]
                await turn_context.send_activity("Conversation ended and session cleared.")
            else:
                await turn_context.send_activity("No active session to end.")
            return

        # 4. Process Message with PinionAI
        p_client = await get_client(conversation_id)
        if not p_client:
            await turn_context.send_activity("No agent is active in this conversation. Upload an `.aia` file or ensure environment variables are set.")
            return

        try:
            p_client.add_message_to_history("user", text)
            
            # AI Processing
            response_text = await p_client.process_user_input(text, sender="user")
            await turn_context.send_activity(response_text)
            await p_client.update_pinion_session()
            
            # Handle follow-up intents
            if p_client.next_intent:
                 follow_up = await p_client.process_user_input("", sender="user")
                 await turn_context.send_activity(follow_up)
                 await p_client.update_pinion_session()
                 
        except PinionAIError as e:
            logger.error(f"PinionAI Error: {e}")
            await turn_context.send_activity(f"Agent Error: {e}")
        except Exception as e:
            logger.exception("Unexpected error during message processing")
            await turn_context.send_activity(f"An unexpected error occurred: {e}")

BOT = PinionAIBot()

async def messages(request: web.Request) -> web.Response:
    if "application/json" in request.content_type:
        body = await request.json()
    else:
        return web.Response(status=415)

    activity = Activity().deserialize(body)
    auth_header = request.headers.get("Authorization", "")

    response = await ADAPTER.process_activity(activity, auth_header, BOT.on_turn)
    if response:
        return web.json_response(data=response.body, status=response.status)
    return web.Response(status=201)

APP = web.Application()
APP.router.add_post("/api/messages", messages)

if __name__ == "__main__":
    try:
        web.run_app(APP, host="localhost", port=PORT)
    except Exception as error:
        raise error
