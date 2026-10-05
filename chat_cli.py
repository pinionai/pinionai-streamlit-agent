"""Terminal-based chat client for PinionAI using AsyncPinionAIClient.

Usage:
    python chat_cli.py

Controls:
    /end    - end chat session and exit
    /continue - continue polling or force refresh

This client uses AsyncPinionAIClient and interacts via stdin/stdout.
"""
import argparse
import os
import time
import asyncio
import threading
import getpass
from pinionai import AsyncPinionAIClient
from pinionai.exceptions import PinionAIConfigurationError, PinionAIError
from agent_selection import (
    get_available_agents,
    merge_agent_capabilities,
    resolve_agent,
)
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

def cleanup_client(client: AsyncPinionAIClient):
    """Clean up client resources, particularly the HTTP session."""
    try:
        if hasattr(client, '_http_session') and client._http_session:
            run_coroutine_in_event_loop(client._http_session.aclose())
    except Exception as e:
        print(f"Warning: Error closing HTTP session: {e}")

def select_agent_interactively(client: AsyncPinionAIClient, default_agent_id: str):
    """Offer account agents in the terminal, retaining the configured agent by default."""
    try:
        agents = run_coroutine_in_event_loop(get_available_agents(client))
    except Exception as e:
        print(f"Could not list available agents: {e}")
        return client
    if not agents:
        print("No agents were returned for this account.")
        return client

    default_agent = resolve_agent(agents, default_agent_id) if default_agent_id else None
    if default_agent is None:
        default_agent = agents[0]
    print("Available agents:")
    for index, agent in enumerate(agents, start=1):
        default_marker = " (default)" if agent["uid"] == default_agent["uid"] else ""
        print(f"  {index}. {agent['agent_name']} [{agent['uid']}]{default_marker}")

    selection = input("Select by number, name, or UID (Enter keeps default): ").strip()
    if not selection:
        selected_agent = default_agent
    elif selection.isdigit() and 1 <= int(selection) <= len(agents):
        selected_agent = agents[int(selection) - 1]
    else:
        selected_agent = resolve_agent(agents, selection)
        if selected_agent is None:
            print("Selection not found; keeping the default agent.")
            selected_agent = default_agent

    if selected_agent["uid"] == getattr(client, "_agent_id", default_agent_id):
        return client

    try:
        new_client = run_coroutine_in_event_loop(AsyncPinionAIClient.create(
            agent_id=selected_agent["uid"],
            host_url=os.environ.get("host_url"),
            client_id=os.environ.get("client_id"),
            client_secret=os.environ.get("client_secret"),
            version=os.environ.get("version", None),
        ))
        cleanup_client(client)
        return new_client
    except Exception as e:
        print(f"Failed to load selected agent: {e}")
        return client

def main():
    parser = argparse.ArgumentParser(description="CLI for interacting with an agent.")
    
    # Add the new argument for the .aia file
    parser.add_argument(
        "-f", "--aia-file",
        type=str,
        help="Path to the .aia agent file to run. If provided, environment variables for client/agent IDs are ignored."
    )
    # You might have other arguments, keep them here
    # parser.add_argument(...) 
    args = parser.parse_args()

    def load_agent_from_aia_path(path: str):
        """Load an agent from a .aia file path. Returns client or None."""
        if not os.path.exists(path):
            print(f"Error: File not found at '{path}'")
            return None
        try:
            with open(path, "rb") as f:
                raw = f.read()
            file_text = raw.decode("utf-8")
            client, init_message = run_coroutine_in_event_loop(AsyncPinionAIClient.create_from_stream(
                file_stream=file_text,
                host_url=os.environ.get("host_url")
            ))
            if client:
                return client
            if init_message == 'key_secret required for private version':
                print("This AIA file requires a key_secret to decrypt.")
                for attempt in range(3):
                    key_secret = getpass.getpass("Enter key_secret: ")
                    if not key_secret:
                        print("No key_secret entered; try again.")
                        continue
                    try:
                        client, init_message = run_coroutine_in_event_loop(AsyncPinionAIClient.create_from_stream(
                            file_stream=file_text,
                            host_url=os.environ.get("host_url"),
                            key_secret=key_secret
                        ))
                        if client:
                            return client
                        else:
                            print(f"Failed to load agent: {init_message}")
                    except PinionAIError as e:
                        print(f"Failed to decrypt AIA file with provided key_secret: {e}")
                print("Exceeded key_secret attempts. Aborting.")
                return None
            else:
                print(f"Could not create agent from file: {init_message}")
                return None
        except PinionAIError as e:
            print(f"Failed to initialize PinionAI client from AIA file: {e}")
            return None
        except Exception as e:
            print(f"Unexpected error while reading AIA file: {e}")
            return None

    client = None
    # Try AIA file from CLI flag first
    if args.aia_file:
        print(f"Loading agent from file: {args.aia_file}")
        client = load_agent_from_aia_path(args.aia_file)

    # If no AIA file or it failed, try env-based creation (only if all required env vars are present)
    if client is None:
        agent_id = os.environ.get("agent_id")
        host_url = os.environ.get("host_url")
        client_id = os.environ.get("client_id")
        client_secret = os.environ.get("client_secret")
        
        # Check if all required environment variables are set
        if agent_id and host_url and client_id and client_secret:
            try:
                client = run_coroutine_in_event_loop(AsyncPinionAIClient.create(
                    agent_id=agent_id,
                    host_url=host_url,
                    client_id=client_id,
                    client_secret=client_secret,
                    version=os.environ.get("version", None),
                ))
                client = select_agent_interactively(client, agent_id)
            except (PinionAIConfigurationError, Exception) as e:
                print(f"Failed to initialize PinionAI client from environment: {e}")
                client = None
        
        # If env-based creation failed or env vars are missing, prompt for AIA file
        if client is None:
            if not (agent_id and host_url and client_id and client_secret):
                print("Environment variables (client_id, client_secret, agent_id, host_url) not found.")
            aia_path = input("Enter path to .aia file to load the agent (or leave empty to abort): ").strip()
            if aia_path:
                client = load_agent_from_aia_path(aia_path)
            else:
                print("No .aia file provided. Exiting.")
                return

    var = client.var
    print(var.get("agentTitle"),"PinionAI Terminal Chat")
    print(var.get("agentSubtitle"))
    print("Type your message and press Enter.")
    print("Commands:")
    print("  /add <path> - merge an AIA agent into the current session")
    print("  /merge <name or uid> - merge an available account agent into this session")
    print("  /agents     - list available account agents")
    print("  /end        - end chat session and exit")
    print("  /continue   - continue polling or force refresh")
    
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
            cleanup_client(client)
            break

        if not prompt:
            continue
        
        trimmed_prompt = prompt.strip().lower()
        if trimmed_prompt == "/end":
            run_coroutine_in_event_loop(client.end_grpc_chat_session())
            print("Chat ended.")
            cleanup_client(client)
            break
        if trimmed_prompt == "/continue":
            print("Continuing / refreshing...")
            # show any new messages
            if poll_for_updates(client, timeout=5):
                display_messages(client.get_chat_messages_for_display(), user_img, assistant_img)
            continue

        if trimmed_prompt == "/agents" or trimmed_prompt == "/merge" or trimmed_prompt.startswith("/merge "):
            try:
                agents = run_coroutine_in_event_loop(get_available_agents(client))
                if not agents:
                    print("No agents were returned for this account.")
                    continue
                print("Available agents:")
                for agent in agents:
                    print(f"  {agent['agent_name']} [{agent['uid']}]")
                if trimmed_prompt == "/agents":
                    print("Use /merge <name or uid> to add an agent's capabilities.")
                    continue

                identifier = prompt.strip()[len("/merge"):].strip()
                if not identifier:
                    identifier = input("Agent name or UID to merge: ").strip()
                selected_agent = resolve_agent(agents, identifier)
                if selected_agent is None:
                    print("Agent not found; use /agents to see available agents.")
                    continue
                run_coroutine_in_event_loop(merge_agent_capabilities(
                    client,
                    selected_agent["uid"],
                    host_url=os.environ.get("host_url"),
                    client_id=os.environ.get("client_id"),
                    client_secret=os.environ.get("client_secret"),
                    version=os.environ.get("version", None),
                ))
                print(f"Capabilities from {selected_agent['agent_name']} merged into the current session.")
                var = client.var
                user_img = var.get("userImage")
                assistant_img = var.get("assistImage")
            except Exception as e:
                print(f"Could not merge selected agent: {e}")
            continue
        
        if trimmed_prompt.startswith("/add "):
            aia_path = prompt.strip()[5:].strip()
            if not os.path.exists(aia_path):
                print(f"Error: File not found at '{aia_path}'")
                continue
            try:
                with open(aia_path, "rb") as f:
                    raw = f.read()
                file_text = raw.decode("utf-8")
                
                result_msg = run_coroutine_in_event_loop(client.add_agent_from_aia(
                    file_stream=file_text
                ))

                if result_msg == 'key_secret required for private version':
                    print("This AIA file is private and requires a secret key to decrypt.")
                    key_secret = getpass.getpass("Enter key_secret: ")
                    result_msg = run_coroutine_in_event_loop(client.add_agent_from_aia(
                        file_stream=file_text,
                        key_secret=key_secret
                    ))
                
                if "Error" not in result_msg:
                    print(f"Success: {result_msg}")
                    # Refresh vars as they might have changed
                    var = client.var
                    user_img = var.get("userImage")
                    assistant_img = var.get("assistImage")
                else:
                    print(f"Merge failed: {result_msg}")
            except Exception as e:
                print(f"Error merging AIA file: {e}")
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

                while client.next_intent:
                    follow_up_response = run_coroutine_in_event_loop(client.process_user_input("", sender="user"))
                    print(f"Agent (follow-up): {follow_up_response}")
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