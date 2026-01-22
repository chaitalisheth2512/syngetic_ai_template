"""
Service for detecting nodes that need configuration and tracking workflow changes.
"""
from typing import Dict, List, Any, Optional, Tuple
import workflow.workflow_service


def detect_configuration_needs(workflow_id: str, nodes: List[Dict]) -> List[Dict[str, Any]]:
    """
    Return all nodes as configuration warnings so users can click to configure any node.
    This allows users to open any node's configuration panel by clicking on it.
    
    Returns list of all nodes with details for configuration.
    """
    configuration_warnings = []
    
    # Get node type definitions to get node type names
    node_types = workflow.workflow_service.load_node_info()
    node_type_map = {nt["id"]: nt for nt in node_types}
    
    for node in nodes:
        node_id = node.get("id")
        node_type_id = node.get("nodeType", "")
        node_label = node.get("label", "")
        
        if not node_id or not node_type_id:
            continue
        
        # Get node type name
        node_type_def = node_type_map.get(node_type_id, {})
        node_type_name = node_type_def.get("name", node_type_id)
        
        # Create warning message for this node
        display_name = node_label or node_type_name
        warning_message = f"{display_name}: Click to configure this node"
        
        # Add all nodes as configuration warnings
        configuration_warnings.append({
            "node_id": node_id,
            "node_label": display_name,
            "node_type": node_type_id,
            "warning_message": warning_message,
            "missing_fields": [],  # Not checking for missing fields
            "setup_instructions": []  # No specific setup instructions
        })
    
    return configuration_warnings


def track_workflow_changes(
    existing_nodes: List[Dict],
    existing_connections: List[Dict],
    new_nodes: List[Dict],
    new_connections: List[Dict],
    prompt: str
) -> Dict[str, Any]:
    """
    Track what changed in the workflow (nodes added/removed/modified, connections added/removed).
    Uses node labels and types for comparison since IDs change after saving.
    
    Returns a "What's changed" summary.
    """
    changes = {
        "nodes_added": [],
        "nodes_removed": [],
        "nodes_modified": [],
        "connections_added": [],
        "connections_removed": []
    }
    
    # Build lookup maps by label+type (since IDs change after saving)
    existing_node_signatures = {}
    for node in existing_nodes:
        label = node.get("label", "").strip()
        node_type = node.get("nodeType", "")
        # Create signature from label and type
        signature = f"{label}|{node_type}" if label else f"|{node_type}"
        existing_node_signatures[signature] = node
    
    new_node_signatures = {}
    new_node_by_id = {}
    for node in new_nodes:
        label = node.get("label", "").strip()
        node_type = node.get("nodeType", "")
        signature = f"{label}|{node_type}" if label else f"|{node_type}"
        new_node_signatures[signature] = node
        new_node_by_id[node.get("id")] = node
    
    existing_node_by_id = {node.get("id"): node for node in existing_nodes}
    
    # Find added nodes (in new but not in existing by signature)
    for node in new_nodes:
        label = node.get("label", "").strip()
        node_type = node.get("nodeType", "")
        signature = f"{label}|{node_type}" if label else f"|{node_type}"
        
        if signature not in existing_node_signatures:
            changes["nodes_added"].append({
                "label": label or node_type,
                "type": node_type,
                "node_id": node.get("id")
            })
    
    # Find removed nodes (in existing but not in new by signature)
    for node in existing_nodes:
        label = node.get("label", "").strip()
        node_type = node.get("nodeType", "")
        signature = f"{label}|{node_type}" if label else f"|{node_type}"
        
        if signature not in new_node_signatures:
            changes["nodes_removed"].append({
                "label": label or node_type,
                "type": node_type,
                "node_id": node.get("id")
            })
    
    # Track connection changes (compare by node labels/positions since IDs change)
    # Build connection signatures using node positions/order
    def build_connection_signature(conn, node_lookup):
        """Build a signature for a connection using node labels/types"""
        source_node = node_lookup.get(conn.get("source_node"), {})
        dest_node = node_lookup.get(conn.get("destination_node"), {})
        source_label = source_node.get("label", "").strip() or source_node.get("nodeType", "")
        dest_label = dest_node.get("label", "").strip() or dest_node.get("nodeType", "")
        source_pin = conn.get("source_pin", "")
        dest_pin = conn.get("destination_pin", "")
        return f"{source_label}->{dest_label}|{source_pin}->{dest_pin}"
    
    existing_conn_signatures = {
        build_connection_signature(conn, existing_node_by_id): conn
        for conn in existing_connections
    }
    
    new_conn_signatures = {
        build_connection_signature(conn, new_node_by_id): conn
        for conn in new_connections
    }
    
    # Find added connections
    added_conn_sigs = set(new_conn_signatures.keys()) - set(existing_conn_signatures.keys())
    for sig in added_conn_sigs:
        conn = new_conn_signatures[sig]
        source_node = new_node_by_id.get(conn.get("source_node"), {})
        dest_node = new_node_by_id.get(conn.get("destination_node"), {})
        changes["connections_added"].append({
            "from": source_node.get("label", "") or source_node.get("nodeType", "Unknown"),
            "to": dest_node.get("label", "") or dest_node.get("nodeType", "Unknown")
        })
    
    # Find removed connections
    removed_conn_sigs = set(existing_conn_signatures.keys()) - set(new_conn_signatures.keys())
    for sig in removed_conn_sigs:
        conn = existing_conn_signatures[sig]
        source_node = existing_node_by_id.get(conn.get("source_node"), {})
        dest_node = existing_node_by_id.get(conn.get("destination_node"), {})
        changes["connections_removed"].append({
            "from": source_node.get("label", "") or source_node.get("nodeType", "Unknown"),
            "to": dest_node.get("label", "") or dest_node.get("nodeType", "Unknown")
        })
    
    return changes


def generate_whats_changed_summary(changes: Dict[str, Any]) -> List[str]:
    """
    Generate a human-readable "What's changed" summary from changes dict.
    """
    summary = []
    
    if changes["nodes_added"]:
        for node in changes["nodes_added"]:
            summary.append(f"Added the {node['label']} node")
    
    if changes["nodes_removed"]:
        for node in changes["nodes_removed"]:
            summary.append(f"Removed the {node['label']} node")
    
    if changes["nodes_modified"]:
        for node in changes["nodes_modified"]:
            summary.append(f"Updated the {node['label']} node configuration")
    
    if changes["connections_added"]:
        for conn in changes["connections_added"]:
            summary.append(f"Connected {conn['from']} to {conn['to']}")
    
    if changes["connections_removed"]:
        for conn in changes["connections_removed"]:
            summary.append(f"Removed connection from {conn['from']} to {conn['to']}")
    
    return summary


def generate_setup_instructions(workflow_id: str, nodes: List[Dict]) -> List[str]:
    """
    Generate setup instructions based on nodes in the workflow.
    """
    instructions = []
    
    # Check for MailtrapEmail nodes
    mailtrap_nodes = [n for n in nodes if n.get("nodeType") == "MailtrapEmail"]
    if mailtrap_nodes:
        instructions.append("Configure Mailtrap SMTP credentials in the 'Send Email (Mailtrap)' node:")
        instructions.append("- From Email: Your verified sender email address in Mailtrap")
        instructions.append("- SMTP Username: Your Mailtrap SMTP username")
        instructions.append("- SMTP Password: Your Mailtrap SMTP password")
    
    # Check for form/parameter nodes that might have URLs
    parameter_nodes = [n for n in nodes if n.get("nodeType") == "Parameter"]
    if parameter_nodes:
        instructions.append("Share the form URL with users - you can find it in the Parameter node after activating the workflow")
    
    return instructions

