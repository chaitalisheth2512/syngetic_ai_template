from workflow.workflow_datatypes import Pin, NodeConfig, FieldType
from workflow.workflow_executor import Node
import requests
import json
from jinja2 import Template, TemplateSyntaxError
from workflow.workflow_service import agents_keyvalue_set


class keyvalue_set_node:
    
    default_setup:NodeConfig = {
        "id":"KeyValueSet",
        "name":"Key/Value (Set)",
        "description": "Set a value for a given key",
        "pins": {
            "trigger_pins":[{"name":"Start"}],
            "input_pins":[{"name":"Key"},{"name":"Value"}],
            "output_pins":[],
            "next_pins":[{"name":"Next"}]
        },
        "fields":[
            {
                "id":"Key",
                "label":"Key",
                "type":FieldType.SINGLE_LINE,
                "width":"100%"
            },
            {
                "id":"Value",
                "label":"Value",
                "type":FieldType.TEXT,
                "width":"100%"
            }
        ]
    }

    def __init__(self, node:Node):
        self.node = node
        configuration = node.data.get("configuration")
        if(configuration != None):
            self.Value = configuration["Value"]
            self.Key = configuration["Key"]
        else:
            self.Value = ""
            self.Key = ""
   
    def Run(self,connection,data):
        if self.Value == "" and data.get("Value") is not None:
            self.Value = data.get("Value")
        if self.Key == "" and data.get("Key") is not None:
            self.Key = data.get("Key")
        
        if self.Key != "" and self.Value != "":
            value = Template(self.Value)
            value = value.render(**data)
            key = Template(self.Key)
            key = key.render(**data)
            agents_keyvalue_set(self.node.workflow.agent_id,key,value)

        return self.node.TriggerAll()
       

    