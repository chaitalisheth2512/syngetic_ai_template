from workflow.workflow_datatypes import Pin, NodeConfig, FieldType
from workflow.workflow_executor import Node
import requests
import json
from jinja2 import Template, TemplateSyntaxError


class text_node:
    
    default_setup:NodeConfig = {
        "id":"Text",
        "name":"Text Node",
        "description": "Manage Text",
        "pins": {
            "trigger_pins":[{"name":"Start"}],
            "input_pins":[],
            "output_pins":[{"name":"Text"}],
            "next_pins":[{"name":"Next"}]
        },
        "fields":[
            {
                "id":"Text",
                "label":"Text",
                "type":FieldType.TEXT,
                "width":"100%"
            }
        ]
    }

    def __init__(self, node:Node):
        self.node = node
        configuration = node.data.get("configuration")
        if(configuration != None):
            self.Text = configuration["Text"]
        else:
            self.Text = ""
   
    def Run(self,connection,data):
        text = Template(self.Text)
        self.Text = text.render(**data)
        self.node.SetTargetPinData(source_pin_name="Text",value=self.Text)
        return self.node.TriggerAll()
       

    