from workflow.workflow_datatypes import Pin, NodeConfig, FieldType
from workflow.workflow_executor import Node
import requests
import json
from jinja2 import Template, TemplateSyntaxError


class toJson_node:
    
    default_setup:NodeConfig = {
        "id":"ToJson",
        "name":"To JSON",
        "description": "Convert Text to JSON Object",
        "pins": {
            "trigger_pins":[{"name":"Start"}],
            "input_pins":[
                {"name":"Text"}],
            "output_pins":[{"name":"JSON"}],
            "next_pins":[{"name":"Next"}]
        },
        "fields":[
            
        ]
    }

    def __init__(self, node:Node):
        self.node = node
   
    def Run(self,connection,data):
        jsonOutput = {}
        if data.get("Text") is not None:
            try:
                jsonOutput = json.loads(data["Text"])
            except json.JSONDecodeError as e:
                print(f"JSON parsing failed: {e}")
                self.node.LogEvent("JSON Parse Error",data={},error=f"{e}")
        self.node.SetTargetPinData("JSON",jsonOutput)
        return self.node.TriggerAll()
        
        

       

    