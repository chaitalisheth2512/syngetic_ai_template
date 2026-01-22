from workflow.workflow_datatypes import Pin, NodeConfig, FieldType
from workflow.workflow_executor import Node
import requests
import json

class response_node:
    
    default_setup:NodeConfig = {
        "id":"Response",
        "name":"Response Node",
        "description": "Send a Response",
        "pins": {
            "trigger_pins":[{"name":"Start"}],
            "input_pins":[{"name":"Response"},{"name":"Metadata"},{"name":"Chat History"}],
            "output_pins":[],
            "next_pins":[{"name":"Next"}]
        },
        "fields":[
            #  {
            #     "id":"ResponseFormat",
            #     "label":"Response Format",
            #     "type":FieldType.SINGLE_SELECT,
            #     "width":"100%",
            #     "options":["Text","JSON"]
            # }
        ]
    }

    def __init__(self, node:Node):
        self.node = node
        configuration = node.data.get("configuration")
    #    self.ResponseFormat = "Text"
    #    if configuration is not None and configuration.get("ResponseFormat") is not None:
    #        self.ResponseFormat = configuration.get("ResponseFormat")


    def Run(self,connection,data):
        print(data,"Response node data---------------------")
        if("Response" in data):
            self.node.workflow.responses.append(data["Response"])
            self.node.LogEvent("Workflow Response",data["Response"])
        if("Metadata" in data):
            self.node.workflow.response_metadata.append(data["Metadata"])
            self.node.LogEvent("Workflow Metadata", data["Metadata"])
        # self.node.workflow.responseFormat = self.ResponseFormat
        return self.node.TriggerAll()

    