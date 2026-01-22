from workflow.workflow_datatypes import Pin, NodeConfig, FieldType
from workflow.workflow_executor import Node

class parameter_node:
    default_setup:NodeConfig = {
        "id":"Parameter",
        "name":"Parameter Node",
        "description":"Parameter Node. Can be a primitive, or an object if provided a schema.",
        "pins":{
            "trigger_pins":[],
            "input_pins":[],
            "output_pins":[{"name":"Data"}],
            "next_pins":[]
        },
        "fields":[
                    {
                "id":"Schema",
                "label":"Schema",
                "type":FieldType.TEXT,
                "width":"100%"
            },
              {
                "id":"Description",
                "label":"Description",
                "type":FieldType.TEXT,
                "width":"100%"
            },
            {
                "id":"Debug",
                "label":"Debug",
                "type":FieldType.TEXT,
                "width":"100%"
            }
            
        ]
    }
    
    def __init__(self, node:Node):
        self.node = node


    def Run(self,connection,data):
        self.node.TriggerAll()