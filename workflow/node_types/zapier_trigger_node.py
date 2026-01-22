from workflow.workflow_datatypes import Pin, NodeConfig, FieldType
from workflow.workflow_executor import Node
import requests
import json


class zapier_trigger_node:
    default_setup: NodeConfig = {
        "id": "ZapierNode",
        "name": "Zapier Webhook Trigger",
        "description": "Send data to a Zapier webhook and optionally trigger other automations",
        "pins": {
            "trigger_pins": [{"name": "Start"}],
            "input_pins": [
                {"name": "Payload"},
                {"name": "QueryParams"}
            ],
            "output_pins": [
                {"name": "Response"},
            ],
            "next_pins": [{"name": "Next"}]
        },
        "fields": [
            {
                "id": "WebhookURL",
                "label": "Zapier Webhook URL",
                "type": FieldType.SINGLE_LINE,
                "width": "100%"
            },
            {
                "id": "Method",
                "label": "HTTP Method",
                "type": FieldType.SINGLE_SELECT,
                "options": ["POST", "GET"],
                "width": "25%"
            },
            {
                "id": "QueryParams",
                "label": "Query Parameters (JSON Format)",
                "type": FieldType.TEXT,
                "width": "100%"
            },
            {
                "id": "Payload",
                "label": "Payload (JSON Format) – Optional if using input pin",
                "type": FieldType.TEXT,
                "width": "100%"
            },
            {
                "id": "Headers",
                "label": "Custom Headers (JSON Format, optional)",
                "type": FieldType.TEXT,
                "width": "100%"
            },
            {
                "id": "Timeout",
                "label": "Request Timeout (seconds)",
                "type": FieldType.SINGLE_LINE,
                "width": "25%"
            }
        ]
    }

    def __init__(self, node: Node):
        self.node = node
        cfg = node.data.get("configuration") or {}
        self.webhook_url = cfg.get("WebhookURL")
        self.method = (cfg.get("Method") or "POST").upper()
        self.payload_str = cfg.get("Payload")
        self.query_str = cfg.get("QueryParams")
        self.headers_str = cfg.get("Headers")
        self.timeout = int(cfg.get("Timeout") or 10)

    def Run(self, connection, data):
        print("\n================= [ZapierNode] DEBUG START =================")
        print(f"Webhook URL: {self.webhook_url}")
        print(f"Method: {self.method}")

        try:
            # 1️⃣  Build payload
            payload = None

            if "Payload" in data and data["Payload"]:
                payload = data["Payload"]
                print("📩 Using payload from input pin.")
            elif self.payload_str:
                payload = json.loads(self.payload_str)
                print("📄 Using payload from configuration.")
            else:
                payload = {}

            # 2️⃣  Build query params
            query_params = {}
            if "QueryParams" in data and data["QueryParams"]:
                query_params = data["QueryParams"]
            elif self.query_str:
                query_params = json.loads(self.query_str)

            # 3️⃣  Build headers
            headers = {}
            if self.headers_str:
                headers = json.loads(self.headers_str)

            # 4️⃣  Make HTTP request
            print("🔗 Sending request to Zapier...")
            if self.method == "POST":
                response = requests.post(
                    self.webhook_url,
                    json=payload,
                    params=query_params,
                    headers=headers,
                    timeout=self.timeout
                )
            else:
                response = requests.get(
                    self.webhook_url,
                    params=query_params,
                    headers=headers,
                    timeout=self.timeout
                )

            print(f"✅ Zapier Response Code: {response.status_code}")

            # 5️⃣  Return response as output
            response_data = {
                "status": response.status_code,
                "text": response.text,
                "json": None
            }

            try:
                response_data["json"] = response.json()
            except Exception:
                pass  # ignore if response is not JSON

            self.node.LogEvent("Zapier Call Successful", data=response_data)
            self.node.SetTargetPinData("Response", response_data)

        except Exception as e:
            self.node.LogEvent("Zapier Call Failed", data={}, error=str(e))
            print(f"❌ Zapier Error: {str(e)}")

        print("================= [ZapierNode] DEBUG END =================\n")
        return self.node.TriggerAll()
