"""Terminal-based chat client for PinionAI using AsyncPinionAIClient.

Usage:
    python chat_cli.py

Controls:
    /end    - end chat session and exit
    /continue - continue polling or force refresh

This client uses AsyncPinionAIClient and interacts via stdin/stdout.
"""
import os
import time
import asyncio
import threading
from pinionai import AsyncPinionAIClient
from pinionai.exceptions import PinionAIConfigurationError, PinionAIError
from dotenv import load_dotenv
load_dotenv()

# Persistent event loop management 
_event_loop = None
_event_loop_lock = threading.Lock()

def get_event_loop():
    global _event_loop
    with _event_loop_lock:
        if _event_loop is None:
            _event_loop = asyncio.new_event_loop()
            threading.Thread(target=_event_loop.run_forever, daemon=True).start()
    return _event_loop

def run_coroutine_in_event_loop(coroutine):
    loop = get_event_loop()
    return asyncio.run_coroutine_threadsafe(coroutine, loop).result()

def poll_for_updates(client: AsyncPinionAIClient, timeout: int, http_poll_start: int = 30, http_poll_interval: int = 5):
    """Polls for updates and returns True if a rerun is needed."""
    start_time = time.time()
    next_http_poll_time = start_time + http_poll_start

    while time.time() - start_time < timeout:
        # Primary check: Has a gRPC message arrived recently?
        if (time.time() - client._grpc_last_update_time) < 2.0:
            return True
        # Fallback check: Poll HTTP endpoint
        now = time.time()
        if now >= next_http_poll_time:
            try:
                lastmodified_server, _ = run_coroutine_in_event_loop(client.get_latest_session_modification_time())
                if lastmodified_server and lastmodified_server != client.last_session_post_modified:
                    return True
                next_http_poll_time = now + http_poll_interval
            except Exception as e:
                print(f"Warning: Could not check for session updates: {e}")
                next_http_poll_time = now + http_poll_interval
        time.sleep(0.1)
    return False

def ensure_grpc_is_active(client: AsyncPinionAIClient):
    if not client._grpc_stub:
        try:
            is_started = run_coroutine_in_event_loop(client.start_grpc_client_listener(sender_id="user"))
            if is_started:
                print("Connecting to live agent...")
                return True
            else:
                print("Could not connect to live agent service.")
                return False
        except Exception as e:
            print(f"Failed to start gRPC listener: {e}")
            return False
    return True

def display_messages(messages, user_img=None, assistant_img=None):
    for message in messages:
        role = message.get("role")
        content = message.get("content")
        prefix = "User: " if role == "user" else "Agent: "
        print(f"{prefix}{content}")

def main():
    # Initialize client
    try:
        client = run_coroutine_in_event_loop(AsyncPinionAIClient.create(
            agent_id=os.environ.get("agent_id"),
            host_url=os.environ.get("host_url"),
            client_id=os.environ.get("client_id"),
            client_secret=os.environ.get("client_secret"),
            version=None
        ))
    except PinionAIConfigurationError as e:
        print(f"Failed to initialize PinionAI client: {e}")
        return

    var = client.var
    print(var.get("agentTitle"),"PinionAI Terminal Chat")
    print(var.get("agentSubtitle"))
    print("Type your message and press Enter. Use /end to quit.")
    user_img = var.get("userImage")
    assistant_img = var.get("assistImage")

    # If there's an agentStart message, show it
    if not client.chat_messages and var.get("agentStart"):
        client.add_message_to_history("assistant", var["agentStart"])

    display_messages(client.get_chat_messages_for_display(), user_img, assistant_img)

    while True:
        try:
            prompt = input("You: ")
        except EOFError:
            print("EOF received, exiting.")
            break

        if not prompt:
            continue
        if prompt.strip().lower() == "/end":
            run_coroutine_in_event_loop(client.end_grpc_chat_session())
            print("Chat ended.")
            break
        if prompt.strip().lower() == "/continue":
            print("Continuing / refreshing...")
            # show any new messages
            if poll_for_updates(client, timeout=5):
                display_messages(client.get_chat_messages_for_display(), user_img, assistant_img)
            continue

        # Add user message
        client.add_message_to_history("user", prompt)
        # print(f"You: {prompt}")

        if client.transfer_requested:
            if ensure_grpc_is_active(client):
                run_coroutine_in_event_loop(client.update_pinion_session())
                run_coroutine_in_event_loop(client.send_grpc_message(prompt))
                if poll_for_updates(client, timeout=180):
                    display_messages(client.get_chat_messages_for_display(), user_img, assistant_img)
                else:
                    print("No new messages in the last 3 minutes. Type /continue or /end.")
            else:
                print("Could not connect to live agent service.")
        else:
            # AI flow
            try:
                full_ai_response_string = run_coroutine_in_event_loop(client.process_user_input(prompt, sender="user"))
                print(f"Agent: {full_ai_response_string}")
                run_coroutine_in_event_loop(client.update_pinion_session())

                if client.next_intent:
                    full_ai_response_string = run_coroutine_in_event_loop(client.process_user_input(prompt, sender="user"))
                    print(f"Agent (follow-up): {full_ai_response_string}")
                    run_coroutine_in_event_loop(client.update_pinion_session())

                # After AI response, check if transfer requested
                if client.transfer_requested:
                    if ensure_grpc_is_active(client):
                        print("Transfer to live agent initiated... Waiting for agent to connect.")
                        if poll_for_updates(client, timeout=180):
                            display_messages(client.get_chat_messages_for_display(), user_img, assistant_img)
                        else:
                            print("No new messages in the last 3 minutes. Type /continue or /end.")
                    else:
                        print("Could not connect to live agent service for transfer.")
            except PinionAIError as e:
                print(f"Error from PinionAI: {e}")
            except Exception as e:
                print(f"Unexpected error: {e}")

if __name__ == "__main__":
    main()