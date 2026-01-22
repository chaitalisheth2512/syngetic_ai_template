import requests
from workflow.workflow_datatypes import NodeConfig, FieldType


class whatsapp_send_message_node:
    """
    WhatsApp Send Message Node
    --------------------------
    Sends a WhatsApp text message using Meta WhatsApp Cloud API
    """

    default_setup: NodeConfig = {
        "id": "WhatsApp Send Message",
        "name": "WhatsApp Send Message",
        "description": "Send a WhatsApp message using Meta WhatsApp Cloud API",
        "pins": {
            "trigger_pins": [{"name": "Start"}],
            "input_pins": [
                {"name": "Message"}
            ],
            "output_pins": [
                {"name": "Response"},
            ],
            "next_pins": [
                {"name": "Next"}
            ],
        },
        "fields": [
            {
                "id": "TO",
                "label": "TO (WhatsApp Number with country code)",
                "type": FieldType.SINGLE_LINE,
            },
            {
                "id": "access_token",
                "label": "WhatsApp Access Token",
                "type": FieldType.SINGLE_LINE,
            },
            {
                "id": "phone_number_id",
                "label": "Business Phone Number ID",
                "type": FieldType.SINGLE_LINE,
            },
        ],
    }

    def __init__(self, node):
        self.node = node

    def Run(self, connection, data):
        config = self.node.data.get("configuration", {})

        access_token = config.get("access_token")
        phone_number_id = config.get("phone_number_id")

        to_number = config.get("TO")
        message_text = data.get("Message")

        if not access_token or not phone_number_id:
            error = "Access Token or Phone Number ID missing"
            self.node.SetTargetPinData("Error", error)
            self.node.LogEvent("Configuration Error", error)
            return self.node.Trigger(["Next"])

        if not to_number or not message_text:
            error = "Recipient number or message text missing"
            self.node.SetTargetPinData("Error", error)
            self.node.LogEvent("Input Error", error)
            return self.node.Trigger(["Next"])

        url = f"https://graph.facebook.com/v22.0/{phone_number_id}/messages"

        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json"
        }

        payload = {
            "messaging_product": "whatsapp",
            "to": str(to_number),
            "type": "text",
            "text": {
                "body": message_text
            }
        }

        try:
            response = requests.post(url, headers=headers, json=payload)
            response_data = response.json()

            if response.status_code >= 400:
                self.node.SetTargetPinData("Response", response_data)
                self.node.LogEvent("WhatsApp API Error", response_data)
            else:
                self.node.SetTargetPinData("Response", response_data)
                self.node.LogEvent("WhatsApp Message Sent", response_data)

        except Exception as e:
            self.node.SetTargetPinData("Error", str(e))
            self.node.LogEvent("Exception", str(e))

        return self.node.Trigger(["Next"])
