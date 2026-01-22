from openai import AzureOpenAI
from flask import Flask, Blueprint, request, jsonify, g, Response
from flask_cors import CORS
from semantic_kernel.functions.kernel_function_decorator import kernel_function
from semantic_kernel.kernel import Kernel
from typing import Annotated, Optional, TypedDict, List, TypeVar, cast, Callable
from azure.cosmos import CosmosClient, PartitionKey
import requests
from datetime import date
from cachetools import TTLCache
from jinja2 import Template, TemplateSyntaxError
from functools import wraps
import os
import re
import json
from services.chat_service import openai_query, openai_query_withworkflows, conversations_get, conversation_add, \
    message_add, conversation_get
from services.workflow_ai_chat_service import workflow_conversation_add, workflow_conversation_get, \
    workflow_message_add, workflow_conversation_get_history, workflow_conversations_get_by_workflow
from services.ai_workflow_service import AIWorkflowGenerator
from services.workflow_deletion_service import detect_deletion_request, delete_connections_by_targets, create_checklist_response
from services.workflow_configuration_service import detect_configuration_needs, track_workflow_changes, generate_whats_changed_summary, generate_setup_instructions
from services.user_service import agent_users_get, all_users_get, user_agent_add, user_agent_remove, agents_get
from services.file_service import agent_file_add, agent_file_get, agent_file_update, agent_files_get, agent_file_delete
from services.blob_storage_service import upload_file_to_blob, generate_sas_url
import uuid
import mimetypes

import workflow.workflow_service
import sys

agent_bp = Blueprint('agent', __name__)

# OpenAI configuration for error message generation
# Model name - should match your Azure OpenAI deployment name
# Can be overridden via OPENAI_MODEL environment variable
OPENAI_MODEL = os.environ.get('OPENAI_MODEL', 'gpt-4.1')
OPENAI_ENDPOINT = 'https://cynthetixopenai.openai.azure.com/'
OPENAI_API_KEY = os.environ.get('CYNTHETIX_OPENAI_API_KEY')
OPENAI_API_VERSION = '2025-03-01-preview'


def generate_error_message_with_openai(
        exception: Exception,
        workflow_id: str,
        agent_id: str = None,
        state_id: str = None,
        parameters: dict = None,
        context: str = "workflow debug execution"
) -> dict:
    """
    Use OpenAI to generate user-friendly error messages based on the error,
    workflow context, and debug state.
    Returns a dict with 'message' and 'details' keys.
    """
    try:
        # Get workflow information
        workflow_info = None
        workflow_name = "the workflow"
        workflow_description = ""
        nodes_info = []

        try:
            workflow = workflow.workflow_service.workflow_get(workflow_id)
            if workflow:
                workflow_name = workflow.get("name", "the workflow")
                workflow_description = workflow.get("description", "")

            # Get nodes information (limited to avoid too much context)
            nodes = workflow.workflow_service.nodes_get(workflow_id)
            if nodes:
                nodes_info = [
                    {
                        "id": node.get("id", ""),
                        "label": node.get("label", ""),
                        "type": node.get("nodeType", "")
                    }
                    for node in nodes[:10]  # Limit to first 10 nodes
                ]
        except Exception:
            pass  # If we can't get workflow info, continue without it

        # Get debug state if available
        debug_state = None
        if state_id:
            try:
                debug_state = workflow.workflow_service.state_get(workflow_id=workflow_id, state_id=state_id)
            except Exception:
                pass

        # Prepare context for OpenAI
        error_message = str(exception)
        error_type = type(exception).__name__
        error_str_lower = error_message.lower()

        # Pre-classify error type to help OpenAI
        is_likely_system_error = (
                "nonetype" in error_str_lower or
                "attributeerror" in error_type.lower() or
                "typeerror" in error_type.lower() or
                "keyerror" in error_type.lower() or
                "indexerror" in error_type.lower() or
                "does not support" in error_str_lower or
                "object has no attribute" in error_str_lower or
                "object does not support" in error_str_lower
        )

        is_likely_user_error = (
                "not found" in error_str_lower or
                "does not exist" in error_str_lower or
                "missing" in error_str_lower or
                "required" in error_str_lower or
                "invalid" in error_str_lower or
                "malformed" in error_str_lower
        )

        error_category = "SYSTEM_ERROR" if is_likely_system_error else (
            "USER_CONFIGURATION_ERROR" if is_likely_user_error else "UNKNOWN")

        # Build prompt for OpenAI
        prompt = f"""You are a helpful assistant that generates user-friendly error messages for workflow execution failures.

Context:
- Workflow Name: {workflow_name}
- Workflow Description: {workflow_description}
- Error Type: {error_type}
- Error Message: {error_message}
- Error Category: {error_category}
- Context: {context}
"""

        if parameters:
            prompt += f"- Parameters Provided: {json.dumps(parameters)}\n"

        if debug_state:
            prompt += f"- Debug State: Currently executing step with state_id {state_id}\n"

        if nodes_info:
            prompt += f"- Workflow Nodes: {json.dumps(nodes_info[:5])}\n"  # Limit nodes in prompt

        prompt += """
IMPORTANT: Analyze the error and determine if it's a USER-CONFIGURABLE error or a SYSTEM error.

USER-CONFIGURABLE ERRORS (user can fix):
- Missing required parameters in the request
- Invalid parameter values or data types
- Workflow configuration issues (missing nodes, invalid connections, incomplete setup)
- Invalid workflow_id, agent_id, or state_id
- Invalid data format in request body
- Missing required fields in workflow nodes

SYSTEM ERRORS (internal system issue, user cannot fix):
- NoneType errors (object is None when it shouldn't be)
- AttributeError (object doesn't have expected attribute)
- Internal code errors
- Database connection issues
- System resource issues

For USER-CONFIGURABLE errors:
- Explain what's wrong with their configuration/request
- Tell them exactly what to fix (which parameters, which nodes, etc.)
- Be specific about what's missing or invalid

For SYSTEM errors:
- Tell them it's a system issue
- Mention they should contact support or try again later
- Do NOT show technical error details

Generate a user-friendly error response in JSON format with two fields:
1. "message": A brief, clear message (1-2 sentences) explaining what went wrong. For system errors, mention it's a system issue. For user errors, explain what they need to fix.
2. "details": More detailed explanation (2-3 sentences). For user errors, be specific about what to fix. For system errors, suggest contacting support.

Examples:
User error: "Required parameters are missing from your request. Please provide all required workflow parameters in the request body."
System error: "A system error occurred while processing your workflow. Please try again later or contact support if the issue persists."

Return ONLY valid JSON in this format:
{
    "message": "...",
    "details": "..."
}
"""

        # Call OpenAI
        client = AzureOpenAI(
            api_version=OPENAI_API_VERSION,
            azure_endpoint=OPENAI_ENDPOINT,
            api_key=OPENAI_API_KEY
        )

        # Use chat completion API
        response = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": "You are a helpful assistant that generates clear, user-friendly error messages for API users. Always respond with valid JSON only."
                },
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            temperature=0.3,
            max_tokens=300
        )

        # Parse response
        response_text = response.choices[0].message.content.strip()

        # Try to extract JSON from response (in case it's wrapped in markdown)
        if "```json" in response_text:
            response_text = response_text.split("```json")[1].split("```")[0].strip()
        elif "```" in response_text:
            response_text = response_text.split("```")[1].split("```")[0].strip()

        error_response = json.loads(response_text)

        return {
            "message": error_response.get("message", f"An error occurred during {context}."),
            "details": error_response.get("details",
                                          f"The workflow execution failed. Please check your request and try again.")
        }

    except Exception as openai_error:
        # Fallback to simple user-friendly message if OpenAI fails
        error_str = str(exception).lower()
        error_type = type(exception).__name__.lower()

        # Classify as user-configurable or system error
        is_system_error = (
                "nonetype" in error_str or
                "attributeerror" in error_type or
                "typeerror" in error_type or
                "keyerror" in error_type or
                "indexerror" in error_type or
                "does not support" in error_str or
                "object has no attribute" in error_str
        )

        if is_system_error:
            return {
                "message": "A system error occurred while processing your workflow. Please try again later or contact support if the issue persists.",
                "details": "An internal system error occurred during workflow execution. This is not related to your request or workflow configuration. Please try again in a few moments, or contact support if the problem continues."
            }

        # User-configurable errors
        if "not found" in error_str or "does not exist" in error_str:
            return {
                "message": "The requested resource could not be found. Please verify that all IDs in your request are correct.",
                "details": "The workflow or related resource you're trying to access does not exist. Please check the workflow_id, agent_id, and state_id parameters and ensure they match existing resources."
            }
        elif "missing" in error_str or "required" in error_str:
            return {
                "message": "Required information is missing from your request. Please check that all required fields are provided.",
                "details": "Your request is missing some required information. Please review your request and ensure all necessary parameters and data are included."
            }
        elif "invalid" in error_str:
            return {
                "message": "The request data format is invalid. Please check that your request body is properly formatted.",
                "details": "The data you provided could not be processed. Please ensure your request contains valid data in the correct format."
            }
        else:
            # Default: assume it might be a configuration issue
            return {
                "message": "The workflow execution failed due to a configuration issue. Please check your workflow setup and request parameters.",
                "details": "There was an issue with the workflow configuration or the data provided. Please verify that all workflow nodes are properly configured, all required parameters are provided, and the workflow connections are valid."
            }


def format_workflow_error(exception: Exception, context: str = "workflow execution") -> dict:
    """
    Convert technical exceptions into user-friendly error messages.
    Returns a dict with 'message' and 'details' keys.
    """
    error_str = str(exception).lower()
    error_type = type(exception).__name__

    # Common error patterns and user-friendly messages
    if "not found" in error_str or "does not exist" in error_str or "cosmosresourcenotfounderror" in error_type.lower():
        if "workflow" in error_str or "workflow_id" in error_str:
            return {
                "message": "The specified workflow could not be found. Please verify that the workflow ID is correct and that the workflow exists.",
                "details": "The workflow you are trying to debug does not exist or has been deleted. Please check the workflow_id in your request and ensure it matches an existing workflow."
            }
        elif "state" in error_str or "state_id" in error_str:
            return {
                "message": "The specified debug state could not be found. The state may have expired or been invalidated.",
                "details": "The debug state you are trying to continue from does not exist. Please start a new debug session or use a valid state_id."
            }
        elif "agent" in error_str or "agent_id" in error_str:
            return {
                "message": "The specified agent could not be found. Please verify that the agent ID is correct.",
                "details": "The agent you are trying to use does not exist or has been deleted. Please check the agent_id parameter and ensure it matches an existing agent."
            }
        else:
            return {
                "message": "A required resource could not be found. Please verify all IDs in your request are correct.",
                "details": f"A resource required for {context} was not found. Please check that all workflow, agent, and state IDs are valid and exist in the system."
            }

    elif "missing" in error_str or "required" in error_str or "not provided" in error_str:
        if "parameter" in error_str:
            return {
                "message": "Required parameters are missing from your request. Please provide all required workflow parameters.",
                "details": f"Your workflow requires certain parameters to run, but they were not provided in the request. Please include all required parameters in the request body. The error indicates: {str(exception)}"
            }
        else:
            return {
                "message": "Required information is missing from your request. Please check that all required fields are provided.",
                "details": f"Some required information is missing. Please review your request and ensure all necessary data is included. The error indicates: {str(exception)}"
            }

    elif "invalid" in error_str or "malformed" in error_str or "json" in error_str:
        return {
            "message": "The request data format is invalid. Please check that your request body is properly formatted JSON.",
            "details": f"The data you provided could not be processed. Please ensure your request body contains valid JSON and all required fields are in the correct format. Error: {str(exception)}"
        }

    elif "timeout" in error_str or "timed out" in error_str:
        return {
            "message": "The workflow execution took too long and timed out. The workflow may be too complex or waiting for external resources.",
            "details": f"The workflow execution exceeded the maximum allowed time. This may happen if the workflow is processing large amounts of data or waiting for external services. Please try simplifying the workflow or check external service availability."
        }

    elif "permission" in error_str or "unauthorized" in error_str or "forbidden" in error_str:
        return {
            "message": "You do not have permission to execute this workflow. Please check your access rights.",
            "details": f"You do not have the necessary permissions to execute this workflow. Please contact your administrator or verify that you have access to the specified agent and workflow."
        }

    elif "connection" in error_str or "network" in error_str:
        return {
            "message": "A network or connection error occurred. Please check your connection and try again.",
            "details": f"The workflow could not complete due to a connection issue. This may be a temporary problem. Please try again in a moment."
        }

    elif "attributeerror" in error_type.lower() or "'nonetype' has no attribute" in error_str:
        return {
            "message": "The workflow configuration is incomplete or invalid. Some required workflow components are missing.",
            "details": f"The workflow is missing required configuration or components. Please check that all workflow nodes are properly configured and connected. The error suggests: {str(exception)}"
        }

    elif "keyerror" in error_type.lower() or "key" in error_str:
        return {
            "message": "The workflow is missing required configuration data. Please check your workflow setup.",
            "details": f"A required configuration value is missing from the workflow. Please review your workflow configuration and ensure all required fields are set. The error indicates: {str(exception)}"
        }

    elif "typeerror" in error_type.lower() or "type" in error_str:
        return {
            "message": "The data types in your request do not match what the workflow expects. Please check your input data format.",
            "details": f"The workflow received data in an unexpected format. Please verify that all parameter values match the expected data types (string, number, object, etc.). Error: {str(exception)}"
        }

    elif "valueerror" in error_type.lower():
        return {
            "message": "One or more values in your request are invalid. Please check your input data.",
            "details": f"Some values provided in your request are not valid. Please review your parameters and ensure they contain valid data. Error: {str(exception)}"
        }

    # Default user-friendly message for unknown errors
    else:
        # Extract a clean error message without technical details
        clean_error = str(exception)
        # Remove common technical prefixes
        if ":" in clean_error:
            clean_error = clean_error.split(":", 1)[-1].strip()

        return {
            "message": f"An error occurred during {context}. {clean_error}",
            "details": f"The workflow execution failed. {clean_error} Please check your request data and workflow configuration, and try again. If the problem persists, please verify that all required parameters are provided and the workflow is properly configured."
        }


@agent_bp.route('/agent/<agent_id>/chat', methods=['POST'])
def openai_query_route(agent_id: str) -> Response:
    user_id = request.headers.get("x-user-id")
    user_email = request.headers.get('x-user-email')
    if user_email is None:
        return jsonify({"error": "User is not authenticated"})

    # Allowed file extensions for attachments
    ALLOWED_EXTENSIONS = {'.pdf', '.jpg', '.jpeg', '.png', '.gif', '.doc', '.docx', '.xls', '.xlsx', '.csv'}
    MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB

    # Handle JSON requests (backward compatibility - no file checking)
    if request.is_json:
        request_obj = request.get_json()
        body = request_obj["body"]
        conversation_id = request_obj.get("conversation_id")
        useWorkflows = request_obj.get("useWorkflows") == None or request_obj.get("useWorkflows") == True
        debug = request.args.get("debug")
        response = openai_query_withworkflows(user_email, agent_id, body, conversation_id, debug,
                                              useWorkflows=useWorkflows)
        return jsonify(response)

    # Handle form-data requests (all fields from form-data, check for attachments)
    if request.form:
        # Extract conversation_id from form-data
        conversation_id = request.form.get('conversation_id')

        # Extract body from form-data
        body = {}
        body_json = request.form.get('body')
        if body_json:
            try:
                body = json.loads(body_json)
            except json.JSONDecodeError:
                return jsonify({"error": "Invalid JSON in 'body' field"}), 400

        # If body not provided as JSON, try to reconstruct from form fields
        if not body:
            # Extract previous_response_id
            previous_response_id = request.form.get('previous_response_id')
            if previous_response_id:
                body["previous_response_id"] = previous_response_id

            # Extract input array
            input_array = []
            # Try to get input as JSON string first
            input_json = request.form.get('input')
            if input_json:
                try:
                    input_array = json.loads(input_json)
                except json.JSONDecodeError:
                    pass

            # If not JSON, try to reconstruct from indexed form fields
            if not input_array:
                index = 0
                while True:
                    role_key = f'input[{index}][role]'
                    if role_key not in request.form:
                        break
                    input_item = {
                        "role": request.form.get(role_key)
                    }
                    content_key = f'input[{index}][content]'
                    if content_key in request.form:
                        input_item["content"] = request.form.get(content_key)
                    input_array.append(input_item)
                    index += 1

            if input_array:
                body["input"] = input_array

        # Validate body structure
        if "input" not in body or not isinstance(body["input"], list) or len(body["input"]) == 0:
            return jsonify({"error": "Invalid request: 'body.input' array is required"}), 400

        # Extract useWorkflows
        useWorkflows_str = request.form.get('useWorkflows')
        if useWorkflows_str is None or useWorkflows_str.lower() == 'true':
            useWorkflows = True
        else:
            useWorkflows = False

        debug = request.args.get("debug")

        # Process attachments if provided
        # Support two patterns:
        # 1. Simple 'attachments' - applies to last input item
        # 2. 'input[<index>][attachments]' - per-input-item attachments

        # First, check for per-input-item attachments
        input_index = 0
        while True:
            attachment_key = f'input[{input_index}][attachments]'
            if attachment_key not in request.files:
                break

            files_list = request.files.getlist(attachment_key)
            valid_files = [f for f in files_list if f.filename != '']

            if valid_files and input_index < len(body["input"]):
                uploaded_files = []
                for file in valid_files:
                    # Validate file extension
                    filename = file.filename
                    file_ext = os.path.splitext(filename)[1].lower()
                    if file_ext not in ALLOWED_EXTENSIONS:
                        return jsonify({
                            "error": f"File type not allowed: {file_ext}. Allowed types: {', '.join(ALLOWED_EXTENSIONS)}"
                        }), 400

                    # Read file data
                    file.seek(0, os.SEEK_END)
                    file_size = file.tell()
                    file.seek(0)

                    # Validate file size
                    if file_size > MAX_FILE_SIZE:
                        return jsonify({
                            "error": f"File size exceeds maximum allowed size of {MAX_FILE_SIZE / (1024 * 1024)}MB"
                        }), 400

                    file_bytes = file.read()

                    # Determine content type
                    content_type, _ = mimetypes.guess_type(filename)
                    if not content_type:
                        content_type = 'application/octet-stream'

                    try:
                        # Determine storage path
                        if conversation_id:
                            file_type = "conversations"
                            entity_id = conversation_id
                        else:
                            file_type = "agents"
                            # Use agents/{agent_id}/chat/ path for chat files without conversation_id
                            entity_id = f"{agent_id}/chat"

                        # Upload to blob storage
                        upload_result = upload_file_to_blob(
                            file_type=file_type,
                            entity_id=entity_id,
                            file_data=file_bytes,
                            original_filename=filename,
                            content_type=content_type
                        )
                        uploaded_files.append(upload_result)
                    except Exception as e:
                        return jsonify({"error": f"Failed to upload file: {str(e)}"}), 500

                # Add files array to the input item
                if "files" not in body["input"][input_index]:
                    body["input"][input_index]["files"] = []
                body["input"][input_index]["files"].extend(uploaded_files)

            input_index += 1

        # Also check for simple 'attachments' field (applies to last input item)
        if 'attachments' in request.files:
            files_list = request.files.getlist('attachments')
            valid_files = [f for f in files_list if f.filename != '']

            if valid_files and len(body["input"]) > 0:
                last_input_index = len(body["input"]) - 1
                uploaded_files = []
                for file in valid_files:
                    # Validate file extension
                    filename = file.filename
                    file_ext = os.path.splitext(filename)[1].lower()
                    if file_ext not in ALLOWED_EXTENSIONS:
                        return jsonify({
                            "error": f"File type not allowed: {file_ext}. Allowed types: {', '.join(ALLOWED_EXTENSIONS)}"
                        }), 400

                    # Read file data
                    file.seek(0, os.SEEK_END)
                    file_size = file.tell()
                    file.seek(0)

                    # Validate file size
                    if file_size > MAX_FILE_SIZE:
                        return jsonify({
                            "error": f"File size exceeds maximum allowed size of {MAX_FILE_SIZE / (1024 * 1024)}MB"
                        }), 400

                    file_bytes = file.read()

                    # Determine content type
                    content_type, _ = mimetypes.guess_type(filename)
                    if not content_type:
                        content_type = 'application/octet-stream'

                    try:
                        # Determine storage path
                        if conversation_id:
                            file_type = "conversations"
                            entity_id = conversation_id
                        else:
                            file_type = "agents"
                            # Use agents/{agent_id}/chat/ path for chat files without conversation_id
                            entity_id = f"{agent_id}/chat"

                        # Upload to blob storage
                        upload_result = upload_file_to_blob(
                            file_type=file_type,
                            entity_id=entity_id,
                            file_data=file_bytes,
                            original_filename=filename,
                            content_type=content_type
                        )
                        uploaded_files.append(upload_result)
                    except Exception as e:
                        return jsonify({"error": f"Failed to upload file: {str(e)}"}), 500

                # Add files array to the last input item
                if "files" not in body["input"][last_input_index]:
                    body["input"][last_input_index]["files"] = []
                body["input"][last_input_index]["files"].extend(uploaded_files)

        # Call the workflow function with processed body
        response = openai_query_withworkflows(user_email, agent_id, body, conversation_id, debug,
                                              useWorkflows=useWorkflows)
        return jsonify(response)

    # If neither JSON nor form-data, return error
    return jsonify({"error": "Request must be either JSON or multipart/form-data"}), 400


@agent_bp.route('/workflow/node/types', methods=['GET'])
def nodetypes_get() -> Response:
    nodes = workflow.workflow_service.load_node_info()
    return jsonify(nodes)


@agent_bp.route('/workflow/<workflow_id>/nodes', methods=['GET'])
def workflow_get(workflow_id) -> Response:
    nodes = workflow.workflow_service.nodes_get(workflow_id)
    return jsonify(nodes)


@agent_bp.route('/workflow/<workflow_id>/node', methods=['POST'])
def workflow_node_add(workflow_id: str) -> Response:
    type = request.args.get("type")
    if type != None:
        return jsonify(workflow.workflow_service.node_add_bytype(workflow_id, type))
    node = request.get_json()
    return jsonify(workflow.workflow_service.node_add(workflow_id, node))


@agent_bp.route('/workflow/<workflow_id>/node/<node_id>', methods=['DELETE'])
def workflow_node_delete(workflow_id: str, node_id: str) -> Response:
    workflow.workflow_service.node_delete(workflow_id=workflow_id, node_id=node_id)
    return jsonify({"isDeleted": True})


@agent_bp.route('/workflow/<workflow_id>/node', methods=['PUT'])
def workflow_node_update(workflow_id) -> Response:
    workflow_node = request.get_json()
    workflow.workflow_service.node_update(workflow_id, workflow_node)
    return jsonify({'result': 'success'})


@agent_bp.route('/workflow/<workflow_id>/<node_id>/<pin_collection>', methods=['POST'])
def workflow_pins_add(workflow_id, node_id, pin_collection):
    pin = request.get_json()
    newPin = workflow.workflow_service.pins_add(pin_collection=pin_collection, workflow_id=workflow_id, node_id=node_id,
                                                pin=pin)
    return jsonify(newPin)


@agent_bp.route('/workflow/<workflow_id>/<node_id>/<pin_collection>', methods=['PUT'])
def workflow_pins_update(workflow_id, node_id, pin_collection):
    pin = request.get_json()
    workflow.workflow_service.pins_update(pin_collection=pin_collection, workflow_id=workflow_id, node_id=node_id,
                                          pin=pin)
    return jsonify({'result': 'success'})


@agent_bp.route('/workflow/<workflow_id>/<node_id>/<pin_collection>/<pin_id>', methods=['DELETE'])
def workflow_pins_remove(workflow_id, node_id, pin_collection, pin_id):
    workflow.workflow_service.pins_remove(pin_collection=pin_collection, workflow_id=workflow_id, node_id=node_id,
                                          pin_id=pin_id)
    return jsonify({'isDeleted': True})


@agent_bp.route('/workflow/<workflow_id>/connections', methods=['GET'])
def workflow_connections_get(workflow_id) -> Response:
    connections = workflow.workflow_service.connections_get(workflow_id)
    return jsonify(connections)


@agent_bp.route('/workflow/<workflow_id>/connection', methods=['POST'])
def workflow_connection_create(workflow_id) -> Response:
    connection = request.get_json()
    item = workflow.workflow_service.connection_create(workflow_id, connection)
    return jsonify(item)


@agent_bp.route('/workflow/nodes/copy', methods=['POST'])
def workflow_nodes_copy() -> Response:
    node_body = request.get_json()
    item = workflow.workflow_service.nodes_copy(node_body)
    return jsonify(item)


@agent_bp.route('/workflow/<workflow_id>/connection/<source_pin>/<destination_pin>', methods=['DELETE'])
def workflow_connection_delete_deprecated(workflow_id, source_pin, destination_pin) -> Response:
    workflow.workflow_service.connection_delete_deprecated(workflow_id, source_pin, destination_pin)
    return jsonify({'result': 'success'})


@agent_bp.route('/workflow/<workflow_id>/connection/<connection_id>', methods=['DELETE'])
def workflow_connection_delete(workflow_id, connection_id) -> Response:
    workflow.workflow_service.connection_delete(workflow_id, connection_id)
    return jsonify({'result': 'success'})


@agent_bp.route('/workflow/<workflow_id>/execute', methods=['POST'])
def workflow_execute(workflow_id):
    agent_id = request.args.get("agent_id")
    if agent_id is not None:
        parameters = request.get_json()
        log = workflow.workflow_service.workflow_log_create(agent_id=agent_id, workflow_id=workflow_id,
                                                            conversation_id=None)
        execution = workflow.workflow_service.workflow_execute(agent_id=agent_id, workflow_id=workflow_id, globals={},
                                                               parameters=parameters, log=log)
        return jsonify(execution)
    return jsonify({"error": "Must include a valid agent id"})


@agent_bp.route('/workflow/<workflow_id>/debug', methods=['POST'])
def workflow_debug(workflow_id):
    agent_id = request.args.get("agent_id")
    if agent_id is not None:
        try:
            parameters = request.get_json() or {}
            execution = workflow.workflow_service.workflow_debug(agent_id=agent_id, workflow_id=workflow_id,
                                                                 parameters=parameters, state_id=None, globals={})
            return jsonify(execution)
        except Exception as e:
            error_info = generate_error_message_with_openai(
                exception=e,
                workflow_id=workflow_id,
                agent_id=agent_id,
                state_id=None,
                parameters=parameters,
                context="workflow debug execution"
            )
            return jsonify({
                "status": False,
                "message": error_info["message"],
                "details": error_info["details"]
            }), 500
    return jsonify({"error": "Must include a valid agent id"})


@agent_bp.route('/workflow/<workflow_id>/debug/<state_id>', methods=['POST'])
def workflow_debug_step(workflow_id, state_id):
    agent_id = request.args.get("agent_id")
    if agent_id is not None:
        try:
            parameters = request.get_json() or {}
            execution = workflow.workflow_service.workflow_debug(agent_id=agent_id, workflow_id=workflow_id,
                                                                 parameters=parameters, state_id=state_id, globals={})
            return jsonify(execution)
        except Exception as e:
            error_info = generate_error_message_with_openai(
                exception=e,
                workflow_id=workflow_id,
                agent_id=agent_id,
                state_id=state_id,
                parameters=parameters,
                context="workflow debug step execution"
            )
            return jsonify({
                "status": False,
                "message": error_info["message"],
                "details": error_info["details"]
            }), 500
    return jsonify({"error": "Must include a valid agent id"})


@agent_bp.route('/agent/<agent_id>/workflows', methods=['GET'])
def workflows_get(agent_id) -> Response:
    workflows = workflow.workflow_service.workflows_get(agent_id)
    # workflows.reverse()
    # print(workflows,"workflows-----------")
    return jsonify(workflows)


@agent_bp.route('/workflow', methods=['POST'])
def workflow_add() -> Response:
    workflowJson = request.get_json()
    agent_id = request.args.get("agent_id")
    workflowObj = workflow.workflow_service.workflow_add(workflowJson)
    if agent_id != None and agent_id != "":
        workflow.workflow_service.agent_workflows_add(agent_id, workflowObj["workflow_id"])
    return jsonify(workflowObj)


@agent_bp.route('/workflow/<workflow_id>/ai-chat', methods=['POST'])
def workflow_ai_chat(workflow_id: str) -> Response:
    """
    AI chat endpoint for workflow generation/modification.
    Maintains conversation history and allows iterative workflow improvements.
    
    Request Body:
    {
        "prompt": "Add a WhatsApp trigger node to the workflow",
        "conversation_id": "optional-existing-conversation-id"  // Optional, auto-created if not provided
    }
    
    Query Params:
    - agent_id: Required agent ID
    """
    try:
        user_email = request.headers.get("x-user-email")
        if not user_email:
            return jsonify({"error": "User is not authenticated"}), 401
        
        agent_id = request.args.get("agent_id")
        if not agent_id:
            return jsonify({"error": "agent_id query parameter is required"}), 400
        
        # Verify workflow exists
        workflow_data = workflow.workflow_service.workflow_get(workflow_id)
        if not workflow_data:
            return jsonify({"error": f"Workflow '{workflow_id}' not found"}), 404
        
        # Verify agent exists
        agent = workflow.workflow_service.agent_get(agent_id)
        if not agent:
            return jsonify({"error": f"Agent '{agent_id}' not found"}), 404
        
        # Get request data
        data = request.get_json()
        if not data or 'prompt' not in data:
            return jsonify({"error": "Prompt is required"}), 400
        
        prompt = data.get('prompt', '').strip()
        if len(prompt) < 3:
            return jsonify({"error": "Prompt must be at least 3 characters"}), 400
        
        if len(prompt) > 2000:
            return jsonify({"error": "Prompt must be less than 2000 characters"}), 400
        
        # Get or create conversation
        conversation_id = data.get('conversation_id')
        conversation = None
        
        if conversation_id:
            # Get existing conversation
            conversation = workflow_conversation_get(user_email, agent_id, workflow_id, include_messages=True)
            if conversation and conversation.get("conversation_id") != conversation_id:
                # conversation_id doesn't match, create new
                conversation = None
        
        if not conversation:
            # Create new conversation
            conversation = workflow_conversation_add(user_email, agent_id, workflow_id)
            conversation_id = conversation.get("conversation_id")
        
        # Get conversation history
        history = workflow_conversation_get_history(user_email, agent_id, workflow_id)
        
        # Get existing workflow structure (nodes and connections)
        existing_nodes = workflow.workflow_service.nodes_get(workflow_id)
        existing_connections = workflow.workflow_service.connections_get(workflow_id)
        
        existing_workflow = None
        if existing_nodes or existing_connections:
            existing_workflow = {
                "nodes": existing_nodes or [],
                "connections": existing_connections or []
            }
        
        # Add user message to conversation
        user_message = {
            "role": "user",
            "content": prompt
        }
        workflow_message_add(conversation_id, user_message)
        
        # Check if user wants to delete connections
        deletion_info = detect_deletion_request(prompt, existing_nodes or [], existing_connections or [])
        actions_taken = []
        deleted_connection_ids = []
        
        # Handle connection deletion if requested
        if deletion_info["action"] == "delete_connections" and deletion_info["targets"]:
            deleted_connection_ids = delete_connections_by_targets(workflow_id, deletion_info["targets"])
            actions_taken.append("Deleting connections")
            
            # Refresh connections after deletion
            existing_connections = workflow.workflow_service.connections_get(workflow_id)
            if existing_workflow:
                existing_workflow["connections"] = existing_connections
        
        # Generate or modify workflow using AI
        generator = AIWorkflowGenerator()
        generated_workflow = generator.generate_or_modify_workflow(
            prompt=prompt,
            conversation_history=history + [user_message],  # Include current message
            existing_workflow=existing_workflow
        )
        
        # Track actions taken
        if not existing_workflow:
            actions_taken.extend(["Categorizing prompt", "Getting best practices", "Getting workflow examples"])
        actions_taken.extend(["Searching nodes", "Getting node details", "Adding nodes", "Connecting nodes", "Updating node parameters", "Validating workflow"])
        
        # Update workflow in database
        # Delete existing connections first (to avoid orphaned connections)
        if existing_connections:
            for connection in existing_connections:
                connection_id = connection.get("id")
                if connection_id:
                    workflow.workflow_service.connection_delete(workflow_id, connection_id)
        
        # Delete existing nodes (this will also delete associated connections)
        if existing_nodes:
            for node in existing_nodes:
                workflow.workflow_service.node_delete(workflow_id=workflow_id, node_id=node.get("id"))
        
        # Add new nodes
        node_id_mapping = {}  # Maps old node ID -> new node ID
        for node in generated_workflow["nodes"]:
            old_node_id = node.get("id")
            node["workflow_id"] = workflow_id
            
            # Save node (this will generate a new ID)
            saved_node = workflow.workflow_service.node_add(workflow_id, node)
            new_node_id = saved_node["id"]
            
            if old_node_id:
                node_id_mapping[old_node_id] = new_node_id
        
        # Update connections with new node IDs
        for connection in generated_workflow["connections"]:
            old_source_node = connection.get("source_node")
            old_dest_node = connection.get("destination_node")
            
            if old_source_node in node_id_mapping:
                connection["source_node"] = node_id_mapping[old_source_node]
            if old_dest_node in node_id_mapping:
                connection["destination_node"] = node_id_mapping[old_dest_node]
            
            # Verify pins exist before creating connection
            source_node = workflow.workflow_service.node_get(workflow_id, connection["source_node"])
            dest_node = workflow.workflow_service.node_get(workflow_id, connection["destination_node"])
            
            if source_node and dest_node:
                # Verify pin IDs exist
                source_pin_exists = False
                dest_pin_exists = False
                
                for pin_collection in ["trigger_pins", "input_pins", "output_pins", "next_pins"]:
                    for pin in source_node.get("pins", {}).get(pin_collection, []):
                        if pin.get("id") == connection.get("source_pin"):
                            source_pin_exists = True
                            break
                    if source_pin_exists:
                        break
                
                for pin_collection in ["trigger_pins", "input_pins", "output_pins", "next_pins"]:
                    for pin in dest_node.get("pins", {}).get(pin_collection, []):
                        if pin.get("id") == connection.get("destination_pin"):
                            dest_pin_exists = True
                            break
                    if dest_pin_exists:
                        break
                
                if source_pin_exists and dest_pin_exists:
                    workflow.workflow_service.connection_create(workflow_id, connection)
        
        # Get existing workflow to preserve name and description
        existing_workflow_data = workflow.workflow_service.workflow_get(workflow_id)
        existing_name = existing_workflow_data.get("name", "") if existing_workflow_data else ""
        existing_description = existing_workflow_data.get("description", "") if existing_workflow_data else ""
        
        # Only update workflow name and description if they don't already exist
        # Preserve existing values - do not overwrite if user has already set them
        update_data = {}
        
        # Only set name if it doesn't exist yet
        if not existing_name:
            workflow_name = generated_workflow.get("workflow_name")
            if workflow_name:
                update_data["name"] = workflow_name
        else:
            # Use existing name
            workflow_name = existing_name
        
        # Only set description if it doesn't exist yet
        if not existing_description:
            workflow_description = generated_workflow.get("workflow_description")
            if workflow_description:
                update_data["description"] = workflow_description
        else:
            # Use existing description
            workflow_description = existing_description
        
        # Only update if there's something to update
        if update_data:
            workflow.workflow_service.workflow_update(workflow_id, update_data)
        
        # Get final nodes after workflow update (for configuration detection)
        final_nodes = workflow.workflow_service.nodes_get(workflow_id)
        final_connections = workflow.workflow_service.connections_get(workflow_id)
        
        # Track workflow changes
        changes = track_workflow_changes(
            existing_nodes=existing_nodes or [],
            existing_connections=existing_connections or [],
            new_nodes=final_nodes,
            new_connections=final_connections,
            prompt=prompt
        )
        
        # Generate "What's changed" summary
        whats_changed = generate_whats_changed_summary(changes)
        
        # Detect configuration needs
        configuration_warnings = detect_configuration_needs(workflow_id, final_nodes)
        
        # Generate setup instructions
        setup_instructions = generate_setup_instructions(workflow_id, final_nodes)
        
        # Create checklist response
        workflow_info = {
            "node_count": len(final_nodes),
            "connection_count": len(final_connections),
            "workflow_name": workflow_name,
            "workflow_description": workflow_description,
            "existing": existing_workflow is not None,
            "deleted_connections": len(deleted_connection_ids)
        }
        
        checklist_response = create_checklist_response(actions_taken, workflow_info)
        
        # Create assistant response message with checklist and changes
        assistant_response = f"I've {'updated' if existing_workflow else 'created'} your workflow with {workflow_info['node_count']} nodes and {workflow_info['connection_count']} connections."
        if workflow_name:
            assistant_response += f" The workflow is named '{workflow_name}'."
        if deleted_connection_ids:
            assistant_response += f" Deleted {len(deleted_connection_ids)} connection(s) as requested."
        
        # Format checklist for message
        checklist_text = "\n\n**Workflow AI Checklist:**\n"
        for item in checklist_response["checklist"]:
            icon = "✓" if item["completed"] else "○"
            checklist_text += f"{icon} {item['item']}\n"
        
        # Add "What's changed" section if there are changes
        if whats_changed:
            whats_changed_text = "\n\n**What's changed:**\n"
            for change in whats_changed:
                whats_changed_text += f"• {change}\n"
            checklist_text += whats_changed_text
        
        # Add setup instructions if any
        if setup_instructions:
            setup_text = "\n\n**How to Setup:**\n"
            for i, instruction in enumerate(setup_instructions, 1):
                setup_text += f"{i}. {instruction}\n"
            checklist_text += setup_text
        
        assistant_message = {
            "role": "assistant",
            "content": assistant_response + checklist_text
        }
        workflow_message_add(conversation_id, assistant_message)
        
        # Prepare configuration warnings for response (all nodes)
        config_warnings_formatted = []
        for warning in configuration_warnings:
            config_warnings_formatted.append({
                "node_id": warning["node_id"],
                "node_label": warning["node_label"],
                "node_type": warning["node_type"],
                "message": warning["warning_message"]
            })
        
        # Return response with checklist, changes, and configuration warnings
        return jsonify({
            "status": "success",
            "conversation_id": conversation_id,
            "workflow_id": workflow_id,
            "message": assistant_response,
            "checklist": checklist_response["checklist"],
            "summary": checklist_response["summary"],
            "whats_changed": whats_changed,
            "changes": changes,
            "configuration_warnings": config_warnings_formatted,
            "setup_instructions": setup_instructions,
            "workflow": {
                "nodes": generated_workflow.get("nodes", []),
                "connections": generated_workflow.get("connections", []),
                "workflow_name": workflow_name,
                "workflow_description": workflow_description
            },
            "deleted_connections": deleted_connection_ids
        }), 200
        
    except Exception as e:
        import traceback
        error_details = str(e)
        traceback.print_exc()
        return jsonify({
            "error": error_details,
            "status": "error"
        }), 500


@agent_bp.route('/workflow/<workflow_id>/ai-chat/history', methods=['GET'])
def workflow_ai_chat_history(workflow_id: str) -> Response:
    """
    Get conversation history for a workflow.
    
    Query Params:
    - agent_id: Required agent ID
    - conversation_id: Optional specific conversation ID (if not provided, returns latest)
    """
    try:
        user_email = request.headers.get("x-user-email")
        if not user_email:
            return jsonify({"error": "User is not authenticated"}), 401
        
        agent_id = request.args.get("agent_id")
        if not agent_id:
            return jsonify({"error": "agent_id query parameter is required"}), 400
        
        conversation_id = request.args.get("conversation_id")
        
        if conversation_id:
            # Get specific conversation
            conversation = workflow_conversation_get(user_email, agent_id, workflow_id, include_messages=True)
            if conversation and conversation.get("conversation_id") == conversation_id:
                return jsonify({
                    "conversation": conversation,
                    "messages": conversation.get("messages", [])
                }), 200
            else:
                return jsonify({"error": "Conversation not found"}), 404
        else:
            # Get latest conversation
            conversation = workflow_conversation_get(user_email, agent_id, workflow_id, include_messages=True)
            if conversation:
                return jsonify({
                    "conversation": conversation,
                    "messages": conversation.get("messages", [])
                }), 200
            else:
                return jsonify({
                    "conversation": None,
                    "messages": []
                }), 200
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({
            "error": str(e),
            "status": "error"
        }), 500


@agent_bp.route('/workflow/<workflow_id>/ai-chat/conversations', methods=['GET'])
def workflow_ai_chat_conversations(workflow_id: str) -> Response:
    """
    Get all conversations for a workflow (for history display).
    
    Query Params:
    - agent_id: Optional agent ID filter
    """
    try:
        user_email = request.headers.get("x-user-email")
        if not user_email:
            return jsonify({"error": "User is not authenticated"}), 401
        
        conversations = workflow_conversations_get_by_workflow(user_email, workflow_id)
        
        return jsonify({
            "conversations": conversations
        }), 200
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({
            "error": str(e),
            "status": "error"
        }), 500


@agent_bp.route('/workflow/ai-generate', methods=['POST'])
def workflow_ai_generate() -> Response:
    """
    Generate a workflow from a natural language prompt using AI.
    
    Request Body:
    {
        "prompt": "Create a workflow that receives a WhatsApp message, processes it with LLM, and sends a response",
        "name": "WhatsApp AI Assistant",  // Optional
        "description": "AI-powered WhatsApp responder",  // Optional
        "save": true,  // Optional, default: false
        "agent_id": "your-agent-id"  // Required if save=true
    }
    """
    try:
        from services.ai_workflow_service import AIWorkflowGenerator
        
        # Get user email for conversation tracking
        user_email = request.headers.get("x-user-email")
        
        data = request.get_json()
        
        # Validate request
        if not data or 'prompt' not in data:
            return jsonify({
                "error": "Prompt is required",
                "status": "error"
            }), 400
        
        prompt = data.get('prompt', '').strip()
        if len(prompt) < 10:
            return jsonify({
                "error": "Prompt must be at least 10 characters",
                "status": "error"
            }), 400
        
        if len(prompt) > 1500:
            return jsonify({
                "error": "Prompt must be less than 1500 characters",
                "status": "error"
            }), 400
        
        save = data.get('save', False)
        agent_id = data.get('agent_id')
        
        # Generate workflow using AI (this will include name and description)
        generator = AIWorkflowGenerator()
        generated_workflow = generator.generate_workflow(prompt)
        
        # Use AI-generated name and description, or fallback to user-provided/default
        workflow_name = data.get('name') or generated_workflow.get('workflow_name', 'AI Generated Workflow')
        workflow_description = data.get('description') or generated_workflow.get('workflow_description', prompt[:200] + '...' if len(prompt) > 200 else prompt)
        
        # Validate agent_id if saving
        if save and not agent_id:
            return jsonify({
                "error": "agent_id is required when save=true",
                "status": "error"
            }), 400
        
        # Verify agent exists if saving
        if save:
            agent = workflow.workflow_service.agent_get(agent_id)
            if agent is None:
                return jsonify({
                    "error": f"Agent '{agent_id}' not found",
                    "status": "error"
                }), 400
        
        # Debug: Log generated workflow structure
        print(f"DEBUG: Generated workflow - {len(generated_workflow.get('nodes', []))} nodes, {len(generated_workflow.get('connections', []))} connections")
        if generated_workflow.get('connections'):
            print(f"DEBUG: Sample connection: {generated_workflow['connections'][0]}")
        
        # Prepare response
        response = {
            "workflow": generated_workflow,
            "status": "success"
        }
        
        # Save workflow if requested
        if save:
            # Create workflow record
            workflow_obj = {
                "name": workflow_name,
                "description": workflow_description
            }
            workflow_record = workflow.workflow_service.workflow_add(workflow_obj)
            workflow_id = workflow_record["workflow_id"]
            
            # Save nodes and create node ID mapping
            # IMPORTANT: node_add generates new node IDs, so we need to map old IDs to new IDs
            node_id_mapping = {}  # Maps old node ID -> new node ID
            
            for node in generated_workflow["nodes"]:
                old_node_id = node["id"]  # Store the original ID
                node["workflow_id"] = workflow_id
                
                # Save node (this will generate a new ID)
                saved_node = workflow.workflow_service.node_add(workflow_id, node)
                new_node_id = saved_node["id"]
                
                # Map old ID to new ID
                node_id_mapping[old_node_id] = new_node_id
                print(f"Mapped node ID: {old_node_id} -> {new_node_id}")
            
            # Update connections with new node IDs and save
            for connection in generated_workflow["connections"]:
                try:
                    # Update source and destination node IDs using the mapping
                    old_source_node = connection.get("source_node")
                    old_dest_node = connection.get("destination_node")
                    
                    if old_source_node in node_id_mapping and old_dest_node in node_id_mapping:
                        # Create connection with updated node IDs
                        updated_connection = {
                            "source_node": node_id_mapping[old_source_node],
                            "source_pin": connection.get("source_pin"),
                            "destination_node": node_id_mapping[old_dest_node],
                            "destination_pin": connection.get("destination_pin")
                        }
                        
                        # Verify pins exist in the saved nodes
                        source_node = workflow.workflow_service.node_get(workflow_id, updated_connection["source_node"])
                        dest_node = workflow.workflow_service.node_get(workflow_id, updated_connection["destination_node"])
                        
                        if source_node and dest_node:
                            # Verify pin IDs exist
                            source_pin_exists = False
                            dest_pin_exists = False
                            
                            # Check all pin collections for source pin
                            for pin_collection in ["trigger_pins", "input_pins", "output_pins", "next_pins"]:
                                for pin in source_node.get("pins", {}).get(pin_collection, []):
                                    if pin.get("id") == updated_connection["source_pin"]:
                                        source_pin_exists = True
                                        break
                                if source_pin_exists:
                                    break
                            
                            # Check all pin collections for dest pin
                            for pin_collection in ["trigger_pins", "input_pins", "output_pins", "next_pins"]:
                                for pin in dest_node.get("pins", {}).get(pin_collection, []):
                                    if pin.get("id") == updated_connection["destination_pin"]:
                                        dest_pin_exists = True
                                        break
                                if dest_pin_exists:
                                    break
                            
                            if source_pin_exists and dest_pin_exists:
                                workflow.workflow_service.connection_create(workflow_id, updated_connection)
                                print(f"Created connection: {updated_connection['source_node']} -> {updated_connection['destination_node']}")
                            else:
                                print(f"WARNING: Pin IDs not found in saved nodes. Source pin exists: {source_pin_exists}, Dest pin exists: {dest_pin_exists}")
                                print(f"  Connection: {connection}")
                        else:
                            print(f"WARNING: Nodes not found. Source: {source_node is not None}, Dest: {dest_node is not None}")
                    else:
                        print(f"WARNING: Node ID mapping not found. Source: {old_source_node in node_id_mapping}, Dest: {old_dest_node in node_id_mapping}")
                        print(f"  Connection: {connection}")
                        print(f"  Available mappings: {list(node_id_mapping.keys())}")
                        
                except Exception as e:
                    # Log but don't fail - continue with other connections
                    import traceback
                    print(f"Error creating connection: {e}")
                    print(f"Connection data: {connection}")
                    traceback.print_exc()
            
            # Associate workflow with agent
            workflow.workflow_service.agent_workflows_add(agent_id, workflow_id)
            
            # Get final nodes after saving (for configuration detection)
            final_nodes = workflow.workflow_service.nodes_get(workflow_id)
            final_connections = workflow.workflow_service.connections_get(workflow_id)
            
            # Detect configuration needs
            configuration_warnings = detect_configuration_needs(workflow_id, final_nodes)
            
            # Generate setup instructions
            setup_instructions = generate_setup_instructions(workflow_id, final_nodes)
            
            # Track actions for checklist
            actions_taken = ["Categorizing prompt", "Getting best practices", "Getting workflow examples", 
                           "Searching nodes", "Getting node details", "Adding nodes", "Connecting nodes", 
                           "Updating node parameters", "Validating workflow"]
            
            workflow_info = {
                "node_count": len(final_nodes),
                "connection_count": len(final_connections),
                "workflow_name": workflow_name,
                "workflow_description": workflow_description,
                "existing": False
            }
            
            checklist_response = create_checklist_response(actions_taken, workflow_info)
            
            # Generate "What's changed" summary (for new workflows, it's all new)
            whats_changed = []
            for node in final_nodes:
                node_label = node.get("label", "") or node.get("nodeType", "")
                whats_changed.append(f"Added the {node_label} node")
            
            # Save conversation if user is authenticated
            conversation_id = None
            if user_email:
                try:
                    # Get or create conversation for this workflow
                    conversation = workflow_conversation_add(user_email, agent_id, workflow_id)
                    conversation_id = conversation.get("conversation_id")
                    
                    # Save user prompt as message
                    user_message = {
                        "role": "user",
                        "content": prompt
                    }
                    workflow_message_add(conversation_id, user_message)
                    
                    # Create AI response message with checklist
                    ai_response_message = f"I've created your workflow '{workflow_name}' with {len(final_nodes)} nodes and {len(final_connections)} connections."
                    
                    # Format checklist for message
                    checklist_text = "\n\n**Workflow AI Checklist:**\n"
                    for item in checklist_response["checklist"]:
                        icon = "✓" if item["completed"] else "○"
                        checklist_text += f"{icon} {item['item']}\n"
                    
                    # Add "What's changed" section
                    if whats_changed:
                        whats_changed_text = "\n\n**What's changed:**\n"
                        for change in whats_changed[:5]:  # Limit to first 5 changes
                            whats_changed_text += f"• {change}\n"
                        checklist_text += whats_changed_text
                    
                    # Add setup instructions if any
                    if setup_instructions:
                        setup_text = "\n\n**How to Setup:**\n"
                        for i, instruction in enumerate(setup_instructions, 1):
                            setup_text += f"{i}. {instruction}\n"
                        checklist_text += setup_text
                    
                    assistant_message = {
                        "role": "assistant",
                        "content": ai_response_message + checklist_text
                    }
                    workflow_message_add(conversation_id, assistant_message)
                    
                    response["conversation_id"] = conversation_id
                except Exception as e:
                    # Don't fail if conversation saving fails, just log it
                    print(f"Warning: Failed to save conversation for workflow {workflow_id}: {e}")
            
            # Prepare configuration warnings for response (all nodes)
            config_warnings_formatted = []
            for warning in configuration_warnings:
                config_warnings_formatted.append({
                    "node_id": warning["node_id"],
                    "node_label": warning["node_label"],
                    "node_type": warning["node_type"],
                    "message": warning["warning_message"]
                })
            
            response["workflow_id"] = workflow_id
            response["message"] = "Workflow generated and saved successfully"
            response["checklist"] = checklist_response["checklist"]
            response["whats_changed"] = whats_changed
            response["configuration_warnings"] = config_warnings_formatted
            response["setup_instructions"] = setup_instructions
        
        return jsonify(response), 200
        
    except Exception as e:
        import traceback
        error_details = str(e)
        traceback.print_exc()
        return jsonify({
            "error": error_details,
            "status": "error"
        }), 500


@agent_bp.route('/workflow/<workflow_id>', methods=['PUT'])
def workflow_update(workflow_id) -> Response:
    workflowJson = request.get_json()
    workflow.workflow_service.workflow_update(workflow_id, workflowJson)
    return jsonify({"result": "success"})


@agent_bp.route('/workflow/<workflow_id>', methods=['DELETE'])
def workflow_delete_route(workflow_id: str) -> Response:
    """
    Delete a workflow and all its associated data including:
    - Nodes and connections
    - Notes
    - Logs and states
    - Workflow AI chat conversations and messages
    """
    try:
        user_email = request.headers.get("x-user-email")
        if not user_email:
            return jsonify({"error": "User is not authenticated"}), 401
        
        # Verify workflow exists
        workflow_data = workflow.workflow_service.workflow_get(workflow_id)
        if not workflow_data:
            return jsonify({"error": f"Workflow '{workflow_id}' not found"}), 404
        
        # Delete the workflow (this will also delete all conversations and messages)
        workflow.workflow_service.workflow_delete(workflow_id)
        
        return jsonify({
            "status": "success",
            "message": f"Workflow '{workflow_id}' and all associated data (including AI chat conversations) have been deleted successfully."
        }), 200
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({
            "error": str(e),
            "status": "error"
        }), 500


@agent_bp.route('/workflow/<workflow_id>/export', methods=['GET'])
def workflow_export_route(workflow_id) -> Response:
    workflowJson = workflow.workflow_service.workflow_export(workflow_id=workflow_id)
    return jsonify(workflowJson)


@agent_bp.route('/agent/<agent_id>/workflows', methods=['POST'])
def agent_workflows_add(agent_id: str) -> Response:
    workflow_ids = request.get_json()
    for workflow_id in workflow_ids:
        workflow.workflow_service.agent_workflows_add(agent_id, workflow_id)
    return jsonify({"result": "success"})


@agent_bp.route('/agent/<agent_id>/workflow/import', methods=['POST'])
def agent_workflow_import(agent_id: str) -> Response:
    workflow_obj = request.get_json()
    workflow_id = workflow.workflow_service.workflow_import(workflow_obj)
    workflow.workflow_service.agent_workflows_add(agent_id, workflow_id)
    return jsonify({"result": "success"})


@agent_bp.route('/agent/<agent_id>/workflows/remove', methods=['POST'])
def agent_workflows_remove(agent_id: str) -> Response:
    workflow_ids = request.get_json()
    workflow.workflow_service.agent_workflows_remove(agent_id, workflow_ids)
    return jsonify({"result": "success"})


@agent_bp.route('/agents/all', methods=['GET'])
def agents_get_all_route() -> Response:
    agents = workflow.workflow_service.agents_get()
    return jsonify(agents)


@agent_bp.route('/agents', methods=['GET'])
def agents_get_route() -> Response:
    user_email = request.headers.get("x-user-email")
    if user_email is None:
        return jsonify({"error": "User is not authenticated."})
    agents = agents_get(user_email)
    return jsonify(agents)


@agent_bp.route('/agent', methods=['POST'])
def agent_add() -> Response:
    agentObj = request.get_json()
    user_email = request.headers.get("x-user-email")
    if user_email is None:
        return jsonify({"error": "User is not authenticated."})
    agentObj["creator_id"] = user_email
    agent = workflow.workflow_service.agent_add(agentObj)
    return jsonify(agent)


@agent_bp.route('/agent/<agent_id>', methods=['PUT'])
def agent_update(agent_id) -> Response:
    agentObj = request.get_json()
    agent = workflow.workflow_service.agent_update(agent_id, agentObj)
    return jsonify({"result": "success"})


@agent_bp.route('/agent/<agent_id>/files', methods=['GET'])
def agent_files_get_route(agent_id) -> Response:
    always_on = request.args.get("always_on") == "true"
    contents = request.args.get("contents") == "true"
    searchable = request.args.get("searchable") == "true"
    include_signed_urls = request.args.get("include_signed_urls", "false").lower() == "true"
    files = agent_files_get(agent_id=agent_id, always_on=always_on, contents=contents, searchable=searchable)

    # Optionally add signed URLs for files
    if include_signed_urls:
        expiry_hours = int(request.args.get("expiry_hours", 1))
        for file in files:
            # Handle files array (new structure)
            files_array = file.get("files")
            if files_array and isinstance(files_array, list):
                signed_urls = []
                for file_info in files_array:
                    if isinstance(file_info, dict) and file_info.get("path"):
                        try:
                            signed_url = generate_sas_url(file_info["path"], expiry_hours=expiry_hours)
                            signed_urls.append({
                                "filename": file_info.get("filename"),
                                "signed_url": signed_url
                            })
                        except Exception as e:
                            import logging
                            logging.getLogger(__name__).warning(
                                f"Failed to generate signed URL for file {file.get('id')}: {e}")
                if signed_urls:
                    file["signed_urls"] = signed_urls
            # Handle backward compatibility with blob_url
            elif file.get("blob_url"):
                try:
                    signed_url = generate_sas_url(file["blob_url"], expiry_hours=expiry_hours)
                    file["signed_url"] = signed_url
                except Exception as e:
                    import logging
                    logging.getLogger(__name__).warning(f"Failed to generate signed URL for file {file.get('id')}: {e}")

    return jsonify(files)


@agent_bp.route('/agent/<agent_id>/file/<file_id>', methods=["GET"])
def agent_file_get_route(agent_id, file_id) -> Response:
    file = agent_file_get(agent_id=agent_id, file_id=file_id)
    if file:
        # Handle files array (new structure)
        files_array = file.get("files")
        if files_array and isinstance(files_array, list):
            signed_urls = []
            try:
                expiry_hours = int(request.args.get("expiry_hours", 1))
                for file_info in files_array:
                    if isinstance(file_info, dict) and file_info.get("path"):
                        signed_url = generate_sas_url(file_info["path"], expiry_hours=expiry_hours)
                        signed_urls.append({
                            "filename": file_info.get("filename"),
                            "signed_url": signed_url
                        })
                if signed_urls:
                    file["signed_urls"] = signed_urls
            except Exception as e:
                import logging
                logging.getLogger(__name__).warning(f"Failed to generate signed URLs: {e}")

        # Handle backward compatibility with blob_url
        elif file.get("blob_url"):
            try:
                expiry_hours = int(request.args.get("expiry_hours", 1))
                signed_url = generate_sas_url(file["blob_url"], expiry_hours=expiry_hours)
                file["signed_url"] = signed_url
            except Exception as e:
                import logging
                logging.getLogger(__name__).warning(f"Failed to generate signed URL: {e}")
    return jsonify(file)


@agent_bp.route('/agent/<agent_id>/file/<file_id>/url', methods=["GET"])
def agent_file_get_signed_url_route(agent_id, file_id) -> Response:
    """
    Get signed URL(s) for a file's blob(s).
    Query params:
        expiry_hours: Number of hours the URL should be valid (default: 1)
        file_index: Index of file in files array (default: 0, for backward compatibility)
    """
    file = agent_file_get(agent_id=agent_id, file_id=file_id)
    if not file:
        return jsonify({"error": "File not found"}), 404

    # Handle files array (new structure)
    files_array = file.get("files")
    if files_array and isinstance(files_array, list) and len(files_array) > 0:
        try:
            expiry_hours = int(request.args.get("expiry_hours", 1))
            file_index = int(request.args.get("file_index", 0))

            if file_index >= len(files_array):
                return jsonify(
                    {"error": f"File index {file_index} out of range. File has {len(files_array)} file(s)"}), 400

            file_info = files_array[file_index]
            if not isinstance(file_info, dict) or not file_info.get("path"):
                return jsonify({"error": "File does not have a valid blob path"}), 400

            blob_url = file_info["path"]
            signed_url = generate_sas_url(blob_url, expiry_hours=expiry_hours)
            return jsonify({
                "signed_url": signed_url,
                "expiry_hours": expiry_hours,
                "file_id": file_id,
                "filename": file_info.get("filename"),
                "blob_url": blob_url,
                "file_index": file_index,
                "total_files": len(files_array)
            })
        except Exception as e:
            import logging
            logging.getLogger(__name__).error(f"Error generating signed URL: {e}")
            return jsonify({"error": f"Failed to generate signed URL: {str(e)}"}), 500

    # Handle backward compatibility with blob_url
    blob_url = file.get("blob_url")
    if not blob_url:
        return jsonify({"error": "File does not have an associated blob"}), 400

    try:
        expiry_hours = int(request.args.get("expiry_hours", 1))
        signed_url = generate_sas_url(blob_url, expiry_hours=expiry_hours)
        return jsonify({
            "signed_url": signed_url,
            "expiry_hours": expiry_hours,
            "file_id": file_id,
            "blob_url": blob_url
        })
    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"Error generating signed URL: {e}")
        return jsonify({"error": f"Failed to generate signed URL: {str(e)}"}), 500


@agent_bp.route('/agent/<agent_id>/file', methods=["POST"])
def agent_file_add_route(agent_id) -> Response:
    # Allowed file extensions
    ALLOWED_EXTENSIONS = {'.pdf', '.jpg', '.jpeg', '.png', '.gif', '.doc', '.docx', '.xls', '.xlsx', '.csv'}
    MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB

    # Get metadata from request (supports both JSON and multipart/form-data)
    file_data = {}

    # Try to get data from JSON first (for JSON requests)
    if request.is_json:
        file_data = request.get_json() or {}

    # Also check form data (for multipart/form-data requests)
    if request.form:
        # Try to get JSON from form data field
        json_data = request.form.get('data')
        if json_data:
            try:
                file_data = json.loads(json_data)
            except:
                pass
        # Also check individual form fields (overrides JSON if present)
        if 'name' in request.form:
            file_data['name'] = request.form.get('name')
        if 'description' in request.form:
            file_data['description'] = request.form.get('description')
        if 'contents' in request.form:
            file_data['contents'] = request.form.get('contents')
        if 'content_type' in request.form:
            file_data['content_type'] = request.form.get('content_type')
        if 'always_on' in request.form:
            file_data['always_on'] = request.form.get('always_on', '').lower() == 'true'
        if 'searchable' in request.form:
            file_data['searchable'] = request.form.get('searchable', '').lower() == 'true'

    # Validate that name is provided
    if 'name' not in file_data or not file_data['name']:
        return jsonify({"error": "'name' field is required"}), 400

    # Check if attachments are provided (optional)
    has_attachments = False
    files = []
    if 'attachments' in request.files:
        files = request.files.getlist('attachments')
        # Check if there are actual files (not just empty filenames)
        valid_files = [f for f in files if f.filename != '']
        if valid_files:
            has_attachments = True
            files = valid_files

    # If no attachments, work exactly like before (backward compatibility)
    if not has_attachments:
        fileObj = agent_file_add(agent_id=agent_id, file=file_data)
        return jsonify(fileObj)

    # Process files if attachments are provided
    # Collect all upload results first, then create a single DB entry
    upload_results = []
    for file in files:
        # Validate file extension
        filename = file.filename
        file_ext = os.path.splitext(filename)[1].lower()
        if file_ext not in ALLOWED_EXTENSIONS:
            return jsonify({
                "error": f"File type not allowed: {file_ext}. Allowed types: {', '.join(ALLOWED_EXTENSIONS)}"
            }), 400

        # Read file data
        file.seek(0, os.SEEK_END)
        file_size = file.tell()
        file.seek(0)

        # Validate file size
        if file_size > MAX_FILE_SIZE:
            return jsonify({
                "error": f"File size exceeds maximum allowed size of {MAX_FILE_SIZE / (1024 * 1024)}MB"
            }), 400

        file_bytes = file.read()

        # Determine content type (use provided or guess from filename)
        content_type = file_data.get('content_type')
        if not content_type:
            content_type, _ = mimetypes.guess_type(filename)
        if not content_type:
            content_type = 'application/octet-stream'

        try:
            # Upload to blob storage (returns dict with path, filename, size, type, extension, uploaded_at)
            upload_result = upload_file_to_blob(
                file_type="agents",
                entity_id=agent_id,
                file_data=file_bytes,
                original_filename=filename,
                content_type=content_type
            )
            upload_results.append(upload_result)

        except ValueError as e:
            return jsonify({"error": str(e)}), 500
        except Exception as e:
            return jsonify({"error": f"Failed to upload file: {str(e)}"}), 500

    # Create a single file object with all files in the files array
    # Use the name from metadata, or generate a name based on file count
    if len(upload_results) == 1:
        file_name = file_data.get('name', upload_results[0].get('filename', 'file'))
    else:
        # For multiple files, use the metadata name if provided, otherwise use a generic name
        file_name = file_data.get('name', f"{len(upload_results)} files")

    file_obj_data = {
        "name": file_name,
        "description": file_data.get("description"),
        "contents": file_data.get("contents"),
        "always_on": file_data.get("always_on"),
        "searchable": file_data.get("searchable"),
        "files": upload_results  # All files in a single array
    }

    # Create a single DB entry with all files
    fileObj = agent_file_add(agent_id=agent_id, file=file_obj_data)
    return jsonify(fileObj)


@agent_bp.route('/agent/<agent_id>/file', methods=["PUT"])
def agent_file_update_route(agent_id) -> Response:
    # Allowed file extensions
    ALLOWED_EXTENSIONS = {'.pdf', '.jpg', '.jpeg', '.png', '.gif', '.doc', '.docx', '.xls', '.xlsx', '.csv'}
    MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB

    # Get metadata from request (supports both JSON and multipart/form-data)
    file_data = {}

    # Try to get data from JSON first (for JSON requests)
    if request.is_json:
        file_data = request.get_json() or {}

    # Also check form data (for multipart/form-data requests)
    if request.form:
        # Try to get JSON from form data field
        json_data = request.form.get('data')
        if json_data:
            try:
                file_data = json.loads(json_data)
            except:
                pass
        # Also check individual form fields (overrides JSON if present)
        if 'id' in request.form:
            file_data['id'] = request.form.get('id')
        if 'name' in request.form:
            file_data['name'] = request.form.get('name')
        if 'description' in request.form:
            file_data['description'] = request.form.get('description')
        if 'contents' in request.form:
            file_data['contents'] = request.form.get('contents')
        if 'content_type' in request.form:
            file_data['content_type'] = request.form.get('content_type')
        if 'always_on' in request.form:
            file_data['always_on'] = request.form.get('always_on', '').lower() == 'true'
        if 'searchable' in request.form:
            file_data['searchable'] = request.form.get('searchable', '').lower() == 'true'

    # Validate that file ID is provided
    if 'id' not in file_data:
        return jsonify({"error": "'id' field is required"}), 400

    # Get existing file to check for old blobs and preserve existing data
    from services.file_service import agent_file_get
    from services.blob_storage_service import delete_blob, upload_file_to_blob
    existing_file = agent_file_get(agent_id=agent_id, file_id=file_data['id'])

    if not existing_file:
        return jsonify({"error": "File not found"}), 404

    # Preserve existing metadata if not provided in update
    if 'name' not in file_data:
        file_data['name'] = existing_file.get('name')
    if 'description' not in file_data:
        file_data['description'] = existing_file.get('description')
    if 'contents' not in file_data:
        file_data['contents'] = existing_file.get('contents')
    if 'always_on' not in file_data:
        file_data['always_on'] = existing_file.get('always_on')
    if 'searchable' not in file_data:
        file_data['searchable'] = existing_file.get('searchable')

    # Check if new attachments are provided (optional - if not provided, keep existing files)
    has_new_attachments = False
    new_files = []
    if 'attachments' in request.files:
        new_files = request.files.getlist('attachments')
        valid_files = [f for f in new_files if f.filename != '']
        if valid_files:
            has_new_attachments = True
            new_files = valid_files

    # If new files are provided, delete old blobs and upload new ones
    if has_new_attachments:
        # Delete old blobs from existing file
        old_files = existing_file.get("files")
        if old_files and isinstance(old_files, list):
            for file_info in old_files:
                if isinstance(file_info, dict) and file_info.get("path"):
                    try:
                        delete_blob(file_info["path"])
                    except Exception as e:
                        import logging
                        logging.getLogger(__name__).warning(f"Failed to delete old blob: {e}")

        # Also handle backward compatibility with blob_url
        old_blob_url = existing_file.get("blob_url")
        if old_blob_url:
            try:
                delete_blob(old_blob_url)
            except Exception as e:
                import logging
                logging.getLogger(__name__).warning(f"Failed to delete old blob_url: {e}")

        # Upload new files - collect all upload results first (same pattern as POST API)
        upload_results = []
        for file in new_files:
            # Validate file extension
            filename = file.filename
            file_ext = os.path.splitext(filename)[1].lower()
            if file_ext not in ALLOWED_EXTENSIONS:
                return jsonify({
                    "error": f"File type not allowed: {file_ext}. Allowed types: {', '.join(ALLOWED_EXTENSIONS)}"
                }), 400

            # Read file data
            file.seek(0, os.SEEK_END)
            file_size = file.tell()
            file.seek(0)

            # Validate file size
            if file_size > MAX_FILE_SIZE:
                return jsonify({
                    "error": f"File size exceeds maximum allowed size of {MAX_FILE_SIZE / (1024 * 1024)}MB"
                }), 400

            file_bytes = file.read()

            # Determine content type (use provided or guess from filename)
            content_type = file_data.get('content_type')
            if not content_type:
                content_type, _ = mimetypes.guess_type(filename)
            if not content_type:
                content_type = 'application/octet-stream'

            try:
                # Upload to blob storage (returns dict with path, filename, size, type, extension, uploaded_at)
                upload_result = upload_file_to_blob(
                    file_type="agents",
                    entity_id=agent_id,
                    file_data=file_bytes,
                    original_filename=filename,
                    content_type=content_type
                )
                upload_results.append(upload_result)
            except ValueError as e:
                return jsonify({"error": str(e)}), 500
            except Exception as e:
                return jsonify({"error": f"Failed to upload file: {str(e)}"}), 500

        # Update file_data with new files array (all files in single array, same as POST API)
        file_data["files"] = upload_results
    else:
        # No new attachments provided - preserve existing files array
        existing_files = existing_file.get("files")
        if existing_files:
            file_data["files"] = existing_files
        # Also preserve blob_url for backward compatibility
        if existing_file.get("blob_url") and not existing_files:
            file_data["blob_url"] = existing_file.get("blob_url")

    # Update the file (with or without new files)
    agent_file_update(agent_id, file_data)

    # Return updated file object
    updated_file = agent_file_get(agent_id=agent_id, file_id=file_data['id'])
    return jsonify(updated_file)


@agent_bp.route('/agent/<agent_id>', methods=["DELETE"])
def agent_delete_route(agent_id) -> Response:
    # Delete all files (blobs) for this agent before deleting the agent
    from services.file_service import delete_all_agent_files
    delete_all_agent_files(agent_id)

    # Then delete the agent
    workflow.workflow_service.agent_delete(agent_id)
    return jsonify({"response": "Success"})


@agent_bp.route('/agent/<agent_id>/file/<file_id>', methods=["DELETE"])
def agent_file_delete_route(agent_id, file_id) -> Response:
    agent_file_delete(agent_id, file_id)
    return jsonify({"response": "Success"})


@agent_bp.route('/workflow/<workflow_id>/notes', methods=['GET'])
def workflow_note_get(workflow_id) -> Response:
    nodes = workflow.workflow_service.notes_get(workflow_id)
    return jsonify(nodes)


@agent_bp.route('/workflow/<workflow_id>/note/<note_id>', methods=['GET'])
def workflow_notes_get(workflow_id, note_id) -> Response:
    nodes = workflow.workflow_service.note_get(workflow_id, note_id)
    return jsonify(nodes)


@agent_bp.route('/workflow/<workflow_id>/note', methods=['POST'])
def workflow_note_add(workflow_id: str) -> Response:
    # note = request.get_json()
    return jsonify(workflow.workflow_service.note_add(workflow_id))


@agent_bp.route('/workflow/<workflow_id>/note', methods=['PUT'])
def workflow_note_update(workflow_id) -> Response:
    workflow_node = request.get_json()
    workflow.workflow_service.note_update(workflow_id, workflow_node)
    return jsonify({'result': 'success'})


@agent_bp.route('/workflow/<workflow_id>/note/<note_id>', methods=['DELETE'])
def workflow_note_delete(workflow_id: str, note_id: str) -> Response:
    workflow.workflow_service.note_delete(workflow_id=workflow_id, note_id=note_id)
    return jsonify({"isDeleted": True})

from services.webhook_service import parse_whatsapp_message, verify_twilio_request, normalize_twilio_event, verify_signature, get_whatsapp_account

@agent_bp.route('/webhook/<type>/<agent_id>/<workflow_id>', methods=['GET'])
def verify_webhook(type,agent_id, workflow_id):
    print(agent_id, workflow_id,"agent_id, workflow_id---------------------=-=-=-=-=")
    if type == "whatsapp":
        hub_mode = request.args.get("hub.mode")
        hub_verify_token = request.args.get("hub.verify_token")
        hub_challenge = request.args.get("hub.challenge")
        print(hub_mode, hub_verify_token, hub_challenge,"hub_mode, hub_verify_token, hub_challenge----------------------------")
        return hub_challenge

    elif type == "twilio-calls":
        return jsonify({"status": "success"}), 200

    elif type == "twilio-sms":
        return jsonify({"status": "success"}), 200

# /webhook-whatsapp/2c3fff67-17ab-4d9e-a76d-57d22f9bd0d5/df90e271-4724-4c02-bdd8-4bb08b9582fa

# https://abdiel-heliotypic-norah.ngrok-free.dev/webhook/whatsapp/2c3fff67-17ab-4d9e-a76d-57d22f9bd0d5/4e819e46-a167-47bd-9980-a6c6299261ca
# 764d5f69-07c9-44d7-bf20-d217b9fbd90a/workflow/a90c5715-5cc9-4e4e-86c7-c73f8a00d084
# https://abdiel-heliotypic-norah.ngrok-free.dev/webhook/twilio-calls/764d5f69-07c9-44d7-bf20-d217b9fbd90a/a90c5715-5cc9-4e4e-86c7-c73f8a00d084
# https://abdiel-heliotypic-norah.ngrok-free.dev/webhook/twilio-sms/764d5f69-07c9-44d7-bf20-d217b9fbd90a/a90c5715-5cc9-4e4e-86c7-c73f8a00d084

@agent_bp.route('/webhook/<type>/<agent_id>/<workflow_id>', methods=['POST'])
def webhook(type, agent_id, workflow_id):

    # For WhatsApp, we need raw payload before parsing for signature verification
    if type == "whatsapp":
        raw_payload = request.get_data(cache=False)
        print(raw_payload,"raw_payload---------------------")
        # Parse JSON from raw payload since get_data() consumes the request body
        try:
            data = json.loads(raw_payload.decode('utf-8'))
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            print(f"Error parsing JSON from raw payload: {e}")
            return jsonify({"status": "error", "error": "Invalid JSON payload"}), 400
        # print(data,"data--111-------------------")
    else:
        data = request.get_json() if request.is_json else request.form.to_dict()
        # print(data,"data-----2222----------------")
    
    # print(data, "data---------------------")

    # Create workflow log
    target_log = workflow.workflow_service.workflow_log_create(
        agent_id=agent_id,
        workflow_id=workflow_id,
        conversation_id=None
    )

    # ==================================================
    # WHATSAPP
    # ==================================================
    if type == "whatsapp":
        print(data,"data------3333---------------")
        # Get signature from header
        signature = request.headers.get("X-Hub-Signature-256")
        
        # Fetch all nodes and find account_id in node configurations
        nodes = workflow.workflow_service.nodes_get(workflow_id)
        account_id = None
        secret_key = None
        
        # Search through all nodes' configurations to find account_id and secret_key
        for node in nodes:
            config = node.get("configuration", {})
            if not account_id and config.get("account_id"):
                account_id = config.get("account_id")
                print(f"Found account_id in node configuration: {account_id}")
            if not secret_key and config.get("secret_key"):
                secret_key = config.get("secret_key")
                print(f"Found secret_key in node configuration")
        
        # Try to extract account_id from payload as fallback
        if not account_id:
            try:
                if isinstance(data, dict):
                    print(f"Data keys: {data.keys()}")
                    if data.get("entry"):
                        entry = data.get("entry", [{}])[0]
                        print(f"Entry: {entry}")
                        account_id = entry.get("id")
                        print(f"Extracted account_id from payload: {account_id}")
            except Exception as e:
                print(f"Error extracting account_id from payload: {e}")
                import traceback
                traceback.print_exc()
        
        # Get account from database using account_id (if found)
        account = None
        if account_id:
            account = get_whatsapp_account(account_id)
            if account:
                print(f"Found account in database for account_id: {account_id}")
                # Get secret_key from database account (prefer database over node config)
                db_secret_key = account.get("secret_key") or account.get("app_secret")
                if db_secret_key:
                    secret_key = db_secret_key
                    print("Using secret_key from database account")
            else:
                print(f"Account not found in database for account_id: {account_id}")
        
        # If account_id not found anywhere, return error
        if not account_id:
            print(f"Account ID not found in node configurations or payload. Data structure: {json.dumps(data, indent=2) if isinstance(data, dict) else str(data)}")
            return jsonify({"status": "error", "error": "Account ID not found in node configurations or payload"}), 400
        
        # Verify signature - require both secret_key and signature
        if not secret_key:
            print("Secret key not found in database or node configuration")
            return jsonify({"status": "error", "error": "Secret key not configured"}), 400
        
        if not signature:
            print("WhatsApp signature header (X-Hub-Signature-256) not found")
            return jsonify({"status": "unauthorized", "error": "Missing signature header"}), 403
        
        # Verify signature
        if not verify_signature(raw_payload, signature, secret_key):
            print("WhatsApp signature verification failed")
            return jsonify({"status": "unauthorized", "error": "Invalid signature"}), 403
        
        # Signature verified, parse WhatsApp message
        event = parse_whatsapp_message(data)
        
        if not event:
            return jsonify({"status": "ignored"}), 200

        # Execute workflow
        workflow.workflow_service.workflow_execute(
            agent_id=agent_id,
            workflow_id=workflow_id,
            parameters={},
            globals={
                "whatsapp_event": event,
                "called_from_agent": agent_id,
                "trace_id": event.get("message_id")
            },
            log=target_log
        )

    # ==================================================
    # TWILIO CALLS
    # ==================================================
    elif type == "twilio-calls":
        # Twilio sends form-encoded data
        # Use request.form directly (MultiDict) - Twilio validator supports it
        # But convert to dict for our processing
        form_dict = request.form.to_dict()
        form_multidict = request.form  # Keep original for validation

        signature = request.headers.get("X-Twilio-Signature")
        if not signature:
            return jsonify({"status": "missing signature"}), 403

        # Construct the URL that Twilio called
        # Try to get the original URL if behind a proxy
        url = request.url
        
        # If behind a proxy, try to reconstruct the public URL
        if request.headers.get('X-Forwarded-Proto'):
            # Reconstruct URL with forwarded protocol and host
            scheme = request.headers.get('X-Forwarded-Proto', request.scheme)
            host = request.headers.get('X-Forwarded-Host', request.host)
            url = f"{scheme}://{host}{request.path}"
            if request.query_string:
                url += f"?{request.query_string.decode()}"
        
        # Debug prints
        # print(f"Signature: {signature}")
        # print(f"Form data (dict): {form_dict}")
        # print(f"Request URL: {url}")
        # print(f"Request scheme: {request.scheme}")
        # print(f"Request host: {request.host}")
        # print(f"Request path: {request.path}")
        # print(f"X-Forwarded-Proto: {request.headers.get('X-Forwarded-Proto')}")
        # print(f"X-Forwarded-Host: {request.headers.get('X-Forwarded-Host')}")
        
        # Try validation with both dict and MultiDict
        # Twilio validator supports MultiDict, so try that first
        is_valid = verify_twilio_request(
            auth_token="784ed39cfaa536b943a55f9b872e8814",
            url=url,
            params=form_multidict,  # Use MultiDict - Twilio validator supports it
            signature=signature
        )
        
        # If that fails, try with dict
        if not is_valid:
            print("Trying with dict instead of MultiDict...")
            is_valid = verify_twilio_request(
                auth_token="784ed39cfaa536b943a55f9b872e8814",
                url=url,
                params=form_dict,
                signature=signature
            )
        
        # Use dict for processing
        form = form_dict

        if not is_valid:
            return jsonify({"status": "invalid"}), 403

        event = normalize_twilio_event("twilio-calls", form)
        print(event,"twilio-calls event---------------------")

        workflow.workflow_service.workflow_execute(
            agent_id=agent_id,
            workflow_id=workflow_id,
            parameters={},
            globals={
                "twilio_event": event,
                "called_from_agent": agent_id,
                "trace_id": form.get("CallSid")
            },
            log=target_log
        )

    # ==================================================
    # TWILIO SMS / MMS
    # ==================================================
    elif type == "twilio-sms":
        form = request.form.to_dict()

        event = normalize_twilio_event("twilio-sms", form)
        print(event,"twilio-sms event---------------------")

        workflow.workflow_service.workflow_execute(
            agent_id=agent_id,
            workflow_id=workflow_id,
            parameters={},
            globals={
                "twilio_event": event,   # ✅ NORMALIZED
                "called_from_agent": agent_id,
                "trace_id": form.get("MessageSid")
            },
            log=target_log
        )

    return jsonify({"status": "success"}), 200






GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
import requests
@agent_bp.route('/oauth/google/callback', methods=['GET'])
def google_oauth_callback():
    code = request.args.get("code")
    print(code,"code---------------------")

    data = {
        "client_id": "",
        "client_secret":"",
        "code": code,
        "grant_type": "authorization_code",
        "redirect_uri": "https://abdiel-heliotypic-norah.ngrok-free.dev/oauth/google/callback"
    }

    r = requests.post(GOOGLE_TOKEN_URL, data=data)
    tokens = r.json()

    # VERY IMPORTANT
    access_token = tokens["access_token"]
    refresh_token = tokens.get("refresh_token")

    print(access_token,"access_token------------\n")
    print(refresh_token,"refresh_token-------------------")

    # Store per-user in DB (encrypted)
    # save_tokens_to_db(
    #     user_id=current_user_id,
    #     provider="gmail",
    #     access_token=access_token,
    #     refresh_token=refresh_token
    # )

    return "Gmail connected successfully"


import base64

def decode_base64(data):
    if not data:
        return ""
    return base64.urlsafe_b64decode(data.encode("UTF-8")).decode("UTF-8", errors="ignore")

@agent_bp.route('/get-mails/<access_token>', methods=['GET'])
def fetch_emails(access_token):
    headers = {
        "Authorization": f"Bearer {access_token}"
    }

    r = requests.get(
        "https://gmail.googleapis.com/gmail/v1/users/me/messages?q=is:unread category:primary",
        headers=headers
    )

    data = r.json()
    print(data,"data---------------")

    results = []

    for msg in data.get("messages", []):
        msg_id = msg["id"]

        res = requests.get(
            f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{msg_id}?format=full",
            headers=headers
        )

        message = res.json()
        # print(message,"message---------")
        payload = message.get("payload", {})
        headers_list = payload.get("headers", [])

        email_data = {
            "id": msg_id,
            "from": None,
            "to": None,
            "subject": None,
            "body": ""
        }

        for h in headers_list:
            if h["name"] == "From":
                email_data["from"] = h["value"]
            elif h["name"] == "To":
                email_data["to"] = h["value"]
            elif h["name"] == "Subject":
                email_data["subject"] = h["value"]

        if "parts" in payload:
            for part in payload["parts"]:
                if part.get("mimeType") == "text/plain":
                    email_data["body"] = decode_base64(
                        part.get("body", {}).get("data")
                    )
        else:
            email_data["body"] = decode_base64(
                payload.get("body", {}).get("data")
            )

        results.append(email_data)

    # start_watch(access_token)

    return results



@agent_bp.route('/gmail/push-event', methods=['POST'])
def gmail_push_event():
    data = request.json
    # email = data["emailAddress"]
    history_id = data["historyId"]

    access_token = ""

    headers = {"Authorization": f"Bearer {access_token}"}

    r = requests.get(
        f"https://gmail.googleapis.com/gmail/v1/users/me/history"
        f"?startHistoryId={history_id}&historyTypes=messageAdded",
        headers=headers
    )

    history = r.json()
    print(history,"history------------------")

    result = []
    for h in history.get("history", []):
        for msg in h.get("messagesAdded", []):
            message_id = msg["message"]["id"]
            result.append(process_message(access_token, message_id))
    
    print(result,"result------------------")

    return result


def process_message(msg_id):
    results = []

    access_token = ""

    headers = {"Authorization": f"Bearer {access_token}"}

    res = requests.get(
        f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{msg_id}?format=full",
        headers=headers
    )

    message = res.json()
    payload = message.get("payload", {})
    headers_list = payload.get("headers", [])

    email_data = {
        "id": msg_id,
        "from": None,
        "to": None,
        "subject": None,
        "body": ""
    }

    for h in headers_list:
        if h["name"] == "From":
            email_data["from"] = h["value"]
        elif h["name"] == "To":
            email_data["to"] = h["value"]
        elif h["name"] == "Subject":
            email_data["subject"] = h["value"]

    if "parts" in payload:
        for part in payload["parts"]:
            if part.get("mimeType") == "text/plain":
                email_data["body"] = decode_base64(
                    part.get("body", {}).get("data")
                )
    else:
        email_data["body"] = decode_base64(
            payload.get("body", {}).get("data")
        )

    results.append(email_data)

    return results

def refresh_access_token(refresh_token):
    data = {
        "client_id": "",
        "client_secret": "",
        "refresh_token": refresh_token,
        "grant_type": "refresh_token"
    }

    r = requests.post(GOOGLE_TOKEN_URL, data=data)
    return r.json()["access_token"]


def start_watch(access_token):
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }

    data = {
        "labelIds": ["INBOX"],
        "topicName": "projects/mailtrigger/topics/gmail-push"
    }

    r = requests.post(
        "https://gmail.googleapis.com/gmail/v1/users/me/watch",
        headers=headers,
        json=data
    )

    return r.json()
