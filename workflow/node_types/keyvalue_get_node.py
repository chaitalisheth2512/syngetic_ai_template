from workflow.workflow_datatypes import Pin, NodeConfig, FieldType
from workflow.workflow_executor import Node
import requests
import json
from jinja2 import Template, TemplateSyntaxError
from workflow.workflow_service import agents_keyvalue_get


class keyvalue_get_node:
    
    default_setup:NodeConfig = {
        "id":"KeyValueGet",
        "name":"Key/Value (Get)",
        "description": "Get a value for a given key",
        "pins": {
            "trigger_pins":[{"name":"Start"}],
            "input_pins":[{"name":"Key"}],
            "output_pins":[{"name":"Value"}],
            "next_pins":[{"name":"Next"}]
        },
        "fields":[
            {
                "id":"Key",
                "label":"Key",
                "type":FieldType.SINGLE_LINE,
                "width":"100%"
            }
        ]
    }

    def __init__(self, node:Node):
        self.node = node
        configuration = node.data.get("configuration")
        if(configuration != None):
            self.Key = configuration["Key"]
        else:
            self.Key = ""
   
    def Run(self,connection,data):
        if self.Key == "" and data.get("Key") is not None:
            self.Key = data.get("Key")
        
        if self.Key != "":
            key = Template(self.Key)
            key = key.render(**data)
            value = agents_keyvalue_get(self.node.workflow.agent_id,key)
            self.node.SetTargetPinData("Value",value)

        return self.node.TriggerAll()
       

    