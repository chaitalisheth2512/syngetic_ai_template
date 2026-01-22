"""
Service for detecting and handling workflow deletion requests from user prompts.
"""
import re
from typing import Dict, List, Any, Optional, Tuple


def detect_deletion_request(prompt: str, existing_nodes: List[Dict], existing_connections: List[Dict]) -> Dict[str, Any]:
    """
    Detect if user wants to delete connections or nodes from the prompt.
    
    Returns:
        {
            "action": "delete_connections" | "delete_nodes" | None,
            "targets": List of connection/node identifiers to delete,
            "original_prompt": The original prompt
        }
    """
    prompt_lower = prompt.lower()
    
    # Patterns for connection deletion
    connection_patterns = [
        r"delete\s+connection(s)?\s+(between|from|to)?",
        r"remove\s+connection(s)?\s+(between|from|to)?",
        r"disconnect\s+(nodes?|connection(s)?)",
        r"break\s+connection(s)?",
        r"unlink\s+(nodes?|connection(s)?)"
    ]
    
    # Patterns for node deletion
    node_patterns = [
        r"delete\s+node(s)?",
        r"remove\s+node(s)?",
        r"delete\s+(the\s+)?(.+?)\s+node",
        r"remove\s+(the\s+)?(.+?)\s+node"
    ]
    
    # Check for connection deletion
    for pattern in connection_patterns:
        if re.search(pattern, prompt_lower):
            # Try to extract node names/labels
            targets = _extract_connection_targets(prompt, existing_nodes, existing_connections)
            return {
                "action": "delete_connections",
                "targets": targets,
                "original_prompt": prompt
            }
    
    # Check for node deletion
    for pattern in node_patterns:
        if re.search(pattern, prompt_lower):
            targets = _extract_node_targets(prompt, existing_nodes)
            return {
                "action": "delete_nodes",
                "targets": targets,
                "original_prompt": prompt
            }
    
    return {
        "action": None,
        "targets": [],
        "original_prompt": prompt
    }


def _extract_connection_targets(prompt: str, nodes: List[Dict], connections: List[Dict]) -> List[Dict]:
    """
    Extract which connections to delete based on node names mentioned in prompt.
    
    Returns list of connection objects to delete.
    """
    prompt_lower = prompt.lower()
    targets = []
    
    # Build node lookup by label/name (more flexible matching)
    node_lookup = {}
    for node in nodes:
        label = node.get("label", "").lower()
        node_id = node.get("id")
        node_type = node.get("nodeType", "").lower()
        
        # Store by full label
        node_lookup[label] = node
        # Store by node type
        node_lookup[node_type] = node
        # Store without parentheses suffix
        if "(" in label:
            clean_label = label.split("(")[0].strip()
            node_lookup[clean_label] = node
        # Store individual words from label
        for word in label.split():
            if len(word) > 3:  # Only meaningful words
                node_lookup[word] = node
    
    # Try to find node pairs mentioned in prompt
    # Pattern: "between X and Y", "from X to Y", "X and Y", "X to Y"
    patterns = [
        r"between\s+([^,\s]+(?:\s+[^,\s]+)*?)\s+and\s+([^,\s]+(?:\s+[^,\s]+)*?)(?:\s|$|\.|,|and)",
        r"from\s+([^,\s]+(?:\s+[^,\s]+)*?)\s+to\s+([^,\s]+(?:\s+[^,\s]+)*?)(?:\s|$|\.|,|and)",
        r"([^,\s]+(?:\s+[^,\s]+)*?)\s+to\s+([^,\s]+(?:\s+[^,\s]+)*?)(?:\s|$|\.|,|and)",
        r"([^,\s]+(?:\s+[^,\s]+)*?)\s+and\s+([^,\s]+(?:\s+[^,\s]+)*?)(?:\s|$|\.|,)"
    ]
    
    found_pairs = []
    for pattern in patterns:
        matches = re.finditer(pattern, prompt_lower)
        for match in matches:
            node1_name = match.group(1).strip()
            node2_name = match.group(2).strip()
            # Clean up common words
            node1_name = re.sub(r'\b(the|a|an|node|nodes)\b', '', node1_name).strip()
            node2_name = re.sub(r'\b(the|a|an|node|nodes)\b', '', node2_name).strip()
            if node1_name and node2_name:
                found_pairs.append((node1_name, node2_name))
    
    # Find connections matching the pairs
    for node1_name, node2_name in found_pairs:
        # Try exact match first
        node1 = node_lookup.get(node1_name)
        node2 = node_lookup.get(node2_name)
        
        # Try partial match if exact match fails
        if not node1:
            for key, node in node_lookup.items():
                if node1_name in key or key in node1_name:
                    node1 = node
                    break
        
        if not node2:
            for key, node in node_lookup.items():
                if node2_name in key or key in node2_name:
                    node2 = node
                    break
        
        if node1 and node2:
            # Find connections between these nodes
            for conn in connections:
                source_id = conn.get("source_node")
                dest_id = conn.get("destination_node")
                
                if (source_id == node1.get("id") and dest_id == node2.get("id")) or \
                   (source_id == node2.get("id") and dest_id == node1.get("id")):
                    if conn not in targets:
                        targets.append(conn)
    
    # If no specific pairs found but user says "delete connections" or "delete all connections"
    if not targets:
        if "all connections" in prompt_lower or "every connection" in prompt_lower or "all the connections" in prompt_lower:
            return connections  # Delete all
        
        # If user says "delete connections" without specifics, check if they mean all
        if ("connection" in prompt_lower and ("delete" in prompt_lower or "remove" in prompt_lower)):
            # Check if it's a general deletion request
            if "delete connections" in prompt_lower or "remove connections" in prompt_lower:
                # If no specific nodes mentioned, delete all
                if not found_pairs:
                    return connections
    
    return targets


def _extract_node_targets(prompt: str, nodes: List[Dict]) -> List[Dict]:
    """
    Extract which nodes to delete based on names/types mentioned in prompt.
    """
    prompt_lower = prompt.lower()
    targets = []
    
    # Build node lookup
    node_lookup = {}
    for node in nodes:
        label = node.get("label", "").lower()
        node_type = node.get("nodeType", "").lower()
        node_lookup[label] = node
        node_lookup[node_type] = node
        if "(" in label:
            clean_label = label.split("(")[0].strip()
            node_lookup[clean_label] = node
    
    # Check if user mentions specific node types or names
    for key, node in node_lookup.items():
        if key in prompt_lower and len(key) > 2:  # Avoid matching single letters
            # Check if it's in a deletion context
            if any(word in prompt_lower for word in ["delete", "remove", "delete the", "remove the"]):
                # Make sure it's not a false positive
                context = prompt_lower[max(0, prompt_lower.find(key) - 20):prompt_lower.find(key) + 20]
                if any(word in context for word in ["delete", "remove"]):
                    if node not in targets:
                        targets.append(node)
    
    # If user says "delete all nodes" or "remove all nodes"
    if "all nodes" in prompt_lower or "every node" in prompt_lower:
        return nodes
    
    return targets


def delete_connections_by_targets(workflow_id: str, connections_to_delete: List[Dict]) -> List[str]:
    """
    Delete connections from workflow.
    
    Returns list of deleted connection IDs.
    """
    import workflow.workflow_service
    deleted_ids = []
    
    for conn in connections_to_delete:
        conn_id = conn.get("id")
        if conn_id:
            try:
                workflow.workflow_service.connection_delete(workflow_id, conn_id)
                deleted_ids.append(conn_id)
            except Exception as e:
                print(f"Error deleting connection {conn_id}: {e}")
    
    return deleted_ids


def create_checklist_response(actions_taken: List[str], workflow_info: Dict[str, Any]) -> Dict[str, Any]:
    """
    Create a checklist/status response similar to n8n AI format.
    
    Args:
        actions_taken: List of actions performed (e.g., ["Categorizing prompt", "Adding nodes", "Connecting nodes"])
        workflow_info: Workflow information
    
    Returns:
        Checklist response dictionary
    """
    checklist_items = []
    
    # Standard checklist items
    standard_items = [
        "Categorizing prompt",
        "Getting best practices",
        "Getting workflow examples",
        "Searching nodes",
        "Getting node details",
        "Adding nodes",
        "Connecting nodes",
        "Updating node parameters",
        "Validating workflow"
    ]
    
    # Mark items as completed based on actions_taken
    for item in standard_items:
        # Check if this item was performed
        item_lower = item.lower()
        completed = any(action.lower() in item_lower or item_lower in action.lower() for action in actions_taken)
        
        checklist_items.append({
            "item": item,
            "completed": completed,
            "icon": "✓" if completed else "○"
        })
    
    return {
        "checklist": checklist_items,
        "workflow_info": workflow_info,
        "summary": f"Workflow {'updated' if workflow_info.get('existing') else 'created'} with {workflow_info.get('node_count', 0)} nodes and {workflow_info.get('connection_count', 0)} connections."
    }

