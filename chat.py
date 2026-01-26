import streamlit as st
import os
import time
import asyncio
from io import StringIO
from pinionai import AsyncPinionAIClient
from pinionai.exceptions import PinionAIConfigurationError, PinionAIError
import threading
from dotenv import load_dotenv
load_dotenv()

def run_coroutine_in_event_loop(coroutine):
    """Runs a coroutine in the app's persistent event loop."""
    loop = get_event_loop()
    return asyncio.run_coroutine_threadsafe(coroutine, loop).result()

def get_event_loop():
    """Gets or creates the app's persistent event loop."""
    if "event_loop" not in st.session_state:
        st.session_state.event_loop = asyncio.new_event_loop()
        threading.Thread(target=st.session_state.event_loop.run_forever, daemon=True).start()
    return st.session_state.event_loop

def display_chat_messages(messages,user_img,assistant_img):
    """Displays chat messages in the Streamlit app."""
    chat_container = st.container()
    with chat_container:
        for message in messages:
            avatar = user_img if message["role"] == "user" else assistant_img
            with st.chat_message(message["role"], avatar=avatar):
                st.markdown(message["content"])

def poll_for_updates(client: AsyncPinionAIClient, timeout: int, http_poll_start: int = 30, http_poll_interval: int = 5):
    """Polls for updates and returns True if a rerun is needed."""
    start_time = time.time()
    next_http_poll_time = start_time + http_poll_start

    while time.time() - start_time < timeout:
        # Primary check: Has a gRPC message arrived recently?
        if (time.time() - client._grpc_last_update_time) < 2.0:
            return True
        # Fallback check: Poll HTTP endpoint no response in a while.
        now = time.time()
        if now >= next_http_poll_time:
            try:
                lastmodified_server, _ = run_coroutine_in_event_loop(client.get_latest_session_modification_time())
                if lastmodified_server and lastmodified_server != client.last_session_post_modified:
                    return True
                # Schedule the next poll
                next_http_poll_time = now + http_poll_interval
            except Exception as e:
                # Using print instead of st.warning to avoid cluttering the UI
                st.warning(f"Warning: Could not check for session updates: {e}")
                # Don't hammer on failure, schedule next poll
                next_http_poll_time = now + http_poll_interval
        time.sleep(0.1) # Prevent busy-waiting
    return False # Timeout

def ensure_grpc_is_active(client: AsyncPinionAIClient):
    """
    For Live Agent Discussion. Checks if the gRPC client is active 
    and starts it if not. Makes the app fork-safe.
    """
    if not client._grpc_stub:
        try:
            is_started = run_coroutine_in_event_loop(client.start_grpc_client_listener(sender_id="user"))
            if is_started:
                st.info("Connecting to live agent...")
                return True
            else:
                st.error("Could not connect to live agent service.")
                return False
        except Exception as e:
            st.error(f"Failed to start gRPC listener: {e}")
            return False
    return True # Already active

# --- Initialize PinionAIClient ---
st.set_page_config(
    page_title="PinionAI Chat",
    page_icon="assets/favicon.ico",
    menu_items={
        'Get help': 'https://docs.pinionai.com/',
        'Report a bug': 'https://www.pinionai.com/contact',
        'About': 'Use **[PinionAI](https://www.pinionai.com)** as your low-code, opinionated AI Agent Platform. Delivering controlled AI Agents that work seamlessly with existing business infrastructure, and targeting topics you desire, PinionAI performs actions, delivers information using all major models, and offers privacy and security built in. \n\n**PinionAI LLC**, All rights reserved. Version: `0.2.4`'
    },
    layout="wide"
)
# state for handling private AIA files
if 'awaiting_key_secret' not in st.session_state:
    st.session_state.awaiting_key_secret = False
if 'uploaded_file_bytes' not in st.session_state:
    st.session_state.uploaded_file_bytes = None

if not os.environ.get("agent_id"):
    if st.session_state.awaiting_key_secret:
        st.warning("This AIA file is private and requires a secret key to decrypt.")
        with st.form("key_secret_form"):
            key_secret = st.text_input("Enter the secret key:", type="password")
            col1, col2 = st.columns(2)
            with col1:
                if st.form_submit_button("Unlock and Load Agent", use_container_width=True):
                    if not key_secret:
                        st.error("Please enter a secret key.")
                    else:
                        # Clear main session state before loading new agent
                        keys_to_keep = ["logged_in", "user_login", "user_email", "accountSelectedUId", "accountPermissions", "awaiting_key_secret", "uploaded_file_bytes"]
                        keys_to_delete = [key for key in st.session_state.keys() if key not in keys_to_keep]
                        for key in keys_to_delete:
                            del st.session_state[key]
                        with st.spinner("Decrypting and loading agent..."):
                            try:
                                file_bytes = st.session_state.uploaded_file_bytes
                                stringio = StringIO(file_bytes.decode("utf-8"))
                                client, init_message = run_coroutine_in_event_loop(AsyncPinionAIClient.create_from_stream(
                                    file_stream=stringio.read(),
                                    host_url=os.environ.get("host_url"),
                                    key_secret=key_secret
                                ))
                                if client:
                                    st.session_state.pinion_client = client
                                    st.session_state.awaiting_key_secret = False # Clean up temp state on success
                                    st.session_state.uploaded_file_bytes = None
                                    st.success("Agent loaded successfully!")
                                    st.rerun()
                                else:
                                    st.error(f"Failed to load agent: {init_message}")
                                    st.stop()
                            except Exception as e:
                                st.error(f"Failed to load agent with provided key: {e}")
                                st.stop()
            with col2:
                if st.form_submit_button("Cancel", use_container_width=True):
                    # Clean up temp state and go back
                    st.session_state.awaiting_key_secret = False
                    st.session_state.uploaded_file_bytes = None
                    st.rerun()
        st.stop()
    else:
        with st.form(f"agent_file"):
            uploaded_file = st.file_uploader("Upload AIA agent file or shortcut", type="aia", accept_multiple_files=False,
                                            help="Select the File version of the agent to test.")
            if st.form_submit_button("Load AIA Agent", help="Reset the test agent and clear the chat history."):
                if uploaded_file is None:
                    st.error("Please upload an agent file first.")
                    st.stop()
                else: # Session state is cleared before attempting to load
                    # keys_to_keep = ["logged_in", "user_login", "user_email", "accountSelectedUId", "accountPermissions"]
                    keys_to_delete = [key for key in st.session_state.keys()] # if key not in keys_to_keep]
                    for key in keys_to_delete:
                        del st.session_state[key]
                    try:
                        file_bytes = uploaded_file.getvalue()
                        stringio = StringIO(file_bytes.decode("utf-8"))
                        client, init_message = run_coroutine_in_event_loop(AsyncPinionAIClient.create_from_stream(
                            file_stream=stringio.read(),
                            host_url=os.environ.get("host_url")
                            ))
                        if init_message == 'key_secret required for private version':
                            st.session_state.awaiting_key_secret = True
                            st.session_state.uploaded_file_bytes = file_bytes
                            st.rerun()
                        elif client:
                            st.session_state.pinion_client = client
                            st.rerun() # Rerun to load the new agent's chat
                        else:
                            st.error(f"Failed to load agent: {init_message}")
                            st.stop()
                    except Exception as e:
                        st.error(f"Failed to initialize PinionAI client from AIA file: {e}")
                        st.stop()
            elif st.session_state.get("pinion_client") is None:
                st.info("Please upload an AIA file or shortcut.")
                st.stop()
else:                    
    if "pinion_client" not in st.session_state:
            try:
                st.session_state.pinion_client = run_coroutine_in_event_loop(AsyncPinionAIClient.create(
                    agent_id=os.environ.get("agent_id"),
                    host_url=os.environ.get("host_url"),
                    client_id=os.environ.get("client_id"),
                    client_secret=os.environ.get("client_secret"),
                    version=os.environ.get("version", None) # Change to serve specific version (draft, development, test, live, archived). None loads latest in progress.
                ))
                if not st.session_state.pinion_client.chat_messages and st.session_state.pinion_client.var.get("agentStart"):
                    st.session_state.pinion_client.add_message_to_history(
                        "assistant", st.session_state.pinion_client.var["agentStart"]
                    )
            except PinionAIConfigurationError as e: 
                st.error(f"Failed to initialize PinionAI client: {e}")
                st.stop()

if st.session_state.pinion_client:
    client: AsyncPinionAIClient = st.session_state.pinion_client
    var = client.var # Convenience to the client's var dictionary
else:
    st.stop()

if "end_chat_clicked" not in st.session_state:
    st.session_state.end_chat_clicked = False

try:
    assistant_img = var["assistImage"]
    user_img = var["userImage"]
except KeyError as e:
    st.error(f"Error loading image URLs from agent configuration: Missing key {e}. Agent configuration might be incomplete.")
    st.stop()

if st.session_state.end_chat_clicked:
    st.write("Your conversation has ended.")
    st.stop()

# --- UI Layout ---
col1, col2 = st.columns([8, 1])
with col1:
    st.header(var["agentTitle"], divider=var["accentColor"])
with col2:
    st.image(assistant_img)
st.write(var["agentSubtitle"])

if var["transferAllowed"]:
    with st.form(f"chat_status_form_{client.session_id or 'nosession'}"):
        col1, col2 = st.columns(2)
        with col1:
            if st.form_submit_button("Continue"):
                st.rerun()
        with col2:
            if st.form_submit_button("End Chat"):
                st.session_state.end_chat_clicked = "yes"
                run_coroutine_in_event_loop(client.end_grpc_chat_session()) 
                st.rerun()
            
# Start gRPC client listener if transfer is requested and not already started
if client.transfer_requested:
    ensure_grpc_is_active(client)

display_chat_messages(client.get_chat_messages_for_display(), user_img, assistant_img)

# Accept user input
if prompt := st.chat_input("Your message..."): # Placeholder, agentStart will be first message
    client.add_message_to_history("user", prompt)
    with st.chat_message("user", avatar=user_img):
        st.markdown(prompt)

    if client.transfer_requested:  # LIVE AGENT MODE
        if ensure_grpc_is_active(client):
            run_coroutine_in_event_loop(client.update_pinion_session())
            run_coroutine_in_event_loop(client.send_grpc_message(prompt))
            # Poll for a response from the agent before rerunning
            if poll_for_updates(client, timeout=180):
                st.rerun()
            else:
                st.warning("No new messages in the last 3 minutes. Please click Continue or End Chat.")
    else: # AI AGENT MODE
        with st.chat_message("assistant", avatar=assistant_img):
            with st.spinner("Thinking..."):
                full_ai_response_string = run_coroutine_in_event_loop(client.process_user_input(prompt, sender="user"))
                st.markdown(full_ai_response_string)
            run_coroutine_in_event_loop(client.update_pinion_session())
            # Handle if a next_intent was set by the AI's processing
            if client.next_intent:
                with st.chat_message("assistant", avatar=assistant_img):
                    with st.spinner("Thinking..."):
                        # Process the next_intent (user_input might be empty or the next_intent itself)
                        full_ai_response_string = run_coroutine_in_event_loop(client.process_user_input(prompt, sender="user"))
                        st.markdown(full_ai_response_string)
                    run_coroutine_in_event_loop(client.update_pinion_session())       
        if client.transfer_requested:
            # Start gRPC client listener if agent transfer is requested
            if ensure_grpc_is_active(client):
                st.info("Transfer to live agent initiated... Waiting for agent to connect.")
                # Poll for the first message from the agent
                if poll_for_updates(client, timeout=180):
                    st.rerun()
                else:
                    st.warning("No new messages in the last 3 minutes. Please click Continue or End Chat.")
            else:
                st.error("Could not connect to live agent service for transfer.")
        elif client.transfer_requested: # If transfer was already active, and AI responded (e.g. fallback)
            if poll_for_updates(client, timeout=180):
                st.rerun()
            else:
                st.warning("No new messages in the last 3 minutes. Please click Continue or End Chat.")