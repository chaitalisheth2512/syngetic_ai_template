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

class barchart_node:
    
    default_setup:NodeConfig = {
        "id":"BarChart",
        "name":"Bar Chart Node",
        "description": "Construct a JSON Blob representing a defined chart",
        "pins": {
            "trigger_pins":[{"name":"Start"}],
            "input_pins":[{"name":"Chat History"}],
            "output_pins":[{"name":"JSON"}],
            "next_pins":[{"name":"Next"}]
        },
        "fields":[
            {
                "id":"Title",
                "label":"Chart Title",
                "type":FieldType.TEXT,
                "width":"100%"
            },
            {
                "id":"XAxis",
                "label":"X Axis",
                "type":FieldType.TEXT,
                "width":"100%"
            },
            {
                "id":"YAxis",
                "label":"Y Axis",
                "type":FieldType.TEXT,
                "width":"100%"
            },
            {
                "id":"OtherInstructions",
                "label":"Other Instructions",
                "type":FieldType.TEXT,
                "width":"100%"
            }
        ]
    }

    def __init__(self, node:Node):
        self.node = node
        configuration = node.data.get("configuration")
        self.Title = None
        self.XAxis = None
        self.YAxis = None
        self.OtherInstructions = None
        if(configuration != None):
            self.Title =configuration["Title"]
            self.XAxis = configuration["XAxis"]
            self.YAxis = configuration["YAxis"]
            self.OtherInstructions = configuration["OtherInstructions"]

    def Run(self,connection,data):
        userMessage = "Here is some information about the chart I would like you to create. This should be column chart.: \n"
        if self.Title != None and len(self.Title)>0:
            titleTemplate = Template(self.Title)
            self.Title = titleTemplate.render(**data)
            userMessage += "Chart Title: " + self.Title + "\n"
        if self.XAxis != None and len(self.XAxis)>0:
            XAxisTemplate = Template(self.XAxis)
            self.XAxis = XAxisTemplate.render(**data)
            userMessage += "X Axis: " + self.XAxis + "\n"
        if self.YAxis != None and len(self.YAxis)>0:
            YAxisTemplate = Template(self.YAxis)
            self.YAxis = YAxisTemplate.render(**data)
            userMessage += "Y Axis: " + self.YAxis + "\n"
        if self.OtherInstructions != None and len(self.OtherInstructions)>0:
            OtherInstructionsTemplate = Template(self.OtherInstructions)
            self.OtherInstructions = OtherInstructionsTemplate.render(**data)
            userMessage += "Other Instructions: " + self.OtherInstructions + "\n"

        

        
        
        body = {
                "input":[
                    {
                        "role":"user",
                        "content":userMessage
                    }
                ],
                "instructions" : "You are responsible for helping the user construct a chart",
                "text":{
                        "format": {
                            "type": "json_schema",
                            "name": "chart_response",
                            "schema": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "chart": {
                    "type": "object",
                    "additionalProperties": False,
                    "description": "Basic information about the type of chart. Must not be null.",
                    "properties": {
                        "type": {
                        "type": "string",
                        "enum": ["column"],
                        "description": "Type of chart to generate, by default should be 'column'."
                        }
                    },
                    "required": ["type"]
                    },
                    "title": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "text": {
                        "type": "string"
                        },
                        "align": {
                        "type": "string",
                        "enum": ["left"],
                        "description": "How the title should be aligned, default is 'left'."
                        }
                    },
                    "required": ["text", "align"]
                    },
                    "xAxis": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "categories": {
                        "type": "array",
                        "description": "Array representing the elements of the x-axis for this column chart.",
                        "items": {
                            "type": "string"
                        }
                        },
                        "crosshair": {
                        "type": "string",
                        "enum": ["crosshair"]
                        }
                    },
                    "required": ["categories", "crosshair"]
                    },
                    "plotOptions": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "column": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "stacking": {
                            "type": "string",
                            "enum": ["normal"],
                            "description": "Set if the user has requested multiple series to be stacked, otherwise don't include this property."
                            }
                        },
                        "required": ["stacking"]
                        }
                    },
                    "required": ["column"]
                    },
                    "yAxis": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "title": {
                        "type": "object",
                        "additionalProperties": False,
                        "description": "Title for the y-axis.",
                        "properties": {
                            "text": {
                            "type": "string"
                            }
                        },
                        "required": ["text"]
                        }
                    },
                    "required": ["title"]
                    },
                    "series": {
                    "type": "array",
                    "description": "Array of the series objects to use for the chart. In the case of a stacked or grouped column chart, specify multiple series objects.",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                        "name": {
                            "type": "string",
                            "description": "Name of this series."
                        },
                        "data": {
                            "type": "array",
                            "items": {
                            "type": "number",
                            "description": "Values for this series, corresponding to the categories array in the xAxis."
                            }
                        }
                        },
                        "required": ["name", "data"]
                    }
                    }
                },
                "required": ["chart", "title", "xAxis", "plotOptions", "yAxis", "series"]
                }

                    }
                }
            }
        
        if data.get("Chat History") != None:
            body["previous_response_id"] = data["Chat History"]

        responseText = ""
        try:
            response = openai_query_withworkflows(conversation_id=None,user_id=None,body=body,agent_id=self.node.workflow.agent_id,debug=None,useWorkflows=False)
            if response is not None and response.get("responses") is not None and len(response["responses"])>0:
                responseText = response["responses"][0].get("content")
            else:
                self.node.LogEvent("Bar Chart Node Error",data={},error="Did not receive a response")
        except Exception as e:
            responseText = f"Error: {e}"
            self.node.LogEvent("Bar Chart Node Error",data={},error=f"{e}")
        
        try:
            jsonObj = json.loads(responseText)
            jsonObj = {
                "type":"chart",
                "data":jsonObj
            }
            self.node.SetTargetPinData("JSON",jsonObj)
        except Exception as e:
            self.node.LogEvent("Bar Chart Node Error",data={},error=f"LLM Response was not proper JSON: {responseText}, {e}")

        return self.node.TriggerAll()

    