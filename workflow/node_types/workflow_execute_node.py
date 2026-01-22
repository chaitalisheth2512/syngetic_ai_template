from workflow.workflow_datatypes import Pin, NodeConfig, FieldType
from workflow.workflow_executor import Node
import requests
import json
from jinja2 import Template, TemplateSyntaxError
import workflow.workflow_service


class workflow_execute_node:
    
    default_setup:NodeConfig = {
        "id":"WorkflowExecute",
        "name":"Execute Workflow",
        "description": "Execute another workflow on the current agent",
        "pins": {
            "trigger_pins":[{"name":"Start"}],
            "input_pins":[],
            "output_pins":[{"name":"Responses"},{"name":"Metadata"}],
            "next_pins":[{"name":"Next"}]
        },
        "fields":[
            {
                "id":"workflow_id",
                "label":"Workflow ID",
                "type":FieldType.SINGLE_LINE,
                "width":"100%"
            }
        ]
    }

    def __init__(self, node:Node):
        self.node = node
        configuration = node.data.get("configuration")
        if(configuration != None):
            self.workflow_id = configuration["workflow_id"]
        else:
            self.workflow_id = None
   
    def Run(self,connection,data):
        if self.workflow_id != None:
            print(self.workflow_id,"self.workflow_id-------------------")
            workflow_result = workflow.workflow_service.workflow_execute(agent_id=self.node.workflow.agent_id,workflow_id=self.workflow_id,globals=self.node.workflow.globals,log=self.node.workflow.log, parameters=data)
            self.node.SetTargetPinData(source_pin_name="Responses",value=workflow_result["responses"])
            self.node.SetTargetPinData(source_pin_name="Metadata",value=workflow_result["metadata"])
        return self.node.TriggerAll()
       

    