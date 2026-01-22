import json
import mimetypes
import os

from flask import Blueprint, request, jsonify, Response

from services.blob_storage_service import upload_file_to_blob
from services.chat_service import conversations_get, conversation_add, \
    message_add, conversation_get, log_event_get, logs_get, conversation_delete, message_get_by_id
from services.message_render_service import download_message_as_file

conversation_bp = Blueprint('conversation', __name__)


@conversation_bp.route('/conversations/<agent_id>', methods=['GET'])
def conversations_get_route(agent_id) -> Response:
    user_email = request.headers.get("x-user-email")
    if user_email is None:
        return jsonify({"error": "User is not authenticated."})
    conversations = conversations_get(user_email, agent_id)
    return jsonify(conversations)


@conversation_bp.route('/conversation/<conversation_id>', methods=['GET'])
def conversation_get_route(conversation_id) -> Response:
    user_email = request.headers.get("x-user-email")
    if user_email is None:
        return jsonify({"error": "User is not authenticated."})
    conversation = conversation_get(user_id=user_email, conversation_id=conversation_id)
    return jsonify(conversation)


@conversation_bp.route('/conversation/<conversation_id>', methods=['DELETE'])
def conversation_delete_route(conversation_id) -> Response:
    # Delete all files (blobs) for this conversation before deleting the conversation
    from services.blob_storage_service import delete_conversation_files
    delete_conversation_files(conversation_id)

    # Then delete the conversation
    conversation_delete(conversation_id=conversation_id)
    return jsonify({"response": "Success"})


@conversation_bp.route('/conversation/<agent_id>', methods=["POST"])
def conversation_add_route(agent_id) -> Response:
    conversation = request.get_json()

    user_email = request.headers.get("x-user-email")
    if user_email is None:
        return jsonify({"error": "User is not authenticated."})
    conversation = conversation_add(user_id=user_email, agent_id=agent_id, conversation=conversation)
    return jsonify(conversation)


@conversation_bp.route('/conversation/<conversation_id>/message', methods=["POST"])
def message_add_route(conversation_id) -> Response:
    # Allowed file extensions
    ALLOWED_EXTENSIONS = {'.pdf', '.jpg', '.jpeg', '.png', '.gif', '.doc', '.docx', '.xls', '.xlsx', '.csv'}
    MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB

    # Get message data from request (supports both JSON and multipart/form-data)
    message_data = {}

    # Try to get data from JSON first (for JSON requests)
    if request.is_json:
        message_data = request.get_json() or {}

    # Also check form data (for multipart/form-data requests)
    if request.form:
        # Try to get JSON from form data field
        json_data = request.form.get('data')
        if json_data:
            try:
                message_data = json.loads(json_data)
            except:
                pass
        # Also check individual form fields (overrides JSON if present)
        if 'role' in request.form:
            message_data['role'] = request.form.get('role')
        if 'content' in request.form:
            message_data['content'] = request.form.get('content')

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
        message = message_add(conversation_id=conversation_id, message=message_data)
        return jsonify(message)

    # Process files if attachments are provided
    uploaded_files = []
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

        # Determine content type
        content_type, _ = mimetypes.guess_type(filename)
        if not content_type:
            content_type = 'application/octet-stream'

        try:
            # Upload to blob storage with conversation path
            upload_result = upload_file_to_blob(
                file_type="conversations",
                entity_id=conversation_id,
                file_data=file_bytes,
                original_filename=filename,
                content_type=content_type
            )
            uploaded_files.append(upload_result)
        except Exception as e:
            return jsonify({"error": f"Failed to upload file: {str(e)}"}), 500

    # Add files array to message data
    message_data["files"] = uploaded_files

    # Create message with files
    message = message_add(conversation_id=conversation_id, message=message_data)
    return jsonify(message)


@conversation_bp.route('/conversation/<conversation_id>/message/<message_id>/logs', methods=["GET"])
def message_logs_get_route(conversation_id, message_id) -> Response:
    logs = logs_get(conversation_id=conversation_id, message_id=message_id)
    return jsonify(logs)


@conversation_bp.route('/workflow/<workflow_id>/log/<log_id>/event/<event_id>', methods=["GET"])
def message_log_events_get_route(workflow_id, log_id, event_id) -> Response:
    log = log_event_get(workflow_id=workflow_id, log_id=log_id, event_id=event_id)
    return jsonify(log)


@conversation_bp.route('/message/<message_id>/download/<download_type>', methods=['GET'])
def message_download_route(message_id, download_type) -> Response:
    """
    Download a message as PDF or Excel file.
    
    Args:
        message_id: The ID of the message to download
        download_type: 'pdf' or 'excel'
    
    Returns:
        File download response
    """
    # Validate authentication
    user_email = request.headers.get("x-user-email")
    if user_email is None:
        return jsonify({"error": "User is not authenticated."}), 401

    # Validate download type
    download_type_lower = download_type.lower()
    if download_type_lower not in ['pdf', 'excel']:
        return jsonify({"error": f"Invalid download type: {download_type}. Must be 'pdf' or 'excel'."}), 400

    try:
        # Retrieve message
        message = message_get_by_id(message_id=message_id, user_id=user_email)

        if message is None:
            return jsonify({"error": "Message not found or access denied."}), 404

        # Generate and return file
        return download_message_as_file(message, download_type_lower)

    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"Error generating download for message {message_id}: {e}")
        return jsonify({"error": "Failed to generate download file."}), 500
