import os
import requests
import json
from datetime import date
from datetime import datetime, timezone
from cosmos_interface import user_container, agent_container, cosmos_getbyid, cosmos_getbypartition
from azure.cosmos import CosmosDict
from azure.cosmos.exceptions import CosmosResourceNotFoundError
import uuid
from simpleeval import simple_eval
from typing import Annotated, Optional, TypedDict, List, TypeVar, cast, Callable, Any


def agent_users_get(agent_id: str):
    query = f"""
   SELECT * FROM c WHERE c.type="user" AND ARRAY_CONTAINS(c.agents, "{agent_id}")
    """

    items = user_container.query_items(
        query=query,
        enable_cross_partition_query=True
    )
    serializedItems = []
    for item in items:
        serializedItems.append(item)
    return serializedItems


def agents_get(user_id: str):
    user = user_get(user_id)
    if user is None:
        return None
    if user.get("agents") is None or len(user["agents"]) == 0:
        return []

    agents = ', '.join(f'"agent_{x}"' for x in user["agents"])
    query = f"""
    SELECT * FROM c WHERE (c.id IN ({agents}) or c.creator_id = "{user_id}") and c.type="agent"
    """

    items = agent_container.query_items(
        query=query,
        enable_cross_partition_query=True
    )
    serializedItems = []
    for item in items:
        serializedItems.append(item)
    return serializedItems


def all_users_get():
    query = f"""
    SELECT * FROM c WHERE c.type="user"
    """

    items = user_container.query_items(
        query=query,
        enable_cross_partition_query=True
    )
    serializedItems = []
    for item in items:
        serializedItems.append(item)
    return serializedItems


def user_get(user_id: str):
    try:
        state = cosmos_getbyid(container=user_container, id="user_" + user_id, partition_key=user_id)
        if isinstance(state, CosmosDict):
            return state
    except CosmosResourceNotFoundError:
        return None
    return None


def user_agent_remove(agent_id: str, user_id: str):
    user = user_get(user_id=user_id)
    if user is not None:
        agents = user.get("agents")
        if agents is None:
            agents = []
        agents.remove(agent_id)
        user["agents"] = agents
        patch_operations = [{'op': 'set', 'path': '/agents', 'value': agents}]
        user_container.patch_item(
            item="user_" + user_id,
            partition_key=user_id,
            patch_operations=patch_operations
        )


def user_agent_add(agent_id: str, user_id: str):
    user = user_get(user_id=user_id)
    if user is not None:
        agents = user.get("agents")
        if agents is None:
            agents = []
        if agent_id in agents:
            return
        agents.append(agent_id)
        patch_operations = [{'op': 'set', 'path': '/agents', 'value': agents}]
        user_container.patch_item(
            item="user_" + user_id,
            partition_key=user_id,
            patch_operations=patch_operations
        )


def user_add(email: str, display_name: str):
    user = {
        "id": "user_" + email,
        "type": "user",
        "user_id": email,
        "email": email,
        "display_name": display_name,
        "agents": []
    }
    user_container.upsert_item(user)
    return user

