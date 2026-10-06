"""Helpers for listing agents available to the configured PinionAI account."""

import os

from pinionai import AsyncPinionAIClient


async def get_available_agents(client):
    """Return valid agent records using account credentials when available."""
    agent_id = os.environ.get("agent_id")
    host_url = os.environ.get("host_url")
    client_id = os.environ.get("client_id")
    client_secret = os.environ.get("client_secret")
    if not all((agent_id, host_url, client_id, client_secret)):
        raise ValueError(
            "Listing account agents requires agent_id, host_url, client_id, and client_secret."
        )

    directory_client = client
    close_directory_client = False
    if (
        getattr(client, "_client_id", None) != client_id
        or getattr(client, "_client_secret", None) != client_secret
    ):
        directory_client = await AsyncPinionAIClient.create(
            agent_id=agent_id,
            host_url=host_url,
            client_id=client_id,
            client_secret=client_secret,
            version=os.environ.get("version", None),
        )
        close_directory_client = True

    try:
        response_data = await directory_client.agent_list()
    finally:
        if close_directory_client:
            await directory_client.close()

    if not isinstance(response_data, dict) or not isinstance(response_data.get("data"), list):
        raise ValueError("Unexpected response format when getting the agent list.")
    if response_data.get("success") is False:
        raise ValueError("The agent-list request was unsuccessful.")

    return [
        agent
        for agent in response_data["data"]
        if isinstance(agent, dict) and agent.get("uid") and agent.get("agent_name")
    ]


async def merge_agent_capabilities(
    client,
    agent_id,
    *,
    host_url,
    client_id,
    client_secret,
    version=None,
):
    """Merge another account agent's version capabilities into an active client."""
    source_client = await AsyncPinionAIClient.create(
        agent_id=agent_id,
        host_url=host_url,
        client_id=client_id,
        client_secret=client_secret,
        version=version,
    )
    try:
        version_data = await source_client.get_pinionai_version_info()
        if not version_data:
            raise ValueError("The selected agent did not return version information.")
        return await client.merge_new_agent(version_data)
    finally:
        await source_client.close()


def resolve_agent(agents, identifier):
    """Find an agent by UID or case-insensitive name."""
    normalized_identifier = identifier.strip().casefold()
    return next(
        (
            agent
            for agent in agents
            if agent["uid"] == identifier.strip()
            or agent["agent_name"].casefold() == normalized_identifier
        ),
        None,
    )