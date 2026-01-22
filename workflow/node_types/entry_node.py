from workflow.workflow_datatypes import Pin, NodeConfig
from workflow.workflow_executor import Node

class entry_node:
    default_setup:NodeConfig = {
        "id":"Entry",
        "name":"Entry Node",
        "description":"Entry Node",
        "pins":{
            "trigger_pins":[],
            "input_pins":[],
            "output_pins":[],
            "next_pins":[{"name":"Next"}]
        },
        "fields":[]
    }
    
    def __init__(self, node:Node):
        self.node = node


    def Run(self,connection,data):
        return self.node.TriggerAll()