"""Helpers for listing agents available to the configured PinionAI account."""

from pinionai import AsyncPinionAIClient


async def get_available_agents(client):
    """Return valid agent records from the client's agent-list API."""
    response_data = await client.agent_list()
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