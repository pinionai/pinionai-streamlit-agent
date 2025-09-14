import streamlit as st
import os
import time
import asyncio
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
                print(f"Warning: Could not check for session updates: {e}")
                # Don't hammer on failure, schedule next poll
                next_http_poll_time = now + http_poll_interval
        time.sleep(0.1) # Prevent busy-waiting
    return False # Timeout reached

# --- Initialize PinionAIClient ---
if "pinion_client" not in st.session_state:
    st.session_state.version = None  # Change to serve desired version, None loads latest.
    try:
        st.session_state.pinion_client = run_coroutine_in_event_loop(AsyncPinionAIClient.create(
            agent_id=os.environ.get("agent_id_stocks"),
            host_url=os.environ.get("host_url"),
            client_id=os.environ.get("client_id"),
            client_secret=os.environ.get("client_secret"),
            version=st.session_state.version
        ))

        # Initialize the gRPC client once the main client is created.
        run_coroutine_in_event_loop(st.session_state.pinion_client.start_grpc_client_listener(sender_id="user"))
        
        if not st.session_state.pinion_client.chat_messages and st.session_state.pinion_client.var.get("agentStart"):
            st.session_state.pinion_client.add_message_to_history(
                "assistant", st.session_state.pinion_client.var["agentStart"]
            )
    except PinionAIConfigurationError as e: 
        st.error(f"Failed to initialize PinionAI client: {e}")
        st.stop()

client: AsyncPinionAIClient = st.session_state.pinion_client
var = client.var # Convenience to the client's var dictionary

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
if client.transfer_requested and not client._grpc_stub:
    if run_coroutine_in_event_loop(client.start_grpc_client_listener(sender_id="user")): 
        st.info("Connecting to live agent...")
    else:
        st.error("Could not connect to live agent service.")

display_chat_messages(client.get_chat_messages_for_display(), user_img, assistant_img)

# Accept user input
if prompt := st.chat_input("Your message..."): # Placeholder, agentStart will be first message
    client.add_message_to_history("user", prompt)
    with st.chat_message("user", avatar=user_img):
        st.markdown(prompt)

    if client.transfer_requested:  # LIVE AGENT MODE
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
            # The client's process_user_input method already adds the assistant's response to its chat_messages
            run_coroutine_in_event_loop(client.update_pinion_session())
            # Handle if a next_intent was set by the AI's processing
            if client.next_intent:
                with st.chat_message("assistant", avatar=assistant_img):
                    with st.spinner("Thinking..."):
                        # Process the next_intent (user_input might be empty or the next_intent itself)
                        full_ai_response_string = run_coroutine_in_event_loop(client.process_user_input(prompt, sender="user"))
                        st.markdown(full_ai_response_string)
                    run_coroutine_in_event_loop(client.update_pinion_session())       
        if client.transfer_requested and not client._grpc_stub: # If transfer was just requested
            # Start gRPC client listener if transfer is now requested
            if run_coroutine_in_event_loop(client.start_grpc_client_listener(sender_id="user")):
                st.info("Transfer to live agent initiated... Waiting for agent to connect.")
                # Poll for the first message from the agent
                if poll_for_updates(client, timeout=180):
                    st.rerun()
                else:
                    st.warning("No new messages in the last 3 minutes. Please click Continue or End Chat.")
            else:
                st.error("Could not connect to live agent service for transfer.")
        elif client.transfer_requested: # If transfer was already active, and AI responded (e.g. fallback)
            # Poll for a response from the agent before rerunning
            if poll_for_updates(client, timeout=180):
                st.rerun()
            else:
                st.warning("No new messages in the last 3 minutes. Please click Continue or End Chat.")