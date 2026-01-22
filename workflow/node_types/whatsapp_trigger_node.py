from workflow.workflow_datatypes import NodeConfig, FieldType


class whatsapp_trigger_node:
    """
    WhatsApp Trigger Node
    ---------------------
    This node does NOT receive HTTP requests directly.
    It is triggered by your webhook controller and receives
    WhatsApp payload via workflow globals.
    """

    default_setup: NodeConfig = {
        "id": "WhatsApp Trigger",
        "name": "WhatsApp Trigger",
        "description": "Triggers workflow when a WhatsApp message is received",
        "pins": {
            "trigger_pins": [
                # {"name": "Start"}
            ],
            "input_pins": [],
            "output_pins": [
                {"name": "Response"},
            ],
            "next_pins": [
                {"name": "Next"}
            ],
        },
        "fields": [
            {
                "id": "only_text",
                "label": "Trigger Only Text Messages",
                "type": FieldType.BOOLEAN,
            },
            {
                "id": "from_number",
                "label": "Filter Sender (Optional)",
                "type": FieldType.SINGLE_LINE,
            },
            {
                "id": "account_id",
                "label": "Account ID",
                "type": FieldType.SINGLE_LINE,
            },
            {
                "id": "secret_key",
                "label": "Secret Key",
                "type": FieldType.SINGLE_LINE,
            },
        ],
    }

    def __init__(self, node):
        self.node = node

    def Run(self, connection, data):
        """
        WhatsApp event is injected by webhook via workflow globals.
        """

        config = self.node.data.get("configuration", {})

        # Get WhatsApp event from workflow globals (injected by webhook)
        whatsapp_event = self.node.workflow.globals.get("whatsapp_event", {})

        if not whatsapp_event:
            self.node.LogEvent(
                event="No WhatsApp Event Found",
                data={}
            )
            print("No WhatsApp Event Found---------------------")
            return []

        # Extract fields
        from_number = whatsapp_event.get("from")
        to_number = whatsapp_event.get("to")
        message = whatsapp_event.get("text")
        message_id = whatsapp_event.get("message_id")
        timestamp = whatsapp_event.get("timestamp")

        # -----------------------------
        # Filters
        # -----------------------------
        if config.get("only_text") is True and not message:
            self.node.LogEvent(
                event="Skipped Non-Text Message",
                data=whatsapp_event
            )
            print("Skipped Non-Text Message---------------------")
            return []

        filter_sender = config.get("from_number")
        if filter_sender and filter_sender != from_number:
            self.node.LogEvent(
                event="Sender Filter Mismatch",
                data={"expected": filter_sender, "actual": from_number}
            )
            print("Sender Filter Mismatch---------------------")
            return []

        # -----------------------------
        # Output Pins
        # -----------------------------
        response = {
            "from": from_number,
            "to": to_number,
            "message": message,
            "message_id": message_id,
            "timestamp": timestamp
        }
        self.node.SetTargetPinData("Response", response)

        self.node.LogEvent(
            event="WhatsApp Trigger Fired",
            data=whatsapp_event
        )

        print(response,"WhatsApp Trigger Fired---------------------")
        # Continue workflow
        return self.node.Trigger(["Next"])
