from workflow.workflow_datatypes import Pin, NodeConfig, FieldType
from workflow.workflow_executor import Node
import requests
import json
from jinja2 import Template, TemplateSyntaxError


class iterator_node:
    
    default_setup:NodeConfig = {
        "id":"Iterator",
        "name":"Iterator",
        "description": "Iterator",
        "pins": {
            "trigger_pins":[{"name":"Iterate"}],
            "input_pins":[
                {"name":"Array"},
                {"name":"Index"}],
            "output_pins":[{"name":"Index"},
                           {"name":"Value"}],
            "next_pins":[{"name":"Next"},
                          {"name":"Finished"}]
        },
        "fields":[
            
        ]
    }

    def __init__(self, node:Node):
        self.node = node
   
    def Run(self,connection,data):
        index = 0
        if data.get("Index") != None and isinstance(data.get("Index"), (int, float)):
            index = data.get("Index")
        array = data.get("Array")
        if array is not None and not isinstance(array,list):
            try:
                array = json.loads(array)
            except Exception as e:
                print("Array formatted incorrectly")
        if not isinstance(array, list):
            self.node.LogEvent("Iterator Error",data={},error="Array must not be blank and must be a JSON Array")
            return self.node.Trigger(["Finished"])
        if len(array)<=index:
            return self.node.Trigger(["Finished"])
        value = array[index]
        self.node.SetTargetPinData("Value",value)
        self.node.SetTargetPinData("Index",index+1)
        self.node.SetInputPinData_ByName("Index",index+1)
        next_connections = self.node.Trigger(["Next"]) #+ self.node.TriggerSelf("Next","Start")
        return next_connections
        
        

       

    