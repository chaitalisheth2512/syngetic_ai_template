from workflow.workflow_datatypes import NodeConfig, FieldType
from workflow.workflow_executor import Node
import requests
import json
import traceback

class email_sender_node:

    default_setup: NodeConfig = {
        "id": "EmailSendNode",
        "name": "Send Email",
        "description": "Send email using Resend API",
        "pins": {
            "trigger_pins": [{"name": "Start"}],
            "input_pins": [],
            "output_pins": [{"name": "Response"}],
            "next_pins": [{"name": "Next"}],
        },
        "fields": [

            {
                "id": "ApiKey",
                "label": "Resend API Key",
                "type": FieldType.SINGLE_LINE,
                "width": "100%"
            },
            {
                "id": "FromEmail",
                "label": "From Email",
                "type": FieldType.SINGLE_LINE,
                "width": "50%"
            },
            {
                "id": "FromName",
                "label": "From Name",
                "type": FieldType.SINGLE_LINE,
                "width": "50%"
            },

            {
                "id": "To",
                "label": "To Emails (comma separated)",
                "type": FieldType.TEXT,
                "width": "100%"
            },
            {
                "id": "Cc",
                "label": "CC Emails (comma separated, optional)",
                "type": FieldType.TEXT,
                "width": "100%"
            },
            {
                "id": "Bcc",
                "label": "BCC Emails (comma separated, optional)",
                "type": FieldType.TEXT,
                "width": "100%"
            },

            {
                "id": "Subject",
                "label": "Subject",
                "type": FieldType.SINGLE_LINE,
                "width": "100%"
            },
            {
                "id": "Body",
                "label": "Email Body (HTML allowed)",
                "type": FieldType.TEXT,
                "width": "100%"
            }
        ],
    }

    def __init__(self, node: Node):
        self.node = node
        cfg = node.data.get("configuration") or {}

        self.api_key = cfg.get("ApiKey")
        self.from_email = cfg.get("FromEmail")
        self.from_name = cfg.get("FromName")

        self.to = cfg.get("To") or ""
        self.cc = cfg.get("Cc") or ""
        self.bcc = cfg.get("Bcc") or ""

        self.subject = cfg.get("Subject")
        self.body = cfg.get("Body")

    def Run(self, connection, data):

        response_data = {}

        try:
            # Validate required fields
            if not self.api_key:
                raise Exception("Resend API Key is missing.")
            if not self.from_email:
                raise Exception("From Email is required.")
            if not self.to:
                raise Exception("At least one To email is required.")

            # Prepare sender
            sender = (
                f"{self.from_name} <{self.from_email}>"
                if self.from_name
                else self.from_email
            )

            # Convert comma-separated strings to list
            to_list = [x.strip() for x in self.to.split(",") if x.strip()]
            cc_list = [x.strip() for x in self.cc.split(",") if x.strip()]
            bcc_list = [x.strip() for x in self.bcc.split(",") if x.strip()]

            payload = {
                "from": sender,
                "to": to_list,
                "subject": self.subject,
                "html": self.body
            }

            if cc_list:
                payload["cc"] = cc_list
            if bcc_list:
                payload["bcc"] = bcc_list

            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json"
            }

            # Log the event
            self.node.LogEvent("Sending Email via Resend", data=payload)

            # API call
            response = requests.post(
                "https://api.resend.com/emails",
                headers=headers,
                json=payload
            )

            # Prepare output
            try:
                json_output = response.json()
            except:
                json_output = {}

            response_data = {
                "status": response.status_code,
                "response": json_output,
                "raw": response.text,
            }

            self.node.SetTargetPinData("Response", response_data)
            self.node.LogEvent("Email Sent", data=response_data)

        except Exception as e:
            error_data = {
                "error": str(e),
                "traceback": traceback.format_exc()
            }
            self.node.LogEvent("Email Failed", error=str(e), data=error_data)
            self.node.SetTargetPinData("Response", error_data)

        # Continue workflow chain
        return self.node.TriggerAll()
