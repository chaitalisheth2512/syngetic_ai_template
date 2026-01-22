from http import HTTPStatus
from fastapi import APIRouter, HTTPException, Depends
from app.modules.ai_workflow_generation.schemas import (
    WorkflowGenerateRequest,
    WorkflowGenerateResponse
)
from app.modules.ai_workflow_generation.service import ai_workflow_generator
from app.api.deps import get_current_user
from app.modules.users.schemas import UserInDB

router = APIRouter()


@router.post("/generate", response_model=WorkflowGenerateResponse)
async def workflow_ai_generate(
    request: WorkflowGenerateRequest,
    current_user: UserInDB = Depends(get_current_user)
):
    """
    Generate a workflow from a natural language prompt using AI.
    
    **Features:**
    - Automatically selects appropriate node types
    - Creates and connects all necessary pins
    - Generates descriptive workflow name and description
    - Handles LLM JSON output with ToJson node
    - Creates missing pins dynamically
    """
    try:
        # Validate request
        if request.save and not request.agent_id:
            raise HTTPException(
                status_code=HTTPStatus.BAD_REQUEST,
                detail="agent_id is required when save=true"
            )
        
        # Generate workflow using service
        generated_workflow = ai_workflow_generator.generate_workflow(request.prompt)
        
        # Use AI-generated name and description, or fallback to user-provided/default
        workflow_name = request.name or generated_workflow.get('workflow_name', 'AI Generated Workflow')
        workflow_description = request.description or generated_workflow.get('workflow_description', request.prompt[:200] + '...' if len(request.prompt) > 200 else request.prompt)
        
        # Update workflow with final name and description
        generated_workflow['workflow_name'] = workflow_name
        generated_workflow['workflow_description'] = workflow_description
        
        # Prepare response
        response = {
            "workflow": generated_workflow,
            "status": "success"
        }
        
        # Save workflow if requested
        if request.save:
            # Import here to avoid circular dependencies
            from app.modules.ai_workflow_generation.repository import ai_workflow_repository
            workflow_id = ai_workflow_repository.save_workflow(
                workflow_name=workflow_name,
                workflow_description=workflow_description,
                workflow_data=generated_workflow,
                agent_id=request.agent_id,
                user=current_user
            )
            response["workflow_id"] = workflow_id
            response["message"] = "Workflow generated and saved successfully"
        
        return response
        
    except FileNotFoundError as e:
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail=f"Node types directory not found. Please check the node structure path: {str(e)}"
        )
    except Exception as e:
        import traceback
        error_details = str(e)
        traceback.print_exc()
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail=f"AI workflow generation failed: {error_details}"
        )

