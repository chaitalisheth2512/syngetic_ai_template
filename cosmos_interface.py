from azure.cosmos import CosmosClient, exceptions
from datetime import date
today = date.today()


import os
import json
import uuid


COSMOS_API_KEY = os.environ.get('CYNTHETIX_COSMOSDB_API_KEY') 
COSMOS_ENDPOINT = os.environ.get('COSMOS_ENDPOINT') 
COSMOS_DATABASE_NAME = os.environ.get('COSMOS_DATABASE_NAME') 

client =  CosmosClient(COSMOS_ENDPOINT,COSMOS_API_KEY or "")
database = client.get_database_client(COSMOS_DATABASE_NAME)
workflow_container = database.get_container_client("Workflow")
agent_container = database.get_container_client("Agent")
conversation_container = database.get_container_client("Conversation")
user_container = database.get_container_client("User")

  
def cosmos_getbypartition(container, partition_key,type):
    query = f"SELECT * FROM c WHERE c.type='{type}'"
    items = container.query_items(
        query=query,
        partition_key=partition_key, 
        enable_cross_partition_query=False  
    )
    serializedItems = []
    for item in items:
        serializedItems.append(item)
    return serializedItems

def cosmos_getbyid(container,id,partition_key):

    try:
        item_response = container.read_item(item=id,partition_key=partition_key)
        return item_response
    except exceptions.CosmosResourceNotFoundError as e:
        return {"error":e}
    
def cosmos_updatefields(container,id,partition_key,value,fields):
    patch_operations = [] 
    for key in value:
        if key not in fields:
            continue
        patch_operations.append({'op':'set','path':'/'+key,'value':value[key]})

    container.patch_item(
        item=id,
        partition_key=partition_key,
        patch_operations=patch_operations
    )