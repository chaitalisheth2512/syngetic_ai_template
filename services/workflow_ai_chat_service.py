"""
Service for managing workflow AI chat conversations.
Handles storing and retrieving workflow-specific conversation history.
"""
import uuid
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional
from cosmos_interface import conversation_container, cosmos_getbypartition


def workflow_conversation_add(user_id: str, agent_id: str, workflow_id: str, conversation: Dict[str, Any] = None) -> Dict[str, Any]:
    """
    Create a new workflow conversation or get existing one.
    
    Args:
        user_id: User email/ID
        agent_id: Agent ID
        workflow_id: Workflow ID
        conversation: Optional conversation data
    
    Returns:
        Conversation object
    """
    if conversation is None:
        conversation = {}
    
    # Check if conversation already exists for this workflow
    existing = workflow_conversation_get(user_id, agent_id, workflow_id)
    if existing:
        return existing
    
    # Create new conversation
    conversation_id = str(uuid.uuid4())
    conversation["user_id"] = user_id
    conversation["type"] = "workflow_conversation"
    conversation["agent_id"] = agent_id
    conversation["workflow_id"] = workflow_id
    conversation["id"] = f"workflow_conversation_{conversation_id}"
    conversation["conversation_id"] = conversation_id
    conversation["summary"] = f"Workflow AI Chat"
    conversation["created_at"] = datetime.now(timezone.utc).timestamp()
    conversation["updated_at"] = datetime.now(timezone.utc).timestamp()
    
    conversation_container.upsert_item(conversation)
    return conversation


def workflow_conversation_get(user_id: str, agent_id: str, workflow_id: str, include_messages: bool = True) -> Optional[Dict[str, Any]]:
    """
    Get workflow conversation with optional messages.
    
    Args:
        user_id: User email/ID
        agent_id: Agent ID
        workflow_id: Workflow ID
        include_messages: Whether to include message history
    
    Returns:
        Conversation object or None
    """
    query = """
    SELECT * FROM c 
    WHERE c.type='workflow_conversation' 
    AND c.user_id = @user_id 
    AND c.agent_id = @agent_id 
    AND c.workflow_id = @workflow_id
    """
    
    parameters = [
        {"name": "@user_id", "value": user_id},
        {"name": "@agent_id", "value": agent_id},
        {"name": "@workflow_id", "value": workflow_id}
    ]
    
    items = list(conversation_container.query_items(
        query=query,
        parameters=parameters,
        enable_cross_partition_query=True
    ))
    
    if not items:
        return None
    
    conversation = items[0]
    
    if include_messages:
        conversation_id = conversation.get("conversation_id")
        if conversation_id:
            messages = cosmos_getbypartition(conversation_container, conversation_id, "workflow_message")
            # Sort by created_at
            messages.sort(key=lambda x: x.get("created_at", 0))
            conversation["messages"] = messages
    
    return conversation


def workflow_message_add(conversation_id: str, message: Dict[str, Any]) -> Dict[str, Any]:
    """
    Add a message to workflow conversation.
    
    Args:
        conversation_id: Conversation ID
        message: Message object with role and content
    
    Returns:
        Created message object
    """
    message["type"] = "workflow_message"
    message["id"] = f"workflow_message_{uuid.uuid4()}"
    message["conversation_id"] = conversation_id
    message["created_at"] = datetime.now(timezone.utc).timestamp()
    
    conversation_container.upsert_item(message)
    
    # Update conversation updated_at
    try:
        patch_operations = [
            {'op': 'set', 'path': '/updated_at', 'value': datetime.now(timezone.utc).timestamp()}
        ]
        conversation_container.patch_item(
            item=f"workflow_conversation_{conversation_id}",
            partition_key=conversation_id,
            patch_operations=patch_operations
        )
    except Exception:
        pass  # Ignore if conversation doesn't exist yet
    
    return message


def workflow_conversation_get_history(user_id: str, agent_id: str, workflow_id: str) -> List[Dict[str, Any]]:
    """
    Get conversation history formatted for LLM context.
    
    Args:
        user_id: User email/ID
        agent_id: Agent ID
        workflow_id: Workflow ID
    
    Returns:
        List of messages formatted for LLM
    """
    conversation = workflow_conversation_get(user_id, agent_id, workflow_id, include_messages=True)
    
    if not conversation or not conversation.get("messages"):
        return []
    
    # Format messages for LLM (role and content only)
    history = []
    for msg in conversation["messages"]:
        history.append({
            "role": msg.get("role", "user"),
            "content": msg.get("content", "")
        })
    
    return history


def workflow_conversations_get_by_workflow(user_id: str, workflow_id: str) -> List[Dict[str, Any]]:
    """
    Get all conversations for a workflow (for history display).
    
    Args:
        user_id: User email/ID
        workflow_id: Workflow ID
    
    Returns:
        List of conversations
    """
    query = """
    SELECT * FROM c 
    WHERE c.type='workflow_conversation' 
    AND c.user_id = @user_id 
    AND c.workflow_id = @workflow_id
    ORDER BY c.updated_at DESC
    """
    
    parameters = [
        {"name": "@user_id", "value": user_id},
        {"name": "@workflow_id", "value": workflow_id}
    ]
    
    items = list(conversation_container.query_items(
        query=query,
        parameters=parameters,
        enable_cross_partition_query=True
    ))
    
    return items


def workflow_conversations_delete_all(workflow_id: str) -> int:
    """
    Delete all conversations and messages for a workflow.
    This should be called when a workflow is deleted.
    
    Args:
        workflow_id: Workflow ID
    
    Returns:
        Number of conversations deleted
    """
    # Find all conversations for this workflow (across all users/agents)
    query = """
    SELECT * FROM c 
    WHERE c.type='workflow_conversation' 
    AND c.workflow_id = @workflow_id
    """
    
    parameters = [
        {"name": "@workflow_id", "value": workflow_id}
    ]
    
    conversations = list(conversation_container.query_items(
        query=query,
        parameters=parameters,
        enable_cross_partition_query=True
    ))
    
    deleted_count = 0
    
    # Delete each conversation and its messages
    for conversation in conversations:
        conversation_id = conversation.get("conversation_id")
        if conversation_id:
            # Delete all messages for this conversation
            messages = cosmos_getbypartition(conversation_container, conversation_id, "workflow_message")
            for message in messages:
                try:
                    message_id = message.get("id")
                    if message_id:
                        conversation_container.delete_item(
                            item=message_id,
                            partition_key=conversation_id
                        )
                except Exception as e:
                    print(f"Error deleting message {message.get('id')}: {e}")
            
            # Delete the conversation itself
            try:
                conversation_item_id = conversation.get("id")
                if conversation_item_id:
                    conversation_container.delete_item(
                        item=conversation_item_id,
                        partition_key=conversation_id
                    )
                    deleted_count += 1
            except Exception as e:
                print(f"Error deleting conversation {conversation.get('id')}: {e}")
    
    return deleted_count

