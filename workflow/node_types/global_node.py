from workflow.workflow_datatypes import Pin, NodeConfig, FieldType
from workflow.workflow_executor import Node

class global_node:
    default_setup:NodeConfig = {
        "id":"GlobalData",
        "name":"Global Data",
        "description":"Returns Data that is globally available to all workflows",
        "pins":{
            "trigger_pins":[],
            "input_pins":[],
            "output_pins":[{"name":"Chat History"}],
            "next_pins":[]
        },
        "fields":[]
    }
    
    def __init__(self, node:Node):
        self.node = node


    def Run(self,connection,data):
        self.node.TriggerAll()