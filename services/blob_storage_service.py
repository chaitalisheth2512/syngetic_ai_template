import os
from azure.storage.blob import BlobServiceClient, BlobClient, ContentSettings, BlobSasPermissions, generate_blob_sas
from azure.storage.blob._shared_access_signature import BlobSharedAccessSignature
from azure.core.exceptions import AzureError
from datetime import datetime, timedelta, timezone
import logging
import re
from urllib.parse import unquote
import uuid

logger = logging.getLogger(__name__)

# Container name for agent files
CONTAINER_NAME = "agent-files"

# Initialize blob service client
_blob_service_client = None

def get_blob_service_client():
    """Get or create the blob service client singleton."""
    global _blob_service_client
    if _blob_service_client is None:
        connection_string = os.environ.get('AZURE_STORAGE_CONNECTION_STRING')
        if not connection_string:
            raise ValueError("AZURE_STORAGE_CONNECTION_STRING environment variable is not set")
        _blob_service_client = BlobServiceClient.from_connection_string(connection_string)
        # Ensure container exists
        ensure_container_exists()
    return _blob_service_client

def ensure_container_exists():
    """Create the container if it doesn't exist."""
    try:
        blob_service_client = get_blob_service_client()
        container_client = blob_service_client.get_container_client(CONTAINER_NAME)
        if not container_client.exists():
            container_client.create_container()
            logger.info(f"Created container: {CONTAINER_NAME}")
    except AzureError as e:
        logger.error(f"Error ensuring container exists: {e}")
        raise

def get_blob_filename(original_filename: str) -> str:
    """
    Generate a unique blob filename with timestamp and UUID.
    Format: {timestamp}_{short_uuid}.{ext}
    
    Args:
        original_filename: The original filename
    
    Returns:
        Unique filename: e.g., "1735392000_abc123.pdf"
    """
    # Get file extension
    ext = os.path.splitext(original_filename)[1] or ""
    if ext:
        ext = ext.lower()
    
    # Generate timestamp (Unix epoch)
    timestamp = int(datetime.now(timezone.utc).timestamp())
    
    # Generate short UUID (first 8 characters)
    unique_id = str(uuid.uuid4()).replace('-', '')[:8]
    
    return f"{timestamp}_{unique_id}{ext}"

def get_blob_path(file_type: str, entity_id: str, original_filename: str) -> str:
    """
    Generate the blob path for a file with hierarchical structure.
    Format: {file_type}/{entity_id}/{timestamp}_{uuid}.{ext}
    
    Args:
        file_type: Type of file - "agents" or "conversations"
        entity_id: The agent ID or conversation ID
        original_filename: The original filename
    
    Returns:
        Blob path: e.g., "agents/agent123/1735392000_abc123.pdf" or "conversations/conv456/1735392000_abc123.pdf"
    """
    blob_filename = get_blob_filename(original_filename)
    return f"{file_type}/{entity_id}/{blob_filename}"

def upload_file_to_blob(file_type: str, entity_id: str, file_data: bytes, original_filename: str, content_type: str = None) -> dict:
    """
    Upload a file to Azure Blob Storage.
    
    Args:
        file_type: Type of file - "agents" or "conversations"
        entity_id: The agent ID or conversation ID
        file_data: The file data as bytes
        original_filename: The original filename
        content_type: Optional content type (MIME type)
    
    Returns:
        Dictionary with:
            - "path": The full blob URL
            - "filename": The original filename
            - "size": File size in bytes
            - "type": Content type (MIME type)
            - "extension": File extension
            - "uploaded_at": Upload timestamp (ISO format)
    
    Raises:
        ValueError: If connection string is not set
        AzureError: If upload fails
    """
    try:
        blob_service_client = get_blob_service_client()
        blob_path = get_blob_path(file_type, entity_id, original_filename)
        blob_client = blob_service_client.get_blob_client(container=CONTAINER_NAME, blob=blob_path)
        
        # Get file size
        file_size = len(file_data)
        
        # Get file extension
        file_ext = os.path.splitext(original_filename)[1].lower()
        
        # Determine content type if not provided
        if not content_type:
            import mimetypes
            content_type, _ = mimetypes.guess_type(original_filename)
            if not content_type:
                content_type = 'application/octet-stream'
        
        # Upload file with content type
        content_settings = ContentSettings(content_type=content_type)
        blob_client.upload_blob(file_data, overwrite=True, content_settings=content_settings)
        
        # Get upload timestamp
        uploaded_at = datetime.now(timezone.utc).isoformat()
        
        # Return the full blob URL and file metadata
        blob_url = blob_client.url
        logger.info(f"Uploaded file to blob: {blob_url}, size: {file_size} bytes")
        return {
            "path": blob_url,
            "filename": original_filename,
            "size": file_size,
            "type": content_type,
            "extension": file_ext,
            "uploaded_at": uploaded_at
        }
    
    except AzureError as e:
        logger.error(f"Error uploading file to blob storage: {e}")
        raise
    except Exception as e:
        logger.error(f"Unexpected error uploading file: {e}")
        raise

def _get_account_key_from_connection_string():
    """Extract account key from connection string."""
    connection_string = os.environ.get('AZURE_STORAGE_CONNECTION_STRING')
    if not connection_string:
        raise ValueError("AZURE_STORAGE_CONNECTION_STRING environment variable is not set")
    
    # Parse connection string to get account key
    # Format: AccountKey=key_value;...
    match = re.search(r'AccountKey=([^;]+)', connection_string)
    if not match:
        raise ValueError("Could not extract account key from connection string")
    return match.group(1)

def _get_account_name_from_connection_string():
    """Extract account name from connection string."""
    connection_string = os.environ.get('AZURE_STORAGE_CONNECTION_STRING')
    if not connection_string:
        raise ValueError("AZURE_STORAGE_CONNECTION_STRING environment variable is not set")
    
    # Parse connection string to get account name
    # Format: AccountName=account_name;...
    match = re.search(r'AccountName=([^;]+)', connection_string)
    if not match:
        raise ValueError("Could not extract account name from connection string")
    return match.group(1)

def generate_sas_url(blob_url: str, expiry_hours: int = 1) -> str:
    """
    Generate a SAS (Shared Access Signature) URL for a blob that allows read access.
    
    Args:
        blob_url: The full URL of the blob
        expiry_hours: Number of hours the SAS URL should be valid (default: 1 hour)
    
    Returns:
        The SAS URL with read permissions
    
    Raises:
        ValueError: If blob URL format is invalid
        AzureError: If SAS generation fails
    """
    try:
        # Remove any existing query parameters from blob_url (in case it already has SAS token)
        blob_url_clean = blob_url.split('?')[0]
        
        # Extract container and blob name from URL
        # URL format: https://{account}.blob.core.windows.net/{container}/{blob_path}
        parts = blob_url_clean.split(f"/{CONTAINER_NAME}/")
        if len(parts) != 2:
            raise ValueError(f"Invalid blob URL format: {blob_url}")
        
        # URL-decode the blob path (spaces and special chars might be encoded)
        blob_path = unquote(parts[1])
        
        # Get account name and key from connection string
        account_name = _get_account_name_from_connection_string()
        account_key = _get_account_key_from_connection_string()
        
        # Use UTC timezone explicitly for expiry
        expiry_time = datetime.now(timezone.utc) + timedelta(hours=expiry_hours)
        
        # Generate SAS token with read permissions
        # Use generate_blob_sas which properly handles the signature
        sas_token = generate_blob_sas(
            account_name=account_name,
            container_name=CONTAINER_NAME,
            blob_name=blob_path,
            account_key=account_key,
            permission=BlobSasPermissions(read=True),
            expiry=expiry_time
        )
        
        # Return the clean blob URL with SAS token
        sas_url = f"{blob_url_clean}?{sas_token}"
        logger.info(f"Generated SAS URL for blob: {blob_path}, expires at: {expiry_time}")
        return sas_url
    
    except AzureError as e:
        logger.error(f"Error generating SAS URL: {e}")
        raise
    except Exception as e:
        logger.error(f"Unexpected error generating SAS URL: {e}")
        raise

def download_blob_content(blob_url: str) -> bytes:
    """
    Download the content of a blob from Azure Blob Storage.
    
    Args:
        blob_url: The full URL of the blob
    
    Returns:
        The blob content as bytes
    
    Raises:
        ValueError: If blob URL format is invalid
        AzureError: If download fails
    """
    try:
        blob_service_client = get_blob_service_client()
        
        # Extract container and blob name from URL
        # URL format: https://{account}.blob.core.windows.net/{container}/{blob_path}
        parts = blob_url.split(f"/{CONTAINER_NAME}/")
        if len(parts) != 2:
            raise ValueError(f"Invalid blob URL format: {blob_url}")
        
        # Remove any query parameters
        blob_path = parts[1].split('?')[0]
        # URL-decode the blob path
        blob_path = unquote(blob_path)
        
        blob_client = blob_service_client.get_blob_client(container=CONTAINER_NAME, blob=blob_path)
        
        if not blob_client.exists():
            raise ValueError(f"Blob does not exist: {blob_path}")
        
        # Download blob content
        blob_data = blob_client.download_blob()
        content = blob_data.readall()
        logger.info(f"Downloaded blob content: {blob_path}, size: {len(content)} bytes")
        return content
    
    except AzureError as e:
        logger.error(f"Error downloading blob content: {e}")
        raise
    except Exception as e:
        logger.error(f"Unexpected error downloading blob content: {e}")
        raise

def delete_agent_files(agent_id: str) -> bool:
    """
    Delete all blobs for an agent from Azure Blob Storage.
    
    Args:
        agent_id: The agent ID
    
    Returns:
        True if all files deleted successfully, False otherwise
    """
    try:
        blob_service_client = get_blob_service_client()
        container_client = blob_service_client.get_container_client(CONTAINER_NAME)
        
        # List all blobs with the agents/agent_id prefix
        blob_prefix = f"agents/{agent_id}/"
        blobs = container_client.list_blobs(name_starts_with=blob_prefix)
        
        deleted_count = 0
        failed_count = 0
        
        for blob in blobs:
            try:
                blob_client = container_client.get_blob_client(blob.name)
                if blob_client.exists():
                    blob_client.delete_blob()
                    deleted_count += 1
                    logger.info(f"Deleted blob: {blob.name}")
            except Exception as e:
                logger.error(f"Error deleting blob {blob.name}: {e}")
                failed_count += 1
        
        logger.info(f"Deleted {deleted_count} blobs for agent {agent_id}, {failed_count} failed")
        return failed_count == 0
    
    except AzureError as e:
        logger.error(f"Error deleting agent files: {e}")
        return False
    except Exception as e:
        logger.error(f"Unexpected error deleting agent files: {e}")
        return False

def get_agent_blob_paths(agent_id: str) -> list:
    """
    Get all blob paths for an agent.
    
    Args:
        agent_id: The agent ID
    
    Returns:
        List of blob paths (relative to container)
    """
    try:
        blob_service_client = get_blob_service_client()
        container_client = blob_service_client.get_container_client(CONTAINER_NAME)
        
        # List all blobs with the agents/agent_id prefix
        blob_prefix = f"agents/{agent_id}/"
        blobs = container_client.list_blobs(name_starts_with=blob_prefix)
        
        return [blob.name for blob in blobs]
    
    except AzureError as e:
        logger.error(f"Error getting agent blob paths: {e}")
        return []
    except Exception as e:
        logger.error(f"Unexpected error getting agent blob paths: {e}")
        return []

def delete_conversation_files(conversation_id: str) -> bool:
    """
    Delete all blobs for a conversation from Azure Blob Storage.
    
    Args:
        conversation_id: The conversation ID
    
    Returns:
        True if all files deleted successfully, False otherwise
    """
    try:
        blob_service_client = get_blob_service_client()
        container_client = blob_service_client.get_container_client(CONTAINER_NAME)
        
        # List all blobs with the conversations/conversation_id prefix
        blob_prefix = f"conversations/{conversation_id}/"
        blobs = container_client.list_blobs(name_starts_with=blob_prefix)
        
        deleted_count = 0
        failed_count = 0
        
        for blob in blobs:
            try:
                blob_client = container_client.get_blob_client(blob.name)
                if blob_client.exists():
                    blob_client.delete_blob()
                    deleted_count += 1
                    logger.info(f"Deleted blob: {blob.name}")
            except Exception as e:
                logger.error(f"Error deleting blob {blob.name}: {e}")
                failed_count += 1
        
        logger.info(f"Deleted {deleted_count} blobs for conversation {conversation_id}, {failed_count} failed")
        return failed_count == 0
    
    except AzureError as e:
        logger.error(f"Error deleting conversation files: {e}")
        return False
    except Exception as e:
        logger.error(f"Unexpected error deleting conversation files: {e}")
        return False

def delete_blob(blob_url: str) -> bool:
    """
    Delete a blob from Azure Blob Storage using its URL.
    
    Args:
        blob_url: The full URL of the blob to delete
    
    Returns:
        True if deleted successfully, False otherwise
    """
    try:
        blob_service_client = get_blob_service_client()
        
        # Extract container and blob name from URL
        # URL format: https://{account}.blob.core.windows.net/{container}/{blob_path}
        parts = blob_url.split(f"/{CONTAINER_NAME}/")
        if len(parts) != 2:
            logger.warning(f"Invalid blob URL format: {blob_url}")
            return False
        
        blob_path = parts[1]
        blob_client = blob_service_client.get_blob_client(container=CONTAINER_NAME, blob=blob_path)
        
        if blob_client.exists():
            blob_client.delete_blob()
            logger.info(f"Deleted blob: {blob_url}")
            return True
        else:
            logger.warning(f"Blob does not exist: {blob_url}")
            return False
    
    except AzureError as e:
        logger.error(f"Error deleting blob: {e}")
        return False
    except Exception as e:
        logger.error(f"Unexpected error deleting blob: {e}")
        return False

