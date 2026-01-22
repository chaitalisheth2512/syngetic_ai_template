from workflow.workflow_datatypes import Pin, NodeConfig, FieldType
from workflow.workflow_executor import Node
import requests
import json
from jinja2 import Template, TemplateSyntaxError

from openai import OpenAIError
import asyncio
import sys
import os
from services.chat_service import openai_query_withworkflows

class llm_node:
    
    default_setup:NodeConfig = {
        "id":"LLM",
        "name":"LLM Node",
        "description": "Send messages to an LLM",
        "pins": {
            "trigger_pins":[{"name":"Start"}],
            "input_pins":[{"name":"Data"},{"name":"Chat History"}],
            "output_pins":[{"name":"Response"},{"name":"Chat History"}],
            "next_pins":[{"name":"Next"}]
        },
        "fields":[
            {
                "id":"Instructions",
                "label":"Instructions",
                "type":FieldType.TEXT,
                "width":"100%"
            },
            {
                "id":"Message",
                "label":"Message",
                "type":FieldType.TEXT,
                "width":"100%"
            }
        ]
    }

    def __init__(self, node:Node):
        self.node = node
        configuration = node.data.get("configuration")
        self.Instructions = ""
        self.Message = ""
        if(configuration != None):
            self.Instructions =configuration["Instructions"]
            self.Message = configuration["Message"]
        
        print(configuration["Message"],"configuration[""]----------")

    def Run(self,connection,data):
        print(data,"input data-------------------")
        if self.Instructions != None:
            instructionsTemplate = Template(self.Instructions)
            self.Instructions = instructionsTemplate.render(**data)
        if self.Message != None:
            messageTemplate = Template(self.Message)
            self.Message = messageTemplate.render(**data)
        
        body = {
                "input":[
                    {
                        "role":"user",
                        "content":self.Message
                    }
                ]
            }
        if self.Instructions != "":
            body["instructions"] = str(self.Instructions)
        
        if data.get("Chat History") != None:
            body["previous_response_id"] = data["Chat History"]

        # print(body,"body----------------")
        responseText = ""
        try:

            response = openai_query_withworkflows(conversation_id=None,user_id=None,body=body,agent_id=self.node.workflow.agent_id,debug=None,useWorkflows=False)
            if response is not None and response.get("responses") is not None and len(response["responses"])>0:
                responseText = response["responses"][0].get("content")
                self.node.SetTargetPinData("Chat History",response["response_id"])
            else:
                self.node.LogEvent("LLM Error",data={},error="Did not receive a response")
        except Exception as e:
            responseText = f"Error: {e}"
            self.node.LogEvent("LLM Error",data={},error=f"{e}")

        print(responseText,"responsetext-------------")
        
        self.node.SetTargetPinData("Response",responseText)
        
        return self.node.TriggerAll()

    