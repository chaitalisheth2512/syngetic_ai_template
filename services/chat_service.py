import os
import requests
import json
import base64
from openai import AzureOpenAI
from cosmos_interface import workflow_container, agent_container, conversation_container, cosmos_getbyid, cosmos_getbypartition, cosmos_updatefields
import workflow.workflow_service
from jinja2 import Template, TemplateSyntaxError
from datetime import date
from datetime import datetime, timezone
today = date.today()
import re
from cachetools import TTLCache
import uuid
from simpleeval import simple_eval
from typing import Annotated, Optional, TypedDict, List,  TypeVar, cast, Callable, Any
from services.file_service import agent_file_add, agent_file_get, agent_file_update, agent_files_get, agent_file_delete
from services.blob_storage_service import download_blob_content
from services.summary_service import generate_tts_summary
from services.guardrails_service import check_input_guardrails, check_output_guardrails
from azure.cosmos.exceptions import CosmosResourceNotFoundError
from azure.cosmos import CosmosDict


cache = TTLCache(maxsize=100,ttl=600)


class GlobalFunctions:
    def simple_math(self,equations:List[Any],agent_id=None):
        results = {}
        for category in equations:
            results[category["category"]] = simple_eval(category["equation"])
            print(category["category"] + ": " + category["equation"])
        return json.dumps(results)
    def document_query(self,agent_id,document_id:str):
        file = agent_file_get(agent_id=agent_id,file_id=document_id)
        if file is None:
            return json.dumps({"error": "File not found"})
        
        # Get file content - check contents field, files array, or blob_url (backward compat)
        file_content = file.get("contents")
        
        # If no contents, try to get from files array (new structure)
        if not file_content:
            files_array = file.get("files")
            if files_array and isinstance(files_array, list) and len(files_array) > 0:
                # Use first file in array
                file_info = files_array[0]
                if isinstance(file_info, dict) and file_info.get("path"):
                    try:
                        blob_content = download_blob_content(file_info["path"])
                        # Try to decode as text, fallback to binary indicator
                        try:
                            file_content = blob_content.decode('utf-8')
                        except UnicodeDecodeError:
                            # For binary files, indicate it's a binary file
                            file_type = file_info.get('type', 'unknown')
                            file_content = f"[Binary file: {file_info.get('filename', file.get('name', 'file'))} - {len(blob_content)} bytes. Content type: {file_type}]"
                        
                        # Update file dict with downloaded content
                        file["contents"] = file_content
                    except Exception as e:
                        import logging
                        logging.getLogger(__name__).warning(f"Failed to download blob content for file {document_id}: {e}")
                        file["contents"] = f"[File available but content could not be retrieved: {file_info.get('filename', file.get('name', 'file'))}]"
        
        # If still no content, try backward compatibility with blob_url
        if not file_content and file.get("blob_url"):
            try:
                blob_content = download_blob_content(file["blob_url"])
                # Try to decode as text, fallback to base64 or binary indicator
                try:
                    file_content = blob_content.decode('utf-8')
                except UnicodeDecodeError:
                    # For binary files, indicate it's a binary file
                    # Try to get type from files array, fallback to unknown
                    file_type = 'unknown'
                    files_array = file.get("files")
                    if files_array and isinstance(files_array, list) and len(files_array) > 0:
                        file_type = files_array[0].get('type', 'unknown')
                    file_content = f"[Binary file: {file.get('name', 'file')} - {len(blob_content)} bytes. Content type: {file_type}]"
                
                # Update file dict with downloaded content
                file["contents"] = file_content
            except Exception as e:
                import logging
                logging.getLogger(__name__).warning(f"Failed to download blob content for file {document_id}: {e}")
                file["contents"] = f"[File available but content could not be retrieved: {file.get('name', 'file')}]"
        
        return json.dumps(file)

# Model name - should match your Azure OpenAI deployment name
# Can be overridden via OPENAI_MODEL environment variable
OPENAI_MODEL = os.environ.get('OPENAI_MODEL', 'gpt-4.1')
OPENAI_ENDPOINT = 'https://cynthetixopenai.openai.azure.com/'
OPENAI_API_KEY = os.environ.get('CYNTHETIX_OPENAI_API_KEY')
OPENAI_API_VERSION = '2025-03-01-preview'

def openai_query(body):
    client = AzureOpenAI(
        api_version=OPENAI_API_VERSION,
        azure_endpoint=OPENAI_ENDPOINT,
        api_key=OPENAI_API_KEY
    )
    
    body['model']=OPENAI_MODEL 
    body["tools"] = [
    {
        "type": "web_search"
    }
]
    response = client.responses.create(**body)
    # print(response,"response-------------------")
    return response

def process_file_attachments(file_info_list: List[dict]) -> tuple[str, bool]:
    """
    Process file attachments and return formatted content string and whether images were included.
    
    Args:
        file_info_list: List of file info dictionaries with 'path', 'filename', 'type', etc.
    
    Returns:
        Tuple of (formatted_content_string, has_images)
    """
    file_contents = []
    has_images = False
    image_mime_types = {'image/jpeg', 'image/jpg', 'image/png', 'image/gif', 'image/webp'}
    
    for file_info in file_info_list:
        if not isinstance(file_info, dict) or not file_info.get("path"):
            continue
            
        try:
            blob_content = download_blob_content(file_info["path"])
            file_type = file_info.get('type', 'unknown').lower()
            filename = file_info.get('filename', 'file')
            
            # Check if it's an image
            is_image = file_type in image_mime_types or file_type.startswith('image/')
            
            if is_image:
                # Base64 encode image for inclusion
                try:
                    base64_image = base64.b64encode(blob_content).decode('utf-8')
                    # Create data URI - include full base64 for vision API compatibility
                    mime_type = file_info.get('type', 'image/png')
                    data_uri = f"data:{mime_type};base64,{base64_image}"
                    file_contents.append(f"File: {filename}\n[Image: {mime_type}, {len(blob_content)} bytes]\nBase64 Data URI: {data_uri}")
                    has_images = True
                except Exception as e:
                    import logging
                    logging.getLogger(__name__).warning(f"Failed to encode image {filename}: {e}")
                    file_contents.append(f"File: {filename} ({file_info.get('type', 'unknown')}, {len(blob_content)} bytes) - [Image encoding failed]")
            else:
                # Try to decode as text
                try:
                    file_content = blob_content.decode('utf-8')
                    file_contents.append(f"File: {filename}\nContent:\n{file_content}")
                except UnicodeDecodeError:
                    # For other binary files, include metadata
                    file_size = file_info.get('size', len(blob_content))
                    file_contents.append(f"File: {filename} ({file_info.get('type', 'unknown')}, {file_size} bytes) - [Binary file content]")
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning(f"Failed to download file content: {e}")
            file_contents.append(f"File: {file_info.get('filename', 'file')} - [File available but content could not be retrieved]")
    
    formatted_content = "\n\n".join(file_contents) if file_contents else ""
    return formatted_content, has_images

def is_valid_json_with_key(s, key):
    try:
        data = json.loads(s)
        if isinstance(data, dict) and key in data:
            return data
    except (json.JSONDecodeError, TypeError):
        pass
    return None


globalFunctions = [
    {
        "name":"global---simple_math",
        "type":"function",
        "description":"Performs simple math calculations on string equations. Can split equation requests into a list of categories to receive the answer to multiple equations at once.",
        "parameters":{
            "type":"object",
            "additionalProperties":False,
            "properties":
            {
                "equations":
                {
                    "type":"array",
                    "description":"List of equations and their corresponding category to map the results",
                    "items":
                    {
                        "type":"object",
                        "properties":
                        {
                            "category":
                            {
                                "type":"string"
                            },
                            "equation":
                            {
                                "type":"string"
                            }
                        },
                        "required":["category","equation"]
                    }
                }
            },
            "required":["equation"]
        }
    },
    {
        "name":"global---document_query",
        "type":"function",
        "description":"Queries for the contents of a document by a given ID",
        "parameters":{
            "type":"object",
            "additionalProperties":False,
            "properties":
            {
                "document_id":
                {
                    "type":"string"
                }
            },
            "required":["document_id"]
        }
    }
]


def query_processworkflows(agent_id,body,conversation_id:str | None,logs,debug=None, metadata=[], agent=None):
    
    response = openai_query(body)
    toolUsed = False
    for output in response.output:
        if output.type != "function_call":
            # Check if output has content attribute (ResponseFunctionWebSearch doesn't have it)
            if hasattr(output, 'content') and output.content and len(output.content) > 0:
                data = is_valid_json_with_key(output.content[0].text,"jinja2")
                if data is not None:
                    try:
                        template = Template(data["jinja2"])
                    except TemplateSyntaxError as e:
                        body["previous_response_id"] = response.id
                        body["input"].append({
                            "role":"assistant",
                            "content":f"Jinja2 Parsing failed with error: {e}. I need to try again"
                        })
                        print(e)
                        return query_processworkflows(agent_id=agent_id,body=body,conversation_id=conversation_id, logs=logs, metadata=metadata, agent=agent)
            continue
        result = ""
        toolUsed = True
        arguments = json.loads(output.arguments)
        if str(output.name).startswith("global---"):
            function_name = str(output.name).split("---")[1]
            finalytixPlugin = GlobalFunctions()
            method = getattr(finalytixPlugin,function_name)
            try:
                result = {"responses":[method(**arguments,agent_id=agent_id)]}
            except Exception as exception:
                result = {"responses":exception}
        else:
            workflow_id = arguments["workflow_id"]
            globals = {"Chat History":body.get("previous_response_id")}
            try:
                if (debug==None):
                    log = workflow.workflow_service.workflow_log_create(agent_id=agent_id, workflow_id=workflow_id, conversation_id=conversation_id)
                    logs.append(log)
                    result = workflow.workflow_service.workflow_execute(agent_id=agent_id,workflow_id=workflow_id,parameters=arguments,globals=globals,log=log)
                    if "metadata" in result and len(result["metadata"])>0:
                        metadata = metadata + result["metadata"]
      
                else:
                    result = workflow.workflow_service.workflow_debug(agent_id=agent_id,workflow_id=workflow_id,parameters=arguments,state_id=None, globals=globals)
                    return {"responses":result}
            except Exception as exception:
                result = {"responses":exception}        
        body["input"].append({
            "type":"function_call_output",
            "call_id":output.call_id,
            "output": str(result.get("responses"))
        })
    if toolUsed==True:
        body["previous_response_id"] = response.id
        return query_processworkflows(agent_id=agent_id,body=body,conversation_id=conversation_id,logs=logs, metadata=metadata, agent=agent)
    
    # Check output guardrails if enabled (for final response)
    if agent:
        apply_output_guardrails = agent.get("apply_output_guardrails", False)
        if apply_output_guardrails:
            # Extract text from response
            response_text = ""
            for output in response.output:
                # Check if output has content attribute (ResponseFunctionWebSearch doesn't have it)
                if output.type != "function_call" and hasattr(output, 'content') and output.content and len(output.content) > 0:
                    response_text = output.content[0].text
                    break
            
            if response_text:
                guardrails_result = check_output_guardrails(response_text)
                if not guardrails_result["allowed"]:
                    # Replace response content with sanitized message
                    for output in response.output:
                        # Check if output has content attribute (ResponseFunctionWebSearch doesn't have it)
                        if output.type != "function_call" and hasattr(output, 'content') and output.content and len(output.content) > 0:
                            output.content[0].text = guardrails_result["message"]
                            break
    
    return {"response":response, "metadata":metadata}


def openai_query_withworkflows(user_id:str | None, agent_id:str,body:Any,conversation_id:str | None,debug:str | None, useWorkflows=True):
    agent = workflow.workflow_service.agent_get(agent_id)
    if agent == None:
        return {"error":"Agent not found"}
    
    devPrompt = f"The current date is {today}. The current epoch time is {datetime.now(timezone.utc).timestamp()}. When asked to provide random numbers use epoch time as the seed. Always use the simple_math function for any kind of math required, including providing sums or totals from tool results. {agent['description']}"
    conversation = conversation_get(user_id=user_id,conversation_id=conversation_id,include_messages=False)
    if conversation_id is not None and (conversation.get("updated_on") is None or (agent.get("context_update") is not None and conversation["updated_on"] < agent.get("context_update"))):
        body["previous_response_id"] = None
        conversation:dict = conversation_get(user_id=user_id,conversation_id=conversation_id,include_messages=True)
        inputs = [
            {
                "role":"developer",
                "content": devPrompt
            }
        ]
        files = agent_files_get(agent_id=agent_id,contents=True,always_on=True)
        searchable_files = agent_files_get(agent_id=agent_id,searchable=True)
        if files is not None:
            for file in files:
                # Get file content - check contents field, files array, or blob_url (backward compat)
                file_content = file.get("contents")
                
                # If no contents, try to get from files array (new structure)
                if not file_content:
                    files_array = file.get("files")
                    if files_array and isinstance(files_array, list) and len(files_array) > 0:
                        # Use first file in array
                        file_info = files_array[0]
                        if isinstance(file_info, dict) and file_info.get("path"):
                            try:
                                blob_content = download_blob_content(file_info["path"])
                                # Try to decode as text, fallback to binary indicator
                                try:
                                    file_content = blob_content.decode('utf-8')
                                except UnicodeDecodeError:
                                    # For binary files, indicate it's a binary file
                                    file_type = file_info.get('type', 'unknown')
                                    file_content = f"[Binary file: {file_info.get('filename', file.get('name', 'file'))} - {len(blob_content)} bytes. Content type: {file_type}]"
                            except Exception as e:
                                import logging
                                logging.getLogger(__name__).warning(f"Failed to download blob content for file {file.get('id')}: {e}")
                                file_content = f"[File available but content could not be retrieved: {file_info.get('filename', file.get('name', 'file'))}]"
                
                # If still no content, try backward compatibility with blob_url
                if not file_content and file.get("blob_url"):
                    try:
                        blob_content = download_blob_content(file["blob_url"])
                        # Try to decode as text, fallback to base64 or binary indicator
                        try:
                            file_content = blob_content.decode('utf-8')
                        except UnicodeDecodeError:
                            # For binary files, indicate it's a binary file
                            # Try to get type from files array, fallback to unknown
                            file_type = 'unknown'
                            files_array = file.get("files")
                            if files_array and isinstance(files_array, list) and len(files_array) > 0:
                                file_type = files_array[0].get('type', 'unknown')
                            file_content = f"[Binary file: {file.get('name', 'file')} - {len(blob_content)} bytes. Content type: {file_type}]"
                    except Exception as e:
                        import logging
                        logging.getLogger(__name__).warning(f"Failed to download blob content for file {file.get('id')}: {e}")
                        file_content = f"[File available but content could not be retrieved: {file.get('name', 'file')}]"
                
                # If still no content, use a placeholder
                if not file_content:
                    file_content = "[No content available]"
                
                inputs.append({
                    "role":"developer",
                    "content": f"""
Document: {file["name"]}
Description: {file.get("description")}
Contents: {file_content}
 """
                })
        if searchable_files is not None and len(searchable_files)>0:
            searchable_files_prompt = f"""Using the document_query function you can request contents from the following files:"""
            for file in searchable_files:
                searchable_files_prompt += f"""
                ID: {file["id"]}
                Name: {file["name"]}
                Description {file["description"]}

                """
            inputs.append({
                "role":"developer",
                "content":searchable_files_prompt
            })

        if conversation.get("messages") is not None:
            for message in conversation["messages"]:
                message_content = message.get("content", "")
                
                # Check if message has file attachments
                message_files = message.get("files")
                if message_files and isinstance(message_files, list) and len(message_files) > 0:
                    # Process file attachments using helper function
                    file_content_str, _ = process_file_attachments(message_files)
                    if file_content_str:
                        message_content += "\n\nAttached Files:\n" + file_content_str
                
                inputs.append({
                    "role":message["role"],
                    "content":message_content
                })
            body["input"] = inputs + body["input"]  
    elif conversation is not None:
        body["previous_response_id"] = conversation.get("response_id")
    
    # Process files from body["input"] items (for cases where conversation doesn't need refresh or no conversation)
    # This ensures files are processed in all scenarios
    # Store files from last user message for saving to database
    last_user_message_files = None
    
    if body.get("input") and isinstance(body["input"], list):
        for input_item in body["input"]:
            if isinstance(input_item, dict):
                input_content = input_item.get("content", "")
                input_files = input_item.get("files")
                
                # Check if input item has file attachments
                if input_files and isinstance(input_files, list) and len(input_files) > 0:
                    # Process file attachments using helper function
                    file_content_str, _ = process_file_attachments(input_files)
                    if file_content_str:
                        input_item["content"] = input_content + "\n\nAttached Files:\n" + file_content_str
                    
                    # Save files for last user message before removing
                    if input_item.get("role") == "user" and len(body["input"]) > 0 and input_item == body["input"][-1]:
                        last_user_message_files = input_files.copy()
                    
                    # Remove files field to prevent OpenAI API error
                    input_item.pop("files", None)
   
    if conversation_id is not None:
        if body["input"][len(body["input"])-1]["role"]=="user":  
            last_input = body["input"][len(body["input"])-1]
            message = {
                "conversation_id":conversation_id,
                "role":"user",
                "content":last_input.get("content", "")
            }
            # Preserve files in message if they were present
            if last_user_message_files:
                message["files"] = last_user_message_files
            message_add(conversation_id=conversation_id,message=message)
    
    tools = []
    if useWorkflows==True and agent.get("workflows") != None:   
        for workflow_id in agent["workflows"]:
            workflow_entity = workflow.workflow_service.workflow_get(workflow_id)
            if workflow_entity == None:
                break
            nodes = workflow.workflow_service.nodes_parameters_get(workflow_id)
            parameters = {}
            required = ["workflow_id"]
            parameters["workflow_id"] = {
                "type":"string",
                "enum":[workflow_id]
            }
            for node in nodes:
                if node is None or node.get("configuration") is None:
                    continue
                schema = node["configuration"]["Schema"]
                if schema == None or schema == "":
                    parameters[node["label"]] = {
                        "description":node["configuration"]["Description"],
                        "type":"string"
                    }
                else:
                    parameters[node["label"]] = json.loads(schema)
                    parameters[node["label"]]["description"] = node["configuration"]["Description"]
                required.append(node["label"])
            if(debug == None or debug==workflow_id):
                workflow_name_cleaned = re.sub(r'[^\w]', '',workflow_entity["name"])
                tools.append({
                    "description":workflow_entity["description"],
                    "name":workflow_name_cleaned,
                    "type":"function",
                    "parameters":{
                        "additionalProperties":False,
                        "type":"object",
                        "properties":parameters,
                        "required":required
                    }
                })
    for globalFunction in globalFunctions:
        tools.append(globalFunction)
    
    body["tools"] = tools
    logs = []
    
    # Check input guardrails if enabled
    apply_input_guardrails = agent.get("apply_input_guardrails", False)
    if apply_input_guardrails:
        # Extract last user message from input
        user_input_content = ""
        if body.get("input") and isinstance(body["input"], list):
            for input_item in reversed(body["input"]):
                if isinstance(input_item, dict) and input_item.get("role") == "user":
                    user_input_content = input_item.get("content", "")
                    break
        
        if user_input_content:
            guardrails_result = check_input_guardrails(user_input_content)
            if not guardrails_result["allowed"]:
                # Return refusal message instead of proceeding
                return {
                    "responses": [{"content": guardrails_result["message"]}],
                    "response_id": None
                }
    
    response_obj = query_processworkflows(agent_id=agent_id,body=body,conversation_id=conversation_id,debug=debug,logs=logs, agent=agent)
    response = response_obj["response"]
    metadata = response_obj.get("metadata")
    if (debug != None):
        return response
    # Find first output with content attribute (ResponseFunctionWebSearch doesn't have it)
    responseText = ""
    for output in response.output:
        if hasattr(output, 'content') and output.content and len(output.content) > 0:
            responseText = output.content[0].text
            break
    
    # Check output guardrails if enabled (additional check here for final response)
    apply_output_guardrails = agent.get("apply_output_guardrails", False)
    if apply_output_guardrails and responseText:
        guardrails_result = check_output_guardrails(responseText)
        if not guardrails_result["allowed"]:
            # Replace response text with sanitized safe message
            responseText = guardrails_result["message"]
    
    data = is_valid_json_with_key(responseText,"jinja2")
    response_objs = []
    processedText = responseText
    if data is not None:
        template = Template(data["jinja2"])
        processedText = template.render(data=cache.get(data["id"]))
        print(responseText)
    
    # Generate TTS summary for assistant messages
    tts_summary = None
    try:
        tts_summary = generate_tts_summary(processedText, response.id)
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(f"Failed to generate TTS summary: {e}")
    
    message = {
            "response_id" : response.id,
            "conversation_id" : conversation_id,
            "role":"assistant",
            "content":processedText,
            "log_ids": [log["id"] for log in logs]
    }
    
    # Add TTS summary if generated
    if tts_summary:
        message["tts_summary"] = tts_summary
    if conversation_id is not None:
        patch_operations = [{'op':'set','path':f'/response_id','value':response.id}
                            ,{'op':'set','path':f'/updated_on','value':datetime.now(timezone.utc).timestamp()}]
        conversation_container.patch_item(
            item="conversation_" + conversation_id,
            partition_key=conversation_id,
            patch_operations=patch_operations
        )
        
        response_message_obj = message_add(conversation_id=conversation_id,message=message,metadata=metadata)
        response_objs.append(response_message_obj)
    else:
        response_objs.append(
           message
        )
        
    return {"response_id":response.id,"responses":response_objs}

    


def conversation_add(user_id,agent_id,conversation):
    count_query = f"""
    SELECT VALUE COUNT(1)
    FROM c
    WHERE c.type = "conversation" and c.user_id='{user_id}' and c.agent_id='{agent_id}'
    """
    
    items = list(conversation_container.query_items(
    query=count_query,
    enable_cross_partition_query=True  
    ))

    count = cast(int,items[0] if items else 0)

    conversation_id = str(uuid.uuid4())
    conversation["user_id"] = user_id
    conversation["type"] = "conversation"
    conversation["agent_id"] = agent_id
    conversation["id"] = "conversation_" + conversation_id
    conversation["summary"] = f"Conversation {count+1}"
    conversation["conversation_id"]=conversation_id
    conversation["created_at"]=datetime.now(timezone.utc).timestamp()
    conversation_container.upsert_item(
            conversation
        )
    return conversation


def conversations_get(user_id:str,agent_id:str | None = None,conversation_id:str | None = None):
    
    query = f"""
    SELECT * FROM c WHERE c.type='conversation' AND c.user_id = @user_id
    """
    parameters:List[dict[str,object]] = [
        {"name":"@user_id","value":user_id}
    ]
    if conversation_id is not None:
        query += f" AND c.id = 'conversation_{conversation_id}'" 
    if agent_id is not None:
        query += f" AND c.agent_id = '{agent_id}'"
    items = conversation_container.query_items(
    query=query,
    parameters=parameters,
    enable_cross_partition_query=True
)
    serializedItems = []
    for item in items:
        serializedItems.append(item)
    return serializedItems

def message_add(conversation_id, message,metadata=[]):
    message["type"] = "message"
    message["id"] = "message_" + str(uuid.uuid4())
    message["conversation_id"] = conversation_id
    message["created_at"] = datetime.now(timezone.utc).timestamp()
    message["metadata"] = metadata
    # files array is already included in message if provided
    
    # Generate TTS summary if missing for assistant messages
    if message.get("role") == "assistant" and "tts_summary" not in message:
        response_id = message.get("response_id")
        content = message.get("content", "")
        if content:
            try:
                tts_summary = generate_tts_summary(content, response_id)
                if tts_summary:
                    message["tts_summary"] = tts_summary
            except Exception as e:
                import logging
                logging.getLogger(__name__).warning(f"Failed to generate TTS summary in message_add: {e}")
    
    conversation_container.upsert_item(
            message
        )
    return message

def conversation_get(user_id,conversation_id,include_messages=True):
    conversation = conversations_get(user_id=user_id,conversation_id=conversation_id)
    if len(conversation) == 0:
        return None
    conversation = conversation[0]
    if include_messages == True:
        messages = cosmos_getbypartition(conversation_container,conversation_id,"message")
        conversation["messages"] = messages
    return conversation

def message_get_by_id(message_id: str, user_id: str = None):
    """
    Retrieve a message by its ID using cross-partition query.
    Optionally verify the user has access to the conversation.
    """
    try:
        # Query message by ID across all partitions
        query = f"SELECT * FROM c WHERE c.type='message' AND c.id='{message_id}'"
        items = conversation_container.query_items(
            query=query,
            enable_cross_partition_query=True
        )
        
        messages = list(items)
        if len(messages) == 0:
            return None
        
        message = messages[0]
        
        # If user_id is provided, verify access by checking the conversation
        if user_id:
            conversation_id = message.get("conversation_id")
            if conversation_id:
                conversation = conversation_get(user_id=user_id, conversation_id=conversation_id, include_messages=False)
                if conversation is None:
                    return None  # User doesn't have access to this conversation
        
        return message
    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"Error retrieving message {message_id}: {e}")
        return None

def logs_get(conversation_id,message_id):
    message = None
    try:
        message = cosmos_getbyid(container=conversation_container,id=message_id,partition_key=conversation_id)
        if not isinstance(message, CosmosDict):
            return None
    except CosmosResourceNotFoundError:
        return None
    if message.get("log_ids") is None or len(message["log_ids"])==0:
        return None
    
    logs = ', '.join(f'"{x}"' for x in message["log_ids"])
    query = f"""
    SELECT c.id, c.workflow_name,c.workflow_id, c.created_at,
       ARRAY(SELECT o.id, o.node_type, o.node_label, o.event, o.error,o.created_at FROM o IN c.events ) AS events
FROM c where c.type="log" and c.id IN ({logs}) order by c.created_at asc
    """
    items = workflow_container.query_items(
    query=query,
    enable_cross_partition_query=True
    )
    serializedItems = []
    for item in items:
        serializedItems.append(item)
    return serializedItems

def log_event_get(workflow_id,log_id,event_id):
    
    query = f"""
   SELECT 
   c.id,
   event
FROM c
JOIN event IN c.events
WHERE c.type="log" and c.id="{log_id}" and event.id = "{event_id}"
    """
    items = workflow_container.query_items(
    query=query,
    partition_key=workflow_id
    )

    for item in items:
        return item
    return None

def conversation_delete(conversation_id):
    conversation_container.delete_item("conversation_" + conversation_id,conversation_id)

    