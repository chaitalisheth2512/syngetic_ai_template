from workflow.workflow_datatypes import NodeConfig, FieldType
import base64
import requests

from jinja2 import Template, TemplateSyntaxError
import re

class gmail_reply_node:
    default_setup: NodeConfig = {
        "id": "Gmail Reply",
        "name": "Gmail - Send Reply",
        "description": "Send a reply to a Gmail message",
        "pins": {
            "trigger_pins": [{"name": "Start"}],
            "input_pins": [
                {"name": "Email"},  # Output of Gmail Trigger
            ],
            "output_pins": [
                {"name": "Response"}
            ],
            "next_pins": [
                {"name": "Next"}
            ]
        },
        "fields": [
            {
                "id": "credential_id",
                "label": "Gmail Account",
                "type": FieldType.SINGLE_LINE
            },
            {
                "id": "content",
                "label": "Reply Message",
                "type": FieldType.TEXT
            }
        ]
    }

    def __init__(self, node):
        self.node = node

    def Run(self, connection, data):
        config = self.node.data.get("configuration", {})
        email = data.get("Email")

        if not email:
            self.node.SetTargetPinData("Response", {
                "error": "No email input provided"
            })
            return self.node.Trigger(["Next"])

        try:
            access_token = get_access_token_from_credential(
                # config.get("credential_id")
            )
        except Exception as e:
            self.node.SetTargetPinData("Response", {
                "error": "Failed to get access token",
                "details": str(e)
            })
            return self.node.Trigger(["Next"])

        reply_text = config.get("content", "")
            
        if not reply_text:
            self.node.SetTargetPinData("Response", {
                "error": "Reply body cannot be empty"
            })
            return self.node.Trigger(["Next"])
        
        print(reply_text,"before reply_text------------")

        # if isinstance(reply_text, str) and re.search(r"{{.*?}}", reply_text):
        try:
            
            template = Template(reply_text)
            reply_text = template.render(**data)

        except TemplateSyntaxError as e:
            response_data = {}
            response_data["error"] = f"Template syntax error: {str(e)}"
            self.node.SetTargetPinData("Response", response_data)
            return self.node.Trigger(["Next"])
        try:
            print(reply_text,"reply_text------------------")
            raw = build_reply_raw(email, reply_text)

            print(raw,"raw---------------")

            payload = {
                "raw": raw,
                "threadId": email.get("thread_id")
            }

            headers = {
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json"
            }

            r = requests.post(
                "https://gmail.googleapis.com/gmail/v1/users/me/messages/send",
                headers=headers,
                json=payload,
                timeout=15
            )
            r.raise_for_status()

            self.node.SetTargetPinData("Response", r.json())
            # self.node.SetTargetPinData("Response", { "message":reply_text } )

        except Exception as e:
            self.node.SetTargetPinData("Response", {
                "error": "Failed to send reply",
                "details": str(e)
            })

        return self.node.Trigger(["Next"])




def build_reply_raw(email, reply_text):
    print(email,"emaillllll---------------")
    headers = []

    headers.append(f"To: {email['from']}")
    headers.append(f"Subject: Re: {email['subject']}")
    headers.append(f"In-Reply-To: {email['message_id']}")
    headers.append(f"References: {email['message_id']}")
    headers.append("Content-Type: text/plain; charset=UTF-8")
    headers.append("")

    body = reply_text

    raw_message = "\r\n".join(headers) + "\r\n" + body

    return base64.urlsafe_b64encode(
        raw_message.encode("utf-8")
    ).decode("utf-8")


GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
def refresh_access_token(refresh_token):
    data = {
        "client_id": "",
        "client_secret": "",
        "refresh_token": refresh_token,
        "grant_type": "refresh_token"
    }

    r = requests.post(GOOGLE_TOKEN_URL, data=data)
    return r.json()["access_token"]

def get_access_token_from_credential():

    access_token = refresh_access_token("")
        
    return access_token
