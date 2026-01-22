import workflow.workflow_service
import importlib
import json
from typing import Any, List, cast
import uuid
from datetime import date
from datetime import datetime, timezone

class WorkflowExecutor:
    def __init__(self, workflow_id:str, agent_id:str,globals:dict[str,Any], node_db_entries:List[Any],connections:List[Any],parameters:dict[str,Any],log:Any, debugging:bool=False):
        types = workflow.workflow_service.load_node_info()
        self.log = log
        self.workflow_id = workflow_id
        self.agent_id = agent_id
        self.globals = globals  # Store globals so nodes can access them
        self.connections = connections
        self.nodes : dict[str,Node] = {}
        self.responses = []
        self.response_metadata = []
        self.responseFormat = "Text"
        self.nodes_by_type = {"Entry":[],"Parameter":[],"GlobalData":[],"Trigger":[]}
        self.active_response_id = None
        log_event = {
            "id" : str(uuid.uuid4()),
            "event" : "",
            "node_type": "Chat Parameters",
            "node_label": "",
            "data" : {"parameters":{}},
            "created_at" : datetime.now(timezone.utc).timestamp()
        }
        self.debugging = debugging
        for node in node_db_entries:
            type = next((item for item in types if item["id"] == node.get("nodeType")), {})
            node_obj = Node(self,node,type["module"])
            self.nodes[node["id"]] = node_obj
            node_type = node.get("nodeType")
            if node_type not in self.nodes_by_type:
                self.nodes_by_type[node_type] = []
            self.nodes_by_type[node_type].append(node_obj)
            # If nodeType contains "Trigger", also add it to the "Trigger" list
            if "Trigger" in node_type:
                self.nodes_by_type["Trigger"].append(node_obj)
           
               
        for connection in connections:
            if connection["source_node"] in self.nodes:
                source_node:Node = self.nodes[connection["source_node"]]
                if connection["source_pin"] in source_node.output_connections:
                    source_node.output_connections[connection["source_pin"]].append(connection)
                if connection["source_pin"] in source_node.next_connections:
                    source_node.next_connections[connection["source_pin"]].append(connection)

        for node in self.nodes_by_type["Parameter"]:
            if node.data.get("label") in parameters:
                node.SetTargetPinData("Data",parameters[node.data.get("label")]) 
                log_event["data"]["parameters"][node.data.get("label")] = parameters[node.data.get("label")]  

        for node in self.nodes_by_type["GlobalData"]:
            for globalKey in globals:
                node.SetTargetPinData(globalKey,globals[globalKey])
        
        workflow.workflow_service.workflow_log_event(self.workflow_id,self.log["id"],log_event)                 

    # def Execute(self):
    #     for entry_node in self.nodes_by_type["Entry"]:
    #         entry_node.Run(connection=None)

    # def ExecuteTriggers(self):
    #     """
    #     Execute trigger nodes independently.
    #     This should be called by a scheduler / background runner.
    #     """
    #     for trigger_node in self.nodes_by_type.get("Trigger", []):
    #         try:
    #             print("----------------------------")
    #             trigger_node.Run(connection=None, data={})
    #         except Exception as e:
    #             self.log_error(trigger_node, e)

    # def ExecuteFromState(self, workflow_state):
    #     action_stack: List[Any] = []

    #     if workflow_state is None:
    #         # START ONLY FROM ENTRY NODES
    #         for entry_node in self.nodes_by_type.get("Entry", []):
    #             for source_pin in entry_node.next_connections:
    #                 for action in entry_node.next_connections[source_pin]:
    #                     if action["destination_node"] in self.nodes:
    #                         action_stack.append(action)

    #         # Parameters logic unchanged
    #         for node in self.nodes_by_type.get("Parameter", []):
    #             configuration = node.data.get("configuration")
    #             data = configuration.get("Debug")
    #             if data is not None:
    #                 if configuration.get("Schema"):
    #                     data = json.loads(data)
    #                 node.SetTargetPinData("Data", data)

    #     else:
    #         action_stack = workflow_state["action_stack"]

    #         while action_stack:
    #             for node_id in self.nodes:
    #                 if node_id in workflow_state["nodes"]:
    #                     self.nodes[node_id].input_pins = workflow_state["nodes"][node_id]["input_pins"]

    #             next_action = action_stack.pop(0)
    #             if next_action["destination_node"] in self.nodes:
    #                 next_node = self.nodes[next_action["destination_node"]]
    #                 new_actions = next_node.Run(next_action)
    #                 action_stack.extend(new_actions)
    #                 break

    #     if not action_stack:
    #         return None

    #     return {
    #         "action_stack": action_stack,
    #         "nodes": {
    #             node_id: {"input_pins": node.input_pins}
    #             for node_id, node in self.nodes.items()
    #         },
    #         **({"id": workflow_state["id"]} if workflow_state else {})
    #     }
    
    def Execute(self):
        # Run both Entry and Trigger nodes when starting a workflow so trigger-only
        # workflows (e.g., Gmail trigger as the first node) actually fire.
        # BUT: Skip Webhook nodes - they wait for HTTP requests, not Execute()
        # BUT: Skip ScheduleTrigger nodes - they are handled by scheduler_service
        
        # Execute Entry nodes
        for entry_node in self.nodes_by_type.get("Entry", []):
            entry_node.Run(connection=None)
        
        # Execute Trigger nodes (but NOT Webhook or ScheduleTrigger nodes)
        for trigger_node in self.nodes_by_type.get("Trigger", []):
            node_type = trigger_node.data.get("nodeType")
            # Skip webhook nodes - they only run when HTTP request arrives
            # Skip ScheduleTrigger nodes - they are handled by scheduler_service
            if node_type not in ["Webhook", "ScheduleTrigger"]:
                trigger_node.Run(connection=None)
        
        # Webhook nodes: DO NOT EXECUTE - they wait for HTTP requests
        # Webhook nodes are handled separately via /webhook/{workflow_id}/{node_id}/{hash} endpoint
        # They will be executed when an HTTP request arrives at that endpoint
        webhook_nodes = self.nodes_by_type.get("Webhook", [])
        if webhook_nodes:
            print(f"Skipping {len(webhook_nodes)} webhook node(s) - waiting for HTTP requests")
        
        # ScheduleTrigger nodes: DO NOT EXECUTE - they are handled by scheduler_service
        schedule_trigger_nodes = self.nodes_by_type.get("ScheduleTrigger", [])
        if schedule_trigger_nodes:
            print(f"Skipping {len(schedule_trigger_nodes)} schedule trigger node(s) - handled by scheduler")
    
    def ExecuteTriggers(self):
        """
        Execute trigger nodes independently.
        This should be called by a scheduler / background runner.
        BUT: Skip Webhook nodes - they wait for HTTP requests, not scheduler.
        BUT: Skip ScheduleTrigger nodes - they are handled by scheduler_service.
        """
        # Execute Trigger nodes (but NOT Webhook or ScheduleTrigger nodes)
        for trigger_node in self.nodes_by_type.get("Trigger", []):
            node_type = trigger_node.data.get("nodeType")
            # Skip webhook nodes - they only run when HTTP request arrives
            # Skip ScheduleTrigger nodes - they are handled by scheduler_service
            if node_type in ["Webhook", "ScheduleTrigger"]:
                continue
            try:
                print("----------------------------")
                trigger_node.Run(connection=None, data={})
            except Exception as e:
                print(f"Error executing trigger node {trigger_node.data.get('label')}: {e}")
                import traceback
                traceback.print_exc()
                trigger_node.LogEvent(event="Trigger Execution Error", data={}, error=str(e))
        
        # Webhook nodes: DO NOT EXECUTE - they wait for HTTP requests
        # Webhook nodes are handled separately via /webhook/{workflow_id}/{node_id}/{hash} endpoint
        webhook_nodes = self.nodes_by_type.get("Webhook", [])
        if webhook_nodes:
            print(f"Skipping {len(webhook_nodes)} webhook node(s) - waiting for HTTP requests")
        
        # ScheduleTrigger nodes: DO NOT EXECUTE - they are handled by scheduler_service
        schedule_trigger_nodes = self.nodes_by_type.get("ScheduleTrigger", [])
        if schedule_trigger_nodes:
            print(f"Skipping {len(schedule_trigger_nodes)} schedule trigger node(s) - handled by scheduler")

    def ExecuteFromState(self, workflow_state):
        action_stack: List[Any] = []

        if workflow_state is None:
            # START FROM ENTRY AND TRIGGER NODES
            # Run Entry nodes
            for entry_node in self.nodes_by_type.get("Entry", []):
                # Run the node so it can produce output data
                new_actions = entry_node.Run(connection=None)
                if new_actions:
                    action_stack.extend(new_actions)
            
            # Run Trigger nodes (but NOT Webhook or ScheduleTrigger nodes)
            for trigger_node in self.nodes_by_type.get("Trigger", []):
                node_type = trigger_node.data.get("nodeType")
                # Skip webhook nodes - they only run when HTTP request arrives
                # Skip ScheduleTrigger nodes - they are handled by scheduler_service
                if node_type in ["Webhook", "ScheduleTrigger"]:
                    continue
                # Run the node so it can produce output data (e.g., Gmail trigger fetch)
                new_actions = trigger_node.Run(connection=None)
                if new_actions:
                    action_stack.extend(new_actions)
            
            # Webhook nodes: DO NOT EXECUTE - they wait for HTTP requests
            # Webhook nodes are handled separately via /webhook/{workflow_id}/{node_id}/{hash} endpoint
            # They will be executed when an HTTP request arrives at that endpoint
            webhook_nodes = self.nodes_by_type.get("Webhook", [])
            if webhook_nodes:
                print(f"Skipping {len(webhook_nodes)} webhook node(s) - waiting for HTTP requests")
            
            # ScheduleTrigger nodes: DO NOT EXECUTE - they are handled by scheduler_service
            schedule_trigger_nodes = self.nodes_by_type.get("ScheduleTrigger", [])
            if schedule_trigger_nodes:
                print(f"Skipping {len(schedule_trigger_nodes)} schedule trigger node(s) - handled by scheduler")

            # Parameters logic unchanged
            for node in self.nodes_by_type.get("Parameter", []):
                configuration = node.data.get("configuration")
                data = configuration.get("Debug")
                if data is not None:
                    if configuration.get("Schema"):
                        data = json.loads(data)
                    node.SetTargetPinData("Data", data)

        else:
            action_stack = workflow_state["action_stack"]

            while action_stack:
                for node_id in self.nodes:
                    if node_id in workflow_state["nodes"]:
                        self.nodes[node_id].input_pins = workflow_state["nodes"][node_id]["input_pins"]

                next_action = action_stack.pop(0)
                if next_action["destination_node"] in self.nodes:
                    next_node = self.nodes[next_action["destination_node"]]
                    new_actions = next_node.Run(next_action)
                    action_stack.extend(new_actions)
                    break

        if not action_stack:
            return None

        return {
            "action_stack": action_stack,
            "nodes": {
                node_id: {"input_pins": node.input_pins}
                for node_id, node in self.nodes.items()
            },
            **({"id": workflow_state["id"]} if workflow_state else {})
        }


    # def ExecuteFromState(self, workflow_state):
    #     action_stack:List[Any] = []
    #     if workflow_state == None:
    #         for entry_node in self.nodes_by_type["Entry"]:
    #             for source_pin in entry_node.next_connections:
    #                 for action in entry_node.next_connections[source_pin]:
    #                     if action["destination_node"] in self.nodes:
    #                         action_stack.append(action)
    #         # for entry_node in (
    #         #     self.nodes_by_type.get("Entry", []) +
    #         #     self.nodes_by_type.get("Trigger", [])
    #         # ):
    #         #     for source_pin in entry_node.next_connections:
    #         #         for action in entry_node.next_connections[source_pin]:
    #         #             if action["destination_node"] in self.nodes:
    #         #                 action_stack.append(action)
    #         for node in self.nodes_by_type["Parameter"]:
    #             configuration = node.data.get("configuration")
    #             data = configuration.get("Debug")
    #             if data is not None:
    #                 if configuration.get("Schema") is not None and len(configuration.get("Schema"))>0:
    #                     data = json.loads(data)
    #                 node.SetTargetPinData("Data",data)
    #     else:
    #         action_stack = workflow_state["action_stack"]
    #         while len(action_stack) > 0:
    #             for node_id in self.nodes:
    #                 node = self.nodes[node_id]
    #                 if node_id in workflow_state["nodes"]:
    #                     node.input_pins = workflow_state["nodes"][node_id]["input_pins"]
    #             next_action = action_stack.pop(0)
    #             if next_action["destination_node"] in self.nodes:
    #                 next_node = self.nodes[next_action["destination_node"]]        
    #                 new_actions = next_node.Run(next_action)
    #                 action_stack += new_actions
    #                 break
        
    #     if len(action_stack) == 0:
    #         return None
        
    #     nodes : dict[str,Any] = {}
    #     for node_id in self.nodes:
    #         node = self.nodes[node_id]
    #         nodes[node.data["id"]] = {
    #             "input_pins":node.input_pins
    #         } 
    #     newState =  {
    #         "action_stack":action_stack,
    #         "nodes":nodes
    #     }
    #     if workflow_state != None:
    #         newState["id"] = workflow_state["id"]
    #     return newState

    
class Node:
    def __init__(self,workflow:WorkflowExecutor,data,module:str):
        self.data = data
        self.module = module
        self.workflow = workflow
        self.input_pins = {}
        self.output_connections = {}
        self.next_connections = {}
        import_module = importlib.import_module("workflow.node_types." +module)
        node_class = getattr(import_module,module)
        self.node_class = node_class(self)

        for pin in data["pins"]["input_pins"]:
            self.input_pins[pin["id"]]=None
        for pin in data["pins"]["output_pins"]:
            self.output_connections[pin["id"]]=[]
        for pin in data["pins"]["next_pins"]:
            self.next_connections[pin["id"]]=[]

    def Run(self,connection):
        print("Running: " + self.data["label"])
        data = {}
        configuration = {}
        if self.data.get("configuration") is not None:
            configuration = self.data["configuration"]
        for pin in self.data["pins"]["input_pins"]:
            data[pin["name"]] = self.input_pins[pin["id"]] 
        event = {
            "input_data": data,
            "triggering_connection":connection,
            "configuration":configuration
        }
        self.LogEvent(event="Node Started",data=event)
        try:
            next_actions = self.node_class.Run(connection=connection,data=data)
        except Exception as e:
            self.LogEvent(event="Node Exception",error=json.dumps(e),data={})
            
        return next_actions

    def SetTargetPinData(self,source_pin_name:str,value):
        pin = next((item for item in self.data["pins"]["output_pins"] if item["name"] == source_pin_name), {})
        for pin_key in self.output_connections:
            if pin_key == pin["id"]:
                for connection in self.output_connections[pin_key]:
                    target_node = self.workflow.nodes.get(connection["destination_node"])
                    if target_node != None:
                        target_node.SetInputPinData(input_pin_id=connection["destination_pin"],value=value)
                
    def SetInputPinData(self,input_pin_id,value):
        if(input_pin_id in self.input_pins):
            self.input_pins[input_pin_id] = value
    
    def SetInputPinData_ByName(self,pin_name,value):
        for input_pin in self.data["pins"]["input_pins"]:
            if input_pin["name"]==pin_name:
                self.SetInputPinData(input_pin["id"],value)

    def LogEvent(self,event:str,data:Any,error:str|None=None):
        id = str(uuid.uuid4())
        event_obj = {
            "id":id,
            "created_at": datetime.now(timezone.utc).timestamp(),
            "node_type": self.data["nodeType"],
            "node_label": self.data["label"],
            "event": event,
            "error": error,
            "data": data
        }
        workflow.workflow_service.workflow_log_event(self.workflow.workflow_id,self.workflow.log["id"],event_obj)
        return event_obj
        
    def Trigger(self,pin_names:List[str]=[]):
        next_connections = [] 
        next_pin_ids = []
        for pin in self.data["pins"]["next_pins"]:
            if pin["name"] in pin_names:
                next_pin_ids.append(pin["id"])

        for next_pin_key in self.next_connections: 
            if len(pin_names)==0 or next_pin_key in next_pin_ids:
                connections = self.next_connections[next_pin_key]
                for connection in connections:
                    if connection["destination_node"] in self.workflow.nodes:
                      next_connections.append(connection)

        if(len(next_connections)>0):  
            event = {
                "connections_triggered":next_connections
            }
            self.LogEvent("Triggered Connections",event)

        if (self.workflow.debugging == False):
            for connection in next_connections:
                self.workflow.nodes[connection["destination_node"]].Run(connection=connection)

        return next_connections

    def TriggerAll(self):
        return self.Trigger()
    
    def getPinByName(self,pin_name,collection):
        pins = self.data["pins"][collection]
        for pin in pins:
            if pin["name"]==pin_name:
                return pin
    
    def TriggerSelf(self,next_pin_name,start_pin_name):
        next_pin = self.getPinByName(next_pin_name,"next_pins")
        start_pin = self.getPinByName(start_pin_name,"trigger_pins")
        if next_pin is not None and start_pin is not None:
            connection = {
                "source_node" : self.data["id"],
                "destination_node" : self.data["id"],
                "source_pin" : next_pin["id"],
                "destination_pin" : start_pin["id"]
            }
            if (self.workflow.debugging == False):
                self.workflow.nodes[self.data["id"]].Run(connection=connection)
            self.LogEvent("Triggered Self",{
                "connection":connection
            })
            return [connection]
        if start_pin is None:
            self.LogEvent("Error",data={},error=f"Tried to Trigger Self but start pin:'{start_pin_name}' could not be found.")
        if next_pin is None:
            self.LogEvent("Error",data={},error=f"Tried to Trigger Self but next pin:'{next_pin_name}' could not be found.")
        return []
