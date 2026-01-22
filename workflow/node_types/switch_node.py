from workflow.workflow_datatypes import Pin, NodeConfig, FieldType
from workflow.workflow_executor import Node
import requests
import json
from jinja2 import Template, TemplateSyntaxError


class switch_node:
    
    default_setup:NodeConfig = {
        "id":"Switch",
        "name":"Switch",
        "description": "Switch",
        "pins": {
            "trigger_pins":[{"name":"Start"}],
            "input_pins":[{"name":"Input"}],
            "output_pins":[],
            "next_pins":[{"name":"Default"}]
        },
        "fields":[
            
        ]
    }

    def __init__(self, node:Node):
        self.node = node
   
    def Run(self,connection,data):
        triggered_actions = self.node.Trigger([data["Input"]])
        if len(triggered_actions) > 0:
            return triggered_actions
        return self.node.Trigger(["Default"])
       

    