"""Helpers for listing agents available to the configured PinionAI account."""


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