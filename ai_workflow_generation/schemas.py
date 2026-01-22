from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field


class WorkflowGenerateRequest(BaseModel):
    prompt: str = Field(..., min_length=10, max_length=1500, description="Natural language description of the workflow")
    name: Optional[str] = Field(None, description="Optional workflow name (will be auto-generated if not provided)")
    description: Optional[str] = Field(None, description="Optional workflow description (will be auto-generated if not provided)")
    save: bool = Field(False, description="Whether to save the workflow to database")
    agent_id: Optional[str] = Field(None, description="Agent ID (required if save=true)")


class WorkflowNode(BaseModel):
    id: str
    type: str
    label: str
    nodeType: str
    pins: Dict[str, List[Dict[str, Any]]]
    configuration: Dict[str, Any]
    nodeData: Dict[str, int]


class WorkflowConnection(BaseModel):
    source_node: str
    source_pin: str
    destination_node: str
    destination_pin: str


class WorkflowResponse(BaseModel):
    workflow_name: str
    workflow_description: str
    nodes: List[WorkflowNode]
    connections: List[WorkflowConnection]


class WorkflowGenerateResponse(BaseModel):
    workflow: WorkflowResponse
    status: str
    workflow_id: Optional[str] = None
    message: Optional[str] = None

