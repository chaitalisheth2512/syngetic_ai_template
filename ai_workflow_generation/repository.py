from typing import Dict, Any, Optional
import uuid
from datetime import datetime
from app.modules.workflows.repository import workflow_repository
from app.modules.workflows.node_repository import node_repository
from app.modules.workflows.connection_repository import connection_repository
from app.modules.workflows.schemas import WorkflowCreate, NodeItem, ConnectionItem
from app.modules.users.schemas import UserInDB
from app.modules.agents.repository import agent_repository
from app.modules.workspaces.service import workspace_service


class AIWorkflowRepository:
    """Repository for saving AI-generated workflows"""
    
    def save_workflow(
        self,
        workflow_name: str,
        workflow_description: str,
        workflow_data: Dict[str, Any],
        agent_id: Optional[str],
        user: UserInDB
    ) -> str:
        """
        Save an AI-generated workflow to the database
        
        Args:
            workflow_name: Name of the workflow
            workflow_description: Description of the workflow
            workflow_data: Generated workflow data with nodes and connections
            agent_id: Optional agent ID to link the workflow
            user: Current user
            
        Returns:
            Workflow ID
        """
        workflow_id = str(uuid.uuid4())
        
        # Resolve workspace_id
        workspace_id = None
        if agent_id:
            # Get agent to retrieve workspace_id
            agent = agent_repository.get(agent_id)
            if not agent:
                raise ValueError(f"Agent with id {agent_id} not found")
            workspace_id = agent.workspace_id
        
        # If no workspace_id from agent, get user's default workspace
        if not workspace_id:
            workspace = workspace_service.ensure_workspace_exists(user)
            workspace_id = workspace.id
        
        # Get user's display name for owner_name
        owner_name = user.display_name if hasattr(user, 'display_name') else user.user_id
        
        # Set timestamps
        now = datetime.utcnow().isoformat()
        
        # Build workflow document
        workflow_doc = {
            "title": workflow_name,
            "type": "workflow",
            "id": "workflow_" + workflow_id,
            "workflow_id": workflow_id,
            "description": workflow_description,
            "agent_id": agent_id,
            "creator_id": user.user_id,
            "workspace_id": workspace_id,
            "status": True,
            "workflow_socket_id": None,
            "created_at": now,
            "updated_at": now,
            "last_run_date_time": None,
            "owner_name": owner_name,
            "triggers_count": 1,
            "actions_count": 0,
            "last_run_at": None,
            "last_run_status": None
        }
        
        # Create workflow
        workflow_repository.create(workflow_doc)
        
        # Create node ID mapping (old AI-generated IDs to new database IDs)
        node_id_mapping = {}
        
        # Save nodes
        nodes = workflow_data.get("nodes", [])
        for node_data in nodes:
            old_node_id = node_data.get("id")
            
            # Create new node with database structure
            new_node = NodeItem(
                id=f"node_{uuid.uuid4()}",
                workflow_id=workflow_id,
                node_type=node_data.get("nodeType", "entry"),
                position={
                    "x": node_data.get("nodeData", {}).get("x", 0),
                    "y": node_data.get("nodeData", {}).get("y", 0)
                },
                data={
                    "label": node_data.get("label", ""),
                    "pins": node_data.get("pins", {}),
                    "configuration": node_data.get("configuration", {})
                },
                user_id=user.user_id,
                agent_id=agent_id,
                workspace_id=workspace_id
            )
            
            saved_node = node_repository.create(new_node)
            node_id_mapping[old_node_id] = saved_node.id
        
        # Save connections with updated node IDs
        connections = workflow_data.get("connections", [])
        for conn_data in connections:
            source_node_id = node_id_mapping.get(conn_data.get("source_node"))
            dest_node_id = node_id_mapping.get(conn_data.get("destination_node"))
            
            if source_node_id and dest_node_id:
                connection = ConnectionItem(
                    workflow_id=workflow_id,
                    from_node_id=source_node_id,
                    from_pin_id=conn_data.get("source_pin", ""),
                    to_node_id=dest_node_id,
                    to_pin_id=conn_data.get("destination_pin", "")
                )
                connection_repository.create(connection)
        
        # Link workflow to agent if agent_id provided
        if agent_id:
            from app.modules.workflows.service import workflow_service
            workflow_service.link_workflow_to_agent(agent_id, workflow_id)
        
        return workflow_id


# Create singleton instance
ai_workflow_repository = AIWorkflowRepository()

