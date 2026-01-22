from workflow.workflow_datatypes import Pin, NodeConfig, FieldType
from workflow.workflow_executor import Node
import requests
import json
from jinja2 import Template, TemplateSyntaxError

class api_node:
    
    default_setup:NodeConfig = {
        "id":"API",
        "name":"API Node",
        "description": "Trigger an API",
        "pins": {
            "trigger_pins":[{"name":"Start"}],
            "input_pins":[],
            "output_pins":[{"name":"Response"}],
            "next_pins":[{"name":"Next"}]
        },
        "fields":[
            {
                "id":"URL",
                "label":"URL",
                "type":FieldType.SINGLE_LINE,
                "width":"75%"
            },
            {
                "id":"Type",
                "label":"Type",
                "type":FieldType.SINGLE_SELECT,
                "width":"25%",
                "options":["GET","PUT","POST","DELETE"]
            },
            {
                "id":"Headers",
                "label":"Headers",
                "type":FieldType.TEXT,
                "width":"100%"
            },
            {
                "id":"Body",
                "label":"Body",
                "type":FieldType.TEXT,
                "width":"100%"
            }
        ]
    }

    def __init__(self, node:Node):
        self.node = node
        configuration = node.data.get("configuration")
        if(configuration != None):
            self.URL = configuration.get("URL")
            self.Type =configuration.get("Type")
            self.Body = configuration.get("Body")
            self.Headers = configuration.get("Headers")


    def Run(self,connection,data):
        headers = None
        responseObj = None

        url = Template(self.URL)
        self.URL = url.render(**data)
        if self.Headers != None and self.Headers != "":
            headerTemplate = Template(self.Headers)
            self.Headers = headerTemplate.render(**data)
            headers = json.loads(self.Headers)
        if self.Type=="GET":
            self.node.LogEvent(event="API GET",data={"URL":self.URL,"Headers":headers})
            try:
                response = requests.get(self.URL,headers=headers)
                responseObj = response.json()
                self.node.SetTargetPinData(source_pin_name="Response",value=responseObj)
                self.node.LogEvent(event="API Response",data={"Response":responseObj})
            except Exception as e:
                self.node.LogEvent(event="API Error",error=json.dumps(e),data={})
        elif self.Type=="POST":
            body = Template(self.Body)
            self.Body = body.render(**data)
            self.node.LogEvent(event="API POST",data={"URL":self.URL,"Headers":headers,"Body":self.Body})
            try:
                response = requests.post(self.URL,headers=headers,json=json.loads(self.Body))
                responseObj = response.json()
                self.node.SetTargetPinData(source_pin_name="Response",value=responseObj)
                self.node.LogEvent(event="API Response",data={"Response":responseObj})
            except Exception as e:
                self.node.LogEvent(event="API Error",error=json.dumps(e),data={})
        
        return self.node.TriggerAll()

    