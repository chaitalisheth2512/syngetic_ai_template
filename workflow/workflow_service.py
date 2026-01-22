import os
import importlib.util
import inspect
from typing import cast, List, Any
from azure.cosmos import CosmosDict
from azure.cosmos.exceptions import CosmosResourceNotFoundError
from cosmos_interface import workflow_container, agent_container, cosmos_getbyid, cosmos_getbypartition, \
    cosmos_updatefields
import uuid
from workflow.workflow_executor import WorkflowExecutor
import json
from datetime import date
from datetime import datetime, timezone


def load_node_info():
    results = []
    base_dir = os.path.dirname(__file__)
    path = os.path.join(base_dir, "node_types")
    for filename in os.listdir(path):
        if filename.endswith('.py') and not filename.startswith('__'):
            filepath = os.path.join(path, filename)
            module_name = filename[:-3]  # strip .py
            class_name = module_name

            # Load the module dynamically
            spec = importlib.util.spec_from_file_location(module_name, filepath)
            assert spec is not None
            module = importlib.util.module_from_spec(spec)
            assert module is not None
            assert spec.loader is not None
            spec.loader.exec_module(module)

            # Get the class by name
            cls = getattr(module, class_name, None)
            if inspect.isclass(cls):
                # Get class attributes (excluding methods and built-ins)
                attributes = {
                    name: value
                    for name, value in vars(cls).items()
                    if not name.startswith('__') and not inspect.isroutine(value)
                }
                attributes["default_setup"]["module"] = module_name
                results.append(attributes["default_setup"])

    return results


def node_add_bytype(workflow_id: str, type: str):
    nodes = load_node_info()
    nodeType = next((n for n in nodes if n["id"] == type), None)
    if nodeType != None:
        pinTypes = ["trigger_pins", "input_pins", "next_pins", "output_pins"]
        for pinType in pinTypes:
            for pin in nodeType["pins"][pinType]:
                pin["id"] = str(uuid.uuid4())

    if nodeType != None:
        newNode = {
            "id": "node_" + str(uuid.uuid4()),
            "type": "node",
            "workflow_id": workflow_id,
            "label": nodeType["name"],
            "pins": nodeType["pins"],
            "nodeType": type,
            "nodeData": {
                "x": 10,
                "y": 10
            }
        }
        workflow_container.upsert_item(
            newNode
        )
        return newNode
    else:
        assert "Node type does not exist"


def node_add(workflow_id: str, node):
    node["type"] = "node"
    node["id"] = "node_" + str(uuid.uuid4())
    node["workflow_id"] = workflow_id
    workflow_container.upsert_item(
        node
    )
    return node


def node_update(workflow_id, workflow_node):
    workflow_node_id = workflow_node["id"]
    nodeData = workflow_node["nodeData"]
    patch_operations = []
    if "configuration" in workflow_node:
        patch_operations.append({'op': 'set', 'path': '/configuration', 'value': workflow_node["configuration"]})
    if "label" in workflow_node:
        patch_operations.append({'op': 'set', 'path': '/label', 'value': workflow_node["label"]})
    if "nodeData" in workflow_node:
        patch_operations.append({'op': 'set', 'path': '/nodeData', 'value': nodeData})

    workflow_container.patch_item(
        item=workflow_node_id,
        partition_key=workflow_id,
        patch_operations=patch_operations
    )


def connections_get(workflow_id: str):
    connections = cosmos_getbypartition(workflow_container, workflow_id, "connection")
    return connections


def connection_create(workflow_id, connection):
    item = {
        "id": "connection_" + str(uuid.uuid4()),
        "type": "connection",
        "workflow_id": workflow_id,
        "source_pin": connection["source_pin"],
        "source_node": connection["source_node"],
        "destination_node": connection["destination_node"],
        "destination_pin": connection["destination_pin"]
    }
    workflow_container.upsert_item(item)
    return item


def connection_delete_deprecated(workflow_id, source_pin, destination_pin):
    query = f"SELECT * FROM c WHERE c.type='connection' AND c.source_pin=@source_pin AND c.destination_pin=@destination_pin"
    parameters: List[dict[str, object]] = [
        {"name": "@source_pin", "value": source_pin},
        {"name": "@destination_pin", "value": destination_pin}
    ]
    items = workflow_container.query_items(
        query=query,
        parameters=parameters,
        partition_key=workflow_id,
        enable_cross_partition_query=False
    )
    for connection in items:
        workflow_container.delete_item(item=connection['id'], partition_key=workflow_id)


def connection_delete(workflow_id, connection_id):
    connection = cosmos_getbyid(container=workflow_container, id=connection_id, partition_key=workflow_id)

    query = f"SELECT * FROM c WHERE c.type='connection' AND c.source_pin=@source_pin AND c.destination_pin=@destination_pin and c.source_node=@source_node and c.destination_node=@destination_node"
    parameters: List[dict[str, object]] = [
        {"name": "@source_pin", "value": connection["source_pin"]},
        {"name": "@destination_pin", "value": connection["destination_pin"]},
        {"name": "@source_node", "value": connection["source_node"]},
        {"name": "@destination_node", "value": connection["destination_node"]}
    ]
    items = workflow_container.query_items(
        query=query,
        parameters=parameters,
        partition_key=workflow_id,
        enable_cross_partition_query=False
    )
    for connection_obj in items:
        workflow_container.delete_item(item=connection_obj['id'], partition_key=workflow_id)


def nodes_copy(copy_body):
    ids = [f"'{node['node_id']}'" for node in copy_body["nodes"]]
    query = f"""
        SELECT * FROM c WHERE c.type='node' AND c.id IN ({', '.join(ids)})
    """
    nodes = workflow_container.query_items(
        partition_key=copy_body["source_workflow_id"],
        query=query)
    node_map = {}
    serialized_nodes = []
    for node in nodes:
        node_map[node["id"]] = node
        node["workflow_id"] = copy_body["destination_workflow_id"]
        node["id"] = "node_" + str(uuid.uuid4())
        for k in list(node.keys()):
            if k.startswith("_"):
                del node[k]

    for node in copy_body["nodes"]:
        node_obj = node_map[node["node_id"]]
        if "location" in node:
            if "nodeData" not in node_obj:
                node_obj["nodeData"] = {}
            node_obj["nodeData"]["x"] = node["location"]["x"]
            node_obj["nodeData"]["y"] = node["location"]["y"]
        workflow_container.upsert_item(node_obj)
        serialized_nodes.append(node_obj)
        if "keep_connections" in copy_body and copy_body["keep_connections"] == True:
            query = f"SELECT * FROM c WHERE c.type='connection' AND (c.source_node='{node["node_id"]}' or c.destination_node='{node["node_id"]}')"
            connections = workflow_container.query_items(
                query=query,
                partition_key=copy_body["source_workflow_id"],
                enable_cross_partition_query=False
            )
            for connection in connections:
                if connection["source_node"] in node_map and connection["destination_node"] in node_map:
                    connection["id"] = "connection_" + str(uuid.uuid4())
                    connection["workflow_id"] = copy_body["destination_workflow_id"]
                    connection["source_node"] = node_map[connection["source_node"]]["id"]
                    connection["destination_node"] = node_map[connection["destination_node"]]["id"]
                    for k in list(connection.keys()):
                        if k.startswith("_"):
                            del connection[k]
                    workflow_container.upsert_item(connection)

    if copy_body["type"] == "cut":
        for node in copy_body["nodes"]:
            workflow_container.delete_item(item=node["node_id"], partition_key=copy_body["source_workflow_id"])

    return serialized_nodes


def nodes_get(workflow_id: str):
    nodes = cosmos_getbypartition(workflow_container, workflow_id, "node")
    return nodes


def node_delete(workflow_id: str, node_id: str):
    query = f"SELECT * FROM c WHERE c.type='connection' AND (c.source_node='{node_id}' or c.destination_node='{node_id}')"
    items = workflow_container.query_items(
        query=query,
        partition_key=workflow_id,
        enable_cross_partition_query=False
    )
    for item in items:
        workflow_container.delete_item(item=item["id"], partition_key=workflow_id)
    workflow_container.delete_item(item=node_id, partition_key=workflow_id)


def node_get(workflow_id: str, node_id: str):
    try:
        node = cosmos_getbyid(workflow_container, node_id, workflow_id)
        if isinstance(node, CosmosDict):
            return node
    except CosmosResourceNotFoundError:
        return None
    return None


def nodes_parameters_get(workflow_id: str):
    query = f"SELECT * FROM c WHERE c.type='node' AND c.nodeType='Parameter'"
    items = workflow_container.query_items(
        query=query,
        partition_key=workflow_id,
        enable_cross_partition_query=False
    )
    serializedItems = []
    for item in items:
        serializedItems.append(item)
    return serializedItems


# def workflow_execute(agent_id: str, workflow_id: str, globals: dict[str, Any], parameters: dict[str, Any], log: Any):
#     nodes = nodes_get(workflow_id)
#     connections = connections_get(workflow_id)
#     # print(nodes,"nodes---------------")
#     # print(connections,"connections---------------")
#     workflow_execution = WorkflowExecutor(agent_id=agent_id, globals=globals, workflow_id=workflow_id,
#                                         node_db_entries=nodes, connections=connections, parameters=parameters,
#                                         log=log)
#     print(workflow_execution,"workflow_execution---------------")
#     workflow_execution.Execute()
#     print(workflow_execution.responses,"workflow_execution.responses---------------")
#     print(workflow_execution.response_metadata,"workflow_execution.response_metadata---------------")
#     return {"responses": workflow_execution.responses, "metadata": workflow_execution.response_metadata}

def workflow_execute(agent_id: str, workflow_id: str, globals: dict[str, Any], parameters: dict[str, Any], log: Any):
    print(parameters,"workflow_execute parameters---------------")
    print(globals,"workflow_execute globals---------------")
    # Validate that the workflow exists
    try:
        workflow = workflow_get(workflow_id)
        if workflow is None:
            raise Exception(f"Workflow '{workflow_id}' not found. Please verify the workflow ID is correct and that it exists in the database.")
    except CosmosResourceNotFoundError as e:
        raise Exception(f"Workflow '{workflow_id}' not found in database. The workflow may have been deleted or the ID is incorrect.")
    except Exception as e:
        raise Exception(f"Error validating workflow '{workflow_id}': {str(e)}")
    
    # Get nodes and connections for the workflow
    try:
        nodes = nodes_get(workflow_id)
        connections = connections_get(workflow_id)
    except CosmosResourceNotFoundError as e:
        raise Exception(f"Error accessing workflow data: Workflow '{workflow_id}' or its components (nodes/connections) not found in database.")
    except Exception as e:
        raise Exception(f"Error retrieving workflow data for '{workflow_id}': {str(e)}")

    # Execute the workflow
    try:
        workflow_execution = WorkflowExecutor(agent_id=agent_id, globals=globals, workflow_id=workflow_id,
                                            node_db_entries=nodes, connections=connections, parameters=parameters,
                                            log=log, debugging=False)
        workflow_execution.Execute()
        return {"responses": workflow_execution.responses, "metadata": workflow_execution.response_metadata}
    except CosmosResourceNotFoundError as e:
        raise Exception(f"Error during workflow execution: A required resource was not found in the database. This may occur if the workflow or its components were deleted during execution. Workflow ID: '{workflow_id}'")
    except Exception as e:
        raise Exception(f"Error executing workflow '{workflow_id}': {str(e)}")



def workflow_debug(agent_id: str, workflow_id: str, globals: dict[str, Any], parameters: dict[str, Any],
                   state_id: str | None):
    try:
        print(parameters,"parameters---------------")
        print(globals,"globals---------------")
        state = None
        if state_id != None:
            state = state_get(workflow_id=workflow_id, state_id=state_id)
        else:
            state_id = f"state_{str(uuid.uuid4())}"

        nodes = nodes_get(workflow_id)
        connections = connections_get(workflow_id)
        log = workflow_log_create(log_id=state_id, agent_id=agent_id, workflow_id=workflow_id, conversation_id=None)
        workflow_execution = WorkflowExecutor(agent_id=agent_id, globals=globals, workflow_id=workflow_id,
                                            node_db_entries=nodes, connections=connections, parameters=parameters,
                                            debugging=True, log=log)

        # print(workflow_execution,"workflow_execution---------------")
        workflow_state = workflow_execution.ExecuteFromState(state)
        # print(workflow_state,"workflow_state---------------")
        if workflow_state != None and "id" not in workflow_state:
            workflow_state["id"] = state_id
        state_update(workflow_id=workflow_id, state=workflow_state)
        return workflow_state
    except Exception as e:
        print(e,"workflow_debug-------------------")


def workflow_get(workflow_id: str):
    workflow = cosmos_getbypartition(workflow_container, workflow_id, "workflow")
    if len(workflow) > 0:
        return workflow[0]
    return None


def workflow_delete(workflow_id: str):
    """
    Delete a workflow and all its associated data (nodes, connections, notes, logs, states).
    Also deletes all workflow AI chat conversations and messages.
    """
    # Delete all nodes (this will also delete connections)
    nodes = nodes_get(workflow_id)
    for node in nodes:
        node_delete(workflow_id, node.get("id"))
    
    # Delete all connections (in case any remain)
    connections = connections_get(workflow_id)
    for connection in connections:
        connection_id = connection.get("id")
        if connection_id:
            try:
                connection_delete(workflow_id, connection_id)
            except Exception:
                pass  # Ignore if already deleted
    
    # Delete all notes
    notes = notes_get(workflow_id)
    for note in notes:
        note_id = note.get("id")
        if note_id:
            try:
                note_delete(workflow_id, note_id)
            except Exception:
                pass
    
    # Delete workflow AI chat conversations and messages
    try:
        from services.workflow_ai_chat_service import workflow_conversations_delete_all
        deleted_conversations = workflow_conversations_delete_all(workflow_id)
        print(f"Deleted {deleted_conversations} workflow conversations for workflow {workflow_id}")
    except Exception as e:
        print(f"Error deleting workflow conversations: {e}")
    
    # Delete workflow logs and states
    try:
        # Delete logs
        logs_query = f"SELECT * FROM c WHERE c.type='log' AND c.workflow_id='{workflow_id}'"
        logs = workflow_container.query_items(
            query=logs_query,
            partition_key=workflow_id,
            enable_cross_partition_query=False
        )
        for log in logs:
            try:
                workflow_container.delete_item(item=log.get("id"), partition_key=workflow_id)
            except Exception:
                pass
        
        # Delete states
        states_query = f"SELECT * FROM c WHERE c.type='state' AND c.workflow_id='{workflow_id}'"
        states = workflow_container.query_items(
            query=states_query,
            partition_key=workflow_id,
            enable_cross_partition_query=False
        )
        for state in states:
            try:
                workflow_container.delete_item(item=state.get("id"), partition_key=workflow_id)
            except Exception:
                pass
    except Exception as e:
        print(f"Error deleting workflow logs/states: {e}")
    
    # Finally, delete the workflow itself
    try:
        workflow_item_id = f"workflow_{workflow_id}"
        workflow_container.delete_item(item=workflow_item_id, partition_key=workflow_id)
    except CosmosResourceNotFoundError:
        pass  # Already deleted
    except Exception as e:
        print(f"Error deleting workflow: {e}")
        raise


def workflows_get(agent_id: str):
    agent = agent_get(agent_id)
    if agent == None:
        return None
    if agent.get("workflows") == None or len(agent["workflows"]) == 0:
        return []
    query = f"""
    SELECT * FROM c WHERE c.type='workflow' AND c.workflow_id IN ({', '.join(json.dumps(workflow_id) for workflow_id in agent["workflows"])})
    """
    items = workflow_container.query_items(
        query=query,
        enable_cross_partition_query=True
    )
    serializedItems = []
    for item in items:
        serializedItems.append(item)
    return serializedItems


def state_update(workflow_id, state):
    state["workflow_id"] = workflow_id
    state["type"] = "state"
    workflow_container.upsert_item(state)
    return state


def state_get(workflow_id, state_id):
    try:
        state = cosmos_getbyid(workflow_container, state_id, workflow_id)
        if isinstance(state, CosmosDict):
            return state
    except CosmosResourceNotFoundError:
        return None
    return None


def workflow_add(workflow):
    workflow_id = str(uuid.uuid4())
    workflowObj = {
        "name": workflow["name"],
        "type": "workflow",
        "id": "workflow_" + workflow_id,
        "workflow_id": workflow_id,
        "description": workflow["description"]
    }

    workflow_container.upsert_item(
        workflowObj
    )
    return workflowObj


def workflow_update(workflow_id, workflow):
    patch_operations = []
    if "name" in workflow:
        patch_operations.append({'op': 'set', 'path': '/name', 'value': workflow["name"]})
    if "description" in workflow:
        patch_operations.append({'op': 'set', 'path': '/description', 'value': workflow["description"]})

    workflow_container.patch_item(
        item="workflow_" + workflow_id,
        partition_key=workflow_id,
        patch_operations=patch_operations
    )


def pins_add(pin_collection: str, workflow_id: str, node_id: str, pin: Any):
    node = node_get(workflow_id, node_id)
    if node == None:
        return

    newPin = {
        "id": str(uuid.uuid4()),
        "name": pin["name"],
        "editable": True
    }
    patch_operation = {'op': 'add', 'path': f'/pins/{pin_collection}/-', 'value': newPin}

    workflow_container.patch_item(
        item=node_id,
        partition_key=workflow_id,
        patch_operations=[patch_operation]
    )
    return newPin


def pins_update(pin_collection: str, workflow_id: str, node_id: str, pin: Any):
    node = node_get(workflow_id, node_id)
    if node == None:
        return

    updatedPin = {
        "id": pin["id"],
        "name": pin["name"],
        "editable": pin["editable"]
    }
    pins = node["pins"][pin_collection]
    pin_index = next((i for i, item in enumerate(pins) if item["id"] == pin["id"]), -1)
    if pin_index == -1:
        return

    pins[pin_index] = updatedPin
    patch_operation = {'op': 'set', 'path': f'/pins/{pin_collection}', 'value': pins}

    workflow_container.patch_item(
        item=node_id,
        partition_key=workflow_id,
        patch_operations=[patch_operation]
    )


def pins_remove(pin_collection: str, workflow_id: str, node_id: str, pin_id: str):
    node = node_get(workflow_id, node_id)
    if node == None:
        return

    pins = [item for item in node["pins"][pin_collection] if item["id"] != pin_id]

    patch_operation = {'op': 'set', 'path': f'/pins/{pin_collection}', 'value': pins}

    workflow_container.patch_item(
        item=node_id,
        partition_key=workflow_id,
        patch_operations=[patch_operation]
    )

    query = f"SELECT * FROM c WHERE c.type='connection' AND ((c.source_node='{node_id}' and c.source_pin='{pin_id}') or (c.destination_node='{node_id}' and c.destination_pin='{pin_id}'))"
    items = workflow_container.query_items(
        query=query,
        partition_key=workflow_id,
        enable_cross_partition_query=False
    )
    for item in items:
        workflow_container.delete_item(item=item["id"], partition_key=workflow_id)


def agent_get(agent_id: str) -> CosmosDict | None:
    try:
        agent = cosmos_getbyid(agent_container, "agent_" + agent_id, agent_id)
        if isinstance(agent, CosmosDict):
            return agent
    except CosmosResourceNotFoundError:
        return None
    return None


def agents_get():
    query = f"""
        SELECT * FROM c WHERE c.type='agent'
        """
    items = agent_container.query_items(
        query=query,
        enable_cross_partition_query=True
    )
    serializedItems = []
    for item in items:
        serializedItems.append(item)
    return serializedItems


def agents_keyvalue_set(agent_id, key, value):
    body = {
        "id": "keyvalue_" + key,
        "type": "keyvalue",
        "agent_id": agent_id,
        "value": value
    }
    agent_container.upsert_item(body)


def agents_keyvalue_get(agent_id, key):
    try:
        value = cosmos_getbyid(agent_container, "keyvalue_" + key, agent_id)
        if isinstance(value, CosmosDict):
            return value["value"]
    except CosmosResourceNotFoundError:
        return None
    return None


def agent_workflows_add(agent_id: str, workflow_id: str):
    agent = agent_get(agent_id)
    if agent == None:
        return

    if agent.get("workflows") is None:
        patch_operation = {'op': 'set', 'path': '/workflows', 'value': [workflow_id]}
    else:
        if workflow_id in agent["workflows"]:
            return
        patch_operation = {'op': 'add', 'path': '/workflows/-', 'value': workflow_id}

    agent_container.patch_item(
        item="agent_" + agent_id,
        partition_key=agent_id,
        patch_operations=[patch_operation]
    )


def agent_add(agent):
    agent_id = str(uuid.uuid4())
    agentObj = {
        "name": agent["name"],
        "type": "agent",
        "id": "agent_" + agent_id,
        "creator_id": agent.get("creator_id"),
        "agent_id": agent_id,
        "description": agent["description"],
        "apply_input_guardrails": agent.get("apply_input_guardrails", False),
        "apply_output_guardrails": agent.get("apply_output_guardrails", False)
    }

    agent_container.upsert_item(
        agentObj
    )
    return agentObj


def agent_update(agent_id, agent):
    patch_operations = []
    if "name" in agent:
        patch_operations.append({'op': 'set', 'path': '/name', 'value': agent["name"]})
    if "description" in agent:
        patch_operations.append({'op': 'set', 'path': '/description', 'value': agent["description"]})
    if "apply_input_guardrails" in agent:
        patch_operations.append({'op': 'set', 'path': '/apply_input_guardrails', 'value': agent["apply_input_guardrails"]})
    if "apply_output_guardrails" in agent:
        patch_operations.append({'op': 'set', 'path': '/apply_output_guardrails', 'value': agent["apply_output_guardrails"]})

    agent_container.patch_item(
        item="agent_" + agent_id,
        partition_key=agent_id,
        patch_operations=patch_operations
    )
    agent_refresh_context(agent_id=agent_id)


def agent_delete(agent_id):
    agent_container.delete_item("agent_" + agent_id, agent_id)


def agent_workflows_remove(agent_id: str, workflow_ids: List[str]):
    agent = agent_get(agent_id)
    if agent == None:
        return

    workflows = [item for item in agent["workflows"] if item not in workflow_ids]

    patch_operation = {'op': 'set', 'path': '/workflows', 'value': workflows}

    agent_container.patch_item(
        item="agent_" + agent_id,
        partition_key=agent_id,
        patch_operations=[patch_operation]
    )


def agent_refresh_context(agent_id):
    cosmos_updatefields(container=agent_container, partition_key=agent_id, id="agent_" + agent_id,
                        value={"context_update": datetime.now(timezone.utc).timestamp()}, fields=["context_update"])


def workflow_log_create(agent_id: str, workflow_id: str, conversation_id: str | None, log_id: str | None = None):
    workflow = workflow_get(workflow_id=workflow_id)
    if workflow is None:
        return

    id = log_id
    if log_id is None:
        id = "log_" + str(uuid.uuid4())

    workflow_log = {
        "id": id,
        "agent_id": agent_id,
        "workflow_id": workflow_id,
        "workflow_name": workflow.get("name"),
        "conversation_id": conversation_id,
        "type": "log",
        "events": [],
        "created_at": datetime.now(timezone.utc).timestamp()
    }
    workflow_container.upsert_item(workflow_log)
    return workflow_log


def workflow_log_event(workflow_id: str, log_id: str, event: Any):
    event["created_at"] = datetime.now(timezone.utc).timestamp()
    patch_operation = {'op': 'add', 'path': f'/events/-', 'value': event}
    workflow_container.patch_item(
        item=log_id,
        partition_key=workflow_id,
        patch_operations=[patch_operation]
    )


def workflow_export(workflow_id: str):
    workflow = workflow_get(workflow_id=workflow_id)
    nodes = nodes_get(workflow_id=workflow_id)
    connections = connections_get(workflow_id=workflow_id)
    if workflow is None:
        return

    for key in list(workflow.keys()):
        if key.startswith("_"):
            workflow.pop(key)
    workflow.pop("type", None)
    workflow.pop("id", None)
    workflow.pop("workflow_id", None)

    connection_dict = {}

    for connection in connections:
        if connection["source_node"] not in connection_dict:
            connection_dict[connection["source_node"]] = {}
        node_dict = connection_dict[connection["source_node"]]
        if connection["source_pin"] not in node_dict:
            node_dict[connection["source_pin"]] = []
        node_dict[connection["source_pin"]].append({
            "destination_node": connection["destination_node"],
            "destination_pin": connection["destination_pin"]
        })

    for node in nodes:
        for key in list(node.keys()):
            if key.startswith("_"):
                node.pop(key)
        node.pop("workflow_id", None)
        node.pop("type", None)

        for pin_collection in ["output_pins", "next_pins"]:
            for pin in node["pins"][pin_collection]:
                pin["connections"] = []
                if node["id"] in connection_dict and pin["id"] in connection_dict[node["id"]]:
                    pin["connections"] = connection_dict[node["id"]][pin["id"]]

    workflow["nodes"] = nodes
    return workflow


def workflow_import(workflow):
    workflow["workflow_id"] = str(uuid.uuid4())
    workflow["id"] = "workflow_" + workflow["workflow_id"]
    workflow["type"] = "workflow"
    nodes = workflow.pop("nodes")
    for key in list(workflow.keys()):
        if key.startswith("_"):
            workflow.pop(key)

    connections = []
    for node in nodes:
        node["workflow_id"] = workflow["workflow_id"]
        node["type"] = "node"
        for pin_collection in ["output_pins", "next_pins"]:
            for pin in node["pins"][pin_collection]:
                if "connections" in pin:
                    for connection in pin["connections"]:
                        connection = {
                            "id": "connection_" + str(uuid.uuid4()),
                            "workflow_id": workflow["workflow_id"],
                            "type": "connection",
                            "source_node": node["id"],
                            "source_pin": pin["id"],
                            "destination_node": connection["destination_node"],
                            "destination_pin": connection["destination_pin"]
                        }
                        connections.append(connection)
                    pin.pop("connections")
    workflow_container.upsert_item(workflow)
    for node in nodes:
        workflow_container.upsert_item(node)
    for connection in connections:
        workflow_container.upsert_item(connection)

    return workflow["workflow_id"]


def note_add(workflow_id: str):
    try:
        newNotes = {
            "id": "note_" + str(uuid.uuid4()),
            "type": "note",
            "workflow_id": workflow_id,
            "title": "I'm a note",
            "content": "Double click to edit me.",
            "data": {
                "bgcolor": "#B3EFBD",
                "color": "#162230",
                "height": "200px",
                "width": "200px",
                "position": {
                    "x": 10,
                    "y": 10
                }
            }
        }

        workflow_container.upsert_item(newNotes)

        return newNotes

    except Exception as e:
        return str(e)


def note_update(workflow_id, workflow_note):
    try:
        workflow_note_id = workflow_note["id"]
        patch_operations = []

        if "title" in workflow_note:
            patch_operations.append({
                "op": "set",
                "path": "/title",
                "value": workflow_note["title"]
            })

        if "content" in workflow_note:
            patch_operations.append({
                "op": "set",
                "path": "/content",
                "value": workflow_note["content"]
            })

        if "data" in workflow_note:
            for key, value in workflow_note["data"].items():
                patch_operations.append({
                    "op": "set",
                    "path": f"/data/{key}",
                    "value": value
                })

        if not patch_operations:
            return {"status": "no_changes"}

        workflow_container.patch_item(
            item=workflow_note_id,
            partition_key=workflow_id,
            patch_operations=patch_operations
        )

        return patch_operations

    except Exception as e:
        return str(e)


def notes_get(workflow_id: str):
    nodes = cosmos_getbypartition(workflow_container, workflow_id, "note")
    return nodes


def note_delete(workflow_id: str, note_id: str):
    try:
        workflow_container.delete_item(
            item=note_id,
            partition_key=workflow_id
        )
        return note_id

    except Exception as e:
        return str(e)


def note_get(workflow_id: str, note_id: str):
    try:
        note = cosmos_getbyid(
            workflow_container,
            note_id,
            workflow_id
        )

        if isinstance(note, CosmosDict) and note.get("type") == "note":
            return note

    except CosmosResourceNotFoundError:
        return None

    return None



import threading


# -------------------------------
# SYNC Agent Delegation
# -------------------------------
def agent_delegate(from_agent, to_agent, input_payload, trace_id):
    # Lazy import to avoid circular dependency
    from services.chat_service import openai_query_withworkflows
    
    body = {
        "input": [
            {
                "role": "user",
                "content": input_payload or "give me output of existing workflow."
                # "content": "give me output of existing workflow."
            }
        ]
    }

    response = openai_query_withworkflows(
        user_id=None,
        agent_id=to_agent,
        body=body,
        conversation_id=None,
        debug=None,
        useWorkflows=True
    )

    return {
        "response": response.get("responses"),
        "metadata": {
            "from_agent": from_agent,
            "to_agent": to_agent,
            "trace_id": trace_id,
            "mode": "sync"
        }
    }


# -------------------------------
# ASYNC Agent Delegation
# -------------------------------
def agent_delegate_async(from_agent, to_agent, input_payload, trace_id):
    def run():
        agent_delegate(
            from_agent=from_agent,
            to_agent=to_agent,
            input_payload=input_payload,
            trace_id=trace_id
        )

    threading.Thread(target=run, daemon=True).start()


def workflow_execute_async(agent_id, workflow_id, parameters, globals, log):
    import threading

    def run():
        workflow_execute(
            agent_id=agent_id,
            workflow_id=workflow_id,
            parameters=parameters,
            globals=globals,
            log=log
        )

    threading.Thread(target=run, daemon=True).start()
 