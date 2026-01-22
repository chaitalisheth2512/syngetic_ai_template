from workflow.workflow_datatypes import NodeConfig, FieldType


class twilio_trigger_node:
    """
    Twilio Trigger Node
    ------------------
    Handles BOTH:
    - Incoming SMS / MMS
    - Incoming Voice Calls

    Triggered via workflow.globals["twilio_event"]
    """

    default_setup: NodeConfig = {
        "id": "Twilio Trigger",
        "name": "Twilio Trigger",
        "description": "Triggers workflow on Twilio message or call events",
        "pins": {
            "trigger_pins": [],
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
                "id": "event_type",
                "label": "Trigger On",
                "type": FieldType.SINGLE_SELECT,
                "options": ["message", "call", "both"],
            },
            {
                "id": "from_number",
                "label": "Filter Sender (Optional)",
                "type": FieldType.SINGLE_LINE,
            },
            {
                "id": "only_text",
                "label": "Only Text Messages (SMS)",
                "type": FieldType.BOOLEAN,
            },
            {
                "id": "has_media",
                "label": "Only Messages With Media (MMS)",
                "type": FieldType.BOOLEAN,
            },
            {
                "id": "call_status",
                "label": "Call Status Filter (Optional)",
                "type": FieldType.SINGLE_SELECT,
                "options": ["ringing", "in-progress", "completed"],
            },
        ],
    }

    def __init__(self, node):
        self.node = node

    def Run(self, connection, data):

        config = self.node.data.get("configuration", {})

        twilio_event = self.node.workflow.globals.get("twilio_event", {})
        if not twilio_event:
            self.node.LogEvent("No Twilio Event Found", {})
            return []

        event_type = twilio_event.get("type")  # message | call

        # -----------------------------
        # Event Type Filter
        # -----------------------------
        allowed_type = config.get("event_type", "both")
        if allowed_type != "both" and allowed_type != event_type:
            self.node.LogEvent(
                "Event Type Filtered",
                {"expected": allowed_type, "actual": event_type}
            )
            return []

        # -----------------------------
        # Sender Filter
        # -----------------------------
        from_number = twilio_event.get("from")
        filter_sender = config.get("from_number")
        if filter_sender and filter_sender != from_number:
            self.node.LogEvent(
                "Sender Filter Mismatch",
                {"expected": filter_sender, "actual": from_number}
            )
            return []

        # ======================================================
        # MESSAGE HANDLING (SMS / MMS)
        # ======================================================
        if event_type == "message":
            message = twilio_event.get("message", {})
            body = message.get("body")
            media = message.get("media", [])

            if config.get("only_text") and not body:
                self.node.LogEvent("Skipped Non-Text Message", message)
                return []

            if config.get("has_media") and not media:
                self.node.LogEvent("Skipped Message Without Media", message)
                return []

        # ======================================================
        # CALL HANDLING
        # ======================================================
        if event_type == "call":
            call = twilio_event.get("call", {})
            status = call.get("status")

            filter_status = config.get("call_status")
            if filter_status and filter_status != status:
                self.node.LogEvent(
                    "Call Status Filtered",
                    {"expected": filter_status, "actual": status}
                )
                return []

        # -----------------------------
        # Output
        # -----------------------------
        response = {
            "type": event_type,
            "from": twilio_event.get("from"),
            "to": twilio_event.get("to"),
            "timestamp": twilio_event.get("timestamp"),
            "message": twilio_event.get("message"),
            "call": twilio_event.get("call"),
        }

        self.node.SetTargetPinData("Response", response)

        self.node.LogEvent("Twilio Trigger Fired", response)

        return self.node.Trigger(["Next"])
