import os
import requests
import json
from datetime import date
from datetime import datetime, timezone
from cosmos_interface import user_container, agent_container, cosmos_getbyid, cosmos_getbypartition, cosmos_updatefields
from azure.cosmos import CosmosDict
from azure.cosmos.exceptions import CosmosResourceNotFoundError
import uuid
from simpleeval import simple_eval
from typing import Annotated, Optional, TypedDict, List,  TypeVar, cast, Callable, Any
import workflow.workflow_service

def agent_files_get(agent_id:str,contents:bool=False,always_on:bool=False, searchable:bool=False):
    
    query = f"""
   SELECT c.id, c.name, c.description, c.searchable, c.always_on, c.files, c.blob_url,
   """
    if contents==False:
       query += f"""
        (
        SUBSTRING(c.contents, 0, 100)
        ||
        IIF(LENGTH(c.contents) > 100, '...', '')
        ) AS preview 
    """
    else:
        query += "c.contents "
    query += f"""
        FROM c WHERE c.type="file"
        """
    
    if always_on == True:
        query += " AND c.always_on=true"
    if searchable == True:
        query += " AND c.searchable=true"

    items = agent_container.query_items(
    query=query,
    partition_key=agent_id
    )
    serializedItems = []
    for item in items:
        # Calculate total file size from files array if available
        total_size = 0
        file_count = 0
        if item.get("files") and isinstance(item["files"], list):
            file_count = len(item["files"])
            for file_info in item["files"]:
                if isinstance(file_info, dict) and file_info.get("size"):
                    total_size += file_info.get("size", 0)
        
        # Add computed fields for easier listing
        item["total_file_size"] = total_size
        item["file_count"] = file_count
        
        serializedItems.append(item)
    return serializedItems

def agent_file_get(agent_id:str,file_id:str):
    try:
        file = cosmos_getbyid(container=agent_container,id=file_id,partition_key=agent_id)
        if isinstance(file, CosmosDict):
            # Calculate total file size from files array if available
            total_size = 0
            file_count = 0
            if file.get("files") and isinstance(file["files"], list):
                file_count = len(file["files"])
                for file_info in file["files"]:
                    if isinstance(file_info, dict) and file_info.get("size"):
                        total_size += file_info.get("size", 0)
            
            # Add computed fields for easier listing
            file["total_file_size"] = total_size
            file["file_count"] = file_count
            return file
    except CosmosResourceNotFoundError:
        return None
    return None

def agent_file_add(agent_id:str, file:Any):
    file_id = str(uuid.uuid4())
    
    # Handle files array (new structure) or blob_url (backward compatibility)
    files_array = file.get("files")
    if not files_array and file.get("blob_url"):
        # Migrate old blob_url to files array format
        files_array = [{
            "filename": file.get("name", "file"),
            "path": file["blob_url"]
        }]
    
    file_obj = {
        "agent_id":agent_id,
        "type":"file",
        "id":"file_" + file_id,
        "name":file["name"],
        "description":file.get("description"),
        "contents":file.get("contents"),
        # Note: content_type is stored in files array items, not at main level
        "always_on":file.get("always_on"),
        "searchable":file.get("searchable"),
        "files": files_array if files_array else None
    }
    
    # Keep blob_url for backward compatibility during migration
    if file.get("blob_url") and not files_array:
        file_obj["blob_url"] = file.get("blob_url")
    
    agent_container.upsert_item(
            file_obj
        )
    workflow.workflow_service.agent_refresh_context(agent_id)
    return file_obj

def agent_file_update(agent_id:str,file:Any):
    # Handle files array (new structure) or blob_url (backward compatibility)
    files_array = file.get("files")
    if not files_array and file.get("blob_url"):
        # Migrate old blob_url to files array format
        existing_file = cosmos_getbyid(container=agent_container,id=file["id"],partition_key=agent_id)
        if existing_file:
            files_array = [{
                "filename": file.get("name", existing_file.get("name", "file")),
                "path": file["blob_url"]
            }]
            file["files"] = files_array
    
    update_fields = ["name","description","contents","always_on","searchable","files"]
    # Keep blob_url in update fields for backward compatibility
    if file.get("blob_url"):
        update_fields.append("blob_url")
    
    cosmos_updatefields(container=agent_container,id=file["id"],partition_key=agent_id,value=file,fields=update_fields)
    workflow.workflow_service.agent_refresh_context(agent_id)

def agent_file_delete(agent_id:str,file_id:str):
    # Get file to check if it has files or blob_url before deleting
    import logging
    logger = logging.getLogger(__name__)
    
    try:
        file = cosmos_getbyid(container=agent_container,id=file_id,partition_key=agent_id)
        if file and isinstance(file, CosmosDict):
            # Import here to avoid circular dependency
            from services.blob_storage_service import delete_blob
            
            # Handle files array (new structure)
            files_array = file.get("files")
            if files_array and isinstance(files_array, list):
                for file_info in files_array:
                    if isinstance(file_info, dict) and file_info.get("path"):
                        blob_url = file_info["path"]
                        logger.info(f"Deleting blob for file {file_id}: {blob_url}")
                        blob_deleted = delete_blob(blob_url)
                        if blob_deleted:
                            logger.info(f"Successfully deleted blob for file {file_id}")
                        else:
                            logger.warning(f"Failed to delete blob for file {file_id}, but continuing with file deletion")
            
            # Handle backward compatibility with blob_url
            blob_url = file.get("blob_url")
            if blob_url:
                logger.info(f"Deleting blob (legacy) for file {file_id}: {blob_url}")
                blob_deleted = delete_blob(blob_url)
                if blob_deleted:
                    logger.info(f"Successfully deleted blob (legacy) for file {file_id}")
                else:
                    logger.warning(f"Failed to delete blob (legacy) for file {file_id}, but continuing with file deletion")
    except CosmosResourceNotFoundError:
        # File doesn't exist, nothing to delete
        pass
    except Exception as e:
        # Log error but don't fail the delete operation - still delete from Cosmos DB
        logger.error(f"Error deleting blob for file {file_id}: {e}", exc_info=True)
    
    # Delete file from Cosmos DB (even if blob deletion failed)
    agent_container.delete_item(item=file_id,partition_key=agent_id)
    workflow.workflow_service.agent_refresh_context(agent_id)

def delete_all_agent_files(agent_id:str):
    """
    Delete all files (blobs) for an agent from Azure Blob Storage.
    This is called when an agent is deleted.
    
    Args:
        agent_id: The agent ID
    """
    import logging
    logger = logging.getLogger(__name__)
    
    try:
        from services.blob_storage_service import delete_agent_files
        logger.info(f"Deleting all blobs for agent {agent_id}")
        deleted = delete_agent_files(agent_id)
        if deleted:
            logger.info(f"Successfully deleted all blobs for agent {agent_id}")
        else:
            logger.warning(f"Some blobs may not have been deleted for agent {agent_id}")
    except Exception as e:
        logger.error(f"Error deleting all agent files for agent {agent_id}: {e}", exc_info=True)

    