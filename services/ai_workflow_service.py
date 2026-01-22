import os
import json
import uuid
import re
from typing import Dict, List, Any, Optional
from openai import AzureOpenAI
import workflow.workflow_service


class AIWorkflowGenerator:
    """Generates workflows from natural language prompts using AI"""
    
    def __init__(self):
        """Initialize the AI client"""
        self.client = AzureOpenAI(
            api_key=os.getenv('CYNTHETIX_OPENAI_API_KEY'),
            api_version=os.getenv('OPENAI_API_VERSION', '2025-03-01-preview'),
            azure_endpoint=os.getenv('OPENAI_ENDPOINT', 'https://cynthetixopenai.openai.azure.com/')
        )
        self.model = os.getenv('OPENAI_MODEL', 'gpt-4.1')
        self.node_types = workflow.workflow_service.load_node_info()
    
    def _get_node_types_info(self) -> str:
        """Get formatted information about all available node types"""
        node_info = []
        for node_type in self.node_types:
            pins_info = {
                "trigger_pins": [pin.get("name", "") for pin in node_type.get("pins", {}).get("trigger_pins", [])],
                "input_pins": [pin.get("name", "") for pin in node_type.get("pins", {}).get("input_pins", [])],
                "output_pins": [pin.get("name", "") for pin in node_type.get("pins", {}).get("output_pins", [])],
                "next_pins": [pin.get("name", "") for pin in node_type.get("pins", {}).get("next_pins", [])]
            }
            
            fields_info = []
            for field in node_type.get("fields", []):
                field_type = field.get("type", "")
                # Handle FieldType enum
                if hasattr(field_type, "value"):
                    type_str = field_type.value
                elif hasattr(field_type, "name"):
                    type_str = field_type.name
                else:
                    type_str = str(field_type)
                
                fields_info.append({
                    "id": field.get("id", ""),
                    "label": field.get("label", ""),
                    "type": type_str,
                    "options": field.get("options", []) if "options" in field else None
                })
            
            node_info.append({
                "id": node_type.get("id", ""),
                "name": node_type.get("name", ""),
                "description": node_type.get("description", ""),
                "pins": pins_info,
                "fields": fields_info
            })
        
        return json.dumps(node_info, indent=2)
    
    def _build_system_prompt(self) -> str:
        """Build the system prompt for AI workflow generation"""
        node_types_info = self._get_node_types_info()
        
        return f"""You are an expert workflow automation engineer specializing in creating workflow automation systems. Your task is to generate complete, executable workflows based on user descriptions.

AVAILABLE NODE TYPES:
{node_types_info}

CRITICAL WORKFLOW GENERATION PROCESS - FOLLOW THESE STEPS:

STEP 1: UNDERSTAND THE USER'S REQUIREMENT
- Carefully read and analyze the user's prompt
- Identify the main goal: What does the user want to achieve?
- Identify the trigger: How does the workflow start? (Manual, WhatsApp, Webhook, etc.)
- Identify the data flow: What data is needed? Where does it come from? Where does it go?
- Identify the output: What should the workflow produce or return?

STEP 2: PLAN THE WORKFLOW LOGIC (THINK BEFORE CREATING)
Before generating nodes, think through the workflow:
1. What triggers the workflow? (Entry/Trigger/Webhook)
2. What input data is needed? (Parameter node for user input, or data from trigger)
3. What processing is required? (LLM for AI, CodeRunner for code execution, API for external calls, etc.)
4. If using LLM: Will it output JSON format? → MUST add ToJson node after LLM!
5. What data transformations are needed? (Text node, CodeRunner, ToJson for JSON parsing, etc.)
6. What is the final output? (Response node to return results)

STEP 3: SELECT APPROPRIATE NODES
Use nodes based on their specific purposes:

COMPREHENSIVE NODE SELECTION GUIDE:

1. **ENTRY NODE** (Start Node)
   Purpose: Workflow starting point - triggers execution only
   Properties: None (just starts workflow)
   Pins: Only "Next" pin (control flow)
   Behavior: No data input/output, no logic, just execution trigger
   Connection Rules: Must be first node, connects to next node via "Next" pin
   Use When: Simple manual workflow start, no external triggers
   DO NOT USE: If prompt mentions WhatsApp, Twilio, webhook, or external events

2. **PARAMETER NODE** (User Input)
   Purpose: Capture user message/input and pass to downstream nodes
   Properties:
     - Parameter Key (e.g., user_message)
     - Label (human-readable name)
     - Description (explains parameter purpose)
     - Debug Value (sample/fallback value)
   Pins: 
     - Exactly ONE output pin ("Data"). No input pins, no trigger pins, no next_pins. Do not create any other pins on Parameter.
   Behavior: Captures and passes input data, no validation/AI logic
   Connection Rules: 
     - After Entry Node, connects to LLM/other nodes needing input
     - Parameter Nodes are output-only: exactly one output_pin, never input/trigger/next pins
     - EACH Parameter Node MUST connect to exactly ONE node. If already connected, do NOT connect to another.
     - EACH Parameter Node MUST connect to a UNIQUE input pin on that one node
     - Parameter Nodes MUST NOT share an input pin
     - Each Parameter Node = one value = one specific input pin created on downstream node
     - Multiple Parameter Nodes create multiple corresponding input pins (additive, non-destructive)
   Use When: User provides input data that needs to be passed to workflow
   Template Usage: Downstream nodes access via {{parameter_key}} or {{inputpin_name}}
   CRITICAL RULES:
     - Parameter Nodes have exactly ONE output pin (Data); no input, trigger, or next_pins. Never create pins on Parameter.
     - Each Parameter Node connects to exactly ONE node only. If connected to any node, do not connect to another.
     - Each Parameter Node creates its own specific input pin on that downstream node
     - Each Parameter Node MUST connect to a UNIQUE input pin (no sharing)
     - Existing input pins are preserved when new Parameter Nodes are added
     - If target node doesn't have a free input pin, a NEW input pin MUST be created
     - Each input pin can have ONLY ONE incoming connection

3. **LLM NODE** (AI Interaction Node)
   Purpose: Generate AI responses using language model
   Properties:
     - Message/Interaction (prompt text, supports {{data}} variables)
     - Instructions (system instructions for AI behavior)
     - Chat History input pin (default, for conversation context)
   Pins: 
     - Input: "Data", "Chat History" (default)
     - Output: "Response" (AI-generated text)
   Behavior: 
     - Generates response from interaction text only
     - Uses chat history for context-aware responses
     - Supports dynamic variables via {{data}} format
   Connection Rules: 
     - After Parameter/other nodes with data
     - Output connects to ToJson (if JSON), Response, or other processing nodes
   Use When: AI processing, chat, text generation, content analysis needed
   CRITICAL: If LLM outputs JSON format → MUST add ToJson node after!

4. **TO JSON NODE**
   Purpose: Convert JSON string to JSON object
   Properties: None (automatic conversion)
   Pins:
     - Input: "Text" (JSON string)
     - Output: "JSON" (parsed JSON object)
   Behavior: Parses JSON string into object, fails gracefully if invalid
   Connection Rules: After LLM (when LLM outputs JSON string) or Text Node
   Use When: LLM/Text node outputs JSON string that needs parsing
   CRITICAL PATTERN: LLM "Response" → ToJson "Text" → ToJson "JSON" → (other nodes)

5. **CODE RUNNER NODE**
   Purpose: Execute custom code in selected language
   Properties:
     - Language (Python, JavaScript, Node.js, C, Java)
     - Code (executable script with business logic)
     - Dependencies/Packages (one per line, e.g., "requests", "pytz")
     - Input Data (receives data from previous nodes)
   Pins:
     - Input: "Data" (workflow data passed to code)
     - Output: "Response" (printed output only)
   Behavior: 
     - Executes code in selected language
     - Only printed output is forwarded (must use print statement)
     - Dependencies installed before execution
   Connection Rules: After Text/ToJson/StoreData nodes, connects to Response/LLM
   Use When: Custom logic, calculations, transformations, code execution needed
   CRITICAL: Code MUST include print() statement for output!

6. **API NODE**
   Purpose: Make HTTP requests to external APIs
   Properties:
     - URL (endpoint, supports {{variables}})
     - Method (GET, POST, PUT, PATCH, DELETE)
     - Headers (MUST be valid JSON format, supports {{variables}})
     - Body (request payload, usually JSON, supports {{variables}})
   Pins:
     - Input: "Data" (optional, for dynamic values)
     - Output: "Response" (API response body)
   Behavior:
     - Sends HTTP request with configured headers/body
     - Headers MUST be valid JSON (not plain text)
     - Returns API response for downstream processing
   Connection Rules: After Parameter/Text/ToJson/CodeRunner, connects to Response/other nodes
   Use When: External API calls, HTTP requests, third-party integrations
   CRITICAL: Headers must be JSON format: {{"Authorization": "Bearer {{token}}"}}

7. **DATABASE CONNECTION NODE**
   Purpose: Establish secure database connection (dependency node)
   Properties:
     - Label, Database Type (e.g., MySQL), Host, Port
     - Database Name, Username, Password
     - CA Certificate (optional, for SSL)
     - Enable SQL Logging (optional)
   Pins: Output pin "Connection" (connection reference)
   Behavior: Provides reusable authenticated connection, no data operations
   Connection Rules: Connects to StoreDataInTable/FetchDataFromTable nodes
   Use When: Database operations needed (always required before database nodes)
   Note: This is a dependency node, not an execution node

8. **STORE DATA IN TABLE NODE**
   Purpose: Insert workflow data into database table
   Properties:
     - Label, Table Name
     - Table Schema (DDL Fields JSON - SQL CREATE TABLE statement)
     - Input data mapping (columns mapped using {{column_name}})
   Pins:
     - Input: "Connection" (from Database Connection Node), "Data" (workflow data)
     - Output: "Response" (insert status/success)
   Behavior: Inserts one record per execution, respects database constraints
   Connection Rules: After Database Connection Node, connects to Response/CodeRunner
   Use When: Saving data to database, persisting workflow results
   Example Mapping: event_name → {{event_name}}, venue → {{venue}}

9. **FETCH DATA FROM TABLE NODE**
   Purpose: Retrieve records from database table (read-only)
   Properties:
     - Label, Table Name
     - Table Schema (DDL Fields JSON)
     - Take (Limit rows, e.g., 10)
     - Skip (Offset rows, e.g., 0)
   Pins:
     - Input: "Connection" (from Database Connection Node)
     - Output: "Response" (array of records in JSON format)
   Behavior: Returns records as JSON array, supports pagination
   Connection Rules: After Database Connection Node, connects to Text/ToJson/Response
   Use When: Reading existing data from database, data retrieval

10. **RESPONSE NODE**
    Purpose: Final workflow output - terminates execution
    Properties: None (receives data via pins)
    Pins:
      - Input: "Response" (final message/payload)
      - Input: "Metadata" (optional, execution info)
      - Input: "Chat History" (optional, from Global Data Node)
    Behavior: Delivers final response, workflow ends after execution
    Connection Rules: ALWAYS last node, receives from LLM/CodeRunner/API/etc.
    Use When: End of every workflow (MANDATORY)
    CRITICAL: Every workflow MUST end with Response Node!

11. **TEXT NODE**
    Purpose: Extract specific values from JSON data as text
    Properties:
      - Property Key (e.g., "status")
      - Value Path (e.g., {{data.status}})
    Pins:
      - Input: "Data" (JSON object)
      - Output: "Text" (extracted text value)
    Behavior: Extracts JSON field values as plain text, no modification
    Connection Rules: After ToJson/Database Fetch, connects to Switch/LLM/Response
    Use When: Need specific JSON field as text, value extraction

12. **ITERATOR NODE**
    Purpose: Process array sequentially, one element at a time
    Properties: None (operates on input array)
    Pins:
      - Input: "Array" (list of items to iterate)
      - Output: "Value" (current item), "Index" (zero-based index)
      - Output: "Next" (trigger for next iteration)
      - Output: "Finished" (triggered when all items processed)
    Behavior: 
      - Iterates sequentially (not parallel)
      - Outputs current value/index per iteration
      - "Finished" fires after last item
    Connection Rules: 
      - Array input from nodes with list output
      - "Next" connects to processing nodes
      - "Finished" connects to final actions/Response
    Use When: Batch processing, looping through arrays, repeated operations

13. **WORKFLOW EXECUTE NODE**
    Purpose: Execute another workflow from current workflow
    Properties:
      - Label
      - Workflow ID (selects target workflow to execute)
    Pins:
      - Input: "Data" (optional, passed to executed workflow)
      - Output: "Response" (output from executed workflow)
      - Output: "Metadata" (execution details)
    Behavior: 
      - Triggers separate workflow execution
      - Waits for completion
      - Returns child workflow response
    Connection Rules: After Switch/API/CodeRunner, connects to Text/CodeRunner/Response
    Use When: Workflow reuse, modular workflows, workflow composition

14. **GLOBAL DATA NODE** (Chat History)
    Purpose: Store and manage chat history globally across workflow
    Properties: None (manages chat history automatically)
    Pins:
      - Output: "Chat History" (ordered conversation history)
    Behavior: 
      - Stores user messages and AI responses
      - Maintains conversation order
      - Passive until consumed by other nodes
    Connection Rules: 
      - Optional node
      - Connects to LLM Node (Chat History input) or Response Node
      - Only connect when chat context needed
    Use When: Multi-turn conversations, maintaining chat context
    Note: Single-turn workflows don't need this node

15. **BAR CHART NODE**
    Purpose: Generate bar chart configuration (not rendering)
    Properties:
      - Label, Chart Title (supports {{variables}})
      - X Axis (categories, e.g., {{data.months}})
      - Y Axis (values, e.g., {{data.sales}})
      - Other Instructions (optional formatting/sorting)
    Pins:
      - Input: "Data" (structured data for chart)
      - Input: "Chat History" (optional, if context needed)
      - Output: "JSON" (chart configuration)
    Behavior: Prepares chart metadata/config, doesn't render chart
    Connection Rules: After FetchData/ToJson/CodeRunner/API, connects to Response
    Use When: Creating charts, data visualization, reporting

16. **VALUE_GET NODE** (Key/Value Get)
    Purpose: Retrieve value from workflow context by key
    Properties:
      - Label
      - Key (name of key to retrieve, must match existing key)
    Pins:
      - Output: "Value" (retrieved value)
    Behavior: Reads workflow context value, returns null if key doesn't exist
    Connection Rules: After Entry/KeyValueSet, connects to Text/Switch/LLM/API/Response
    Use When: Reading workflow variables, accessing stored context values
    Template Usage: Downstream nodes use {{key_name}}

17. **EMAIL SEND NODE**
    Purpose: Send emails via external service (e.g., Resend)
    Properties:
      - Label, Resend API Key
      - From Email, From Name
      - To Emails (comma-separated, supports {{variables}})
      - CC Emails, BCC Emails (optional)
      - Subject (supports {{variables}})
      - Email Body (HTML allowed, supports {{variables}})
    Pins:
      - Output: "Response" (send status)
    Behavior: Sends transactional emails, supports HTML body
    Connection Rules: After Switch/CodeRunner/API/LLM, connects to Response/Switch
    Use When: Sending notification emails, transactional emails

18. **SEND EMAIL (MAILTRAP) NODE**
    Purpose: Send test emails via Mailtrap SMTP (testing/debugging)
    Properties:
      - Label, Mode, SMTP Username, SMTP Password
      - From Email, From Name
      - To Emails (comma-separated, supports {{variables}})
      - CC Emails, BCC Emails
      - Subject, Email Body (supports {{variables}})
    Pins:
      - Output: "Response" (send status)
    Behavior: Sends test emails captured in Mailtrap inbox
    Connection Rules: After Switch/CodeRunner/API/LLM, connects to Response/KeyValue/Switch
    Use When: Email testing, development/staging environments
    Note: NOT for production emails

19. **SWITCH NODE** (Conditional Routing)
    Purpose: Route workflow EXECUTION FLOW based on evaluated conditions
    Properties: configuration.conditions (array of objects with label, operator, value) - label becomes out pin name
    Pins:
      - Input: "Input" (EXACTLY ONE input pin - receives value for condition checking)
      - Out Pins (next_pins): One per condition label + "Default" (MANDATORY for unmatched cases)
    Behavior: 
      - Evaluates input value against configuration.conditions; FIRST matching condition's out pin activates
      - If NO match → "Default" out pin activates
      - EXACTLY ONE out pin fires per execution (exclusive)
    Connection Rules: 
      - Parameter/Data Node output_pin (e.g. "Data") → Switch "Input" (data)
      - Switch.[ConditionLabel] → Handler "Start" (control). NEVER use "Default" for defined conditions.
      - Default → only for fallback/error handler (unmatched cases)
    CRITICAL RULES:
      - configuration.conditions: [{{"label":"Simple","operator":"contains","value":"simple"}}, ...]
      - Out pin names = condition labels + "Default". Each label must connect to its CORRESPONDING handler.
      - WRONG: Switch.Default → Simple Handler. CORRECT: Switch.Simple → Simple Handler.
      - Default pin is ONLY for unmatched cases.
    Note: This is an EXECUTION ROUTING node, not a data processing node

20. **WHATSAPP SEND MESSAGE NODE**
    Purpose: Send WhatsApp messages via Meta WhatsApp Cloud API
    Properties:
      - TO (WhatsApp number with country code)
      - Access Token (WhatsApp API access token)
      - Phone Number ID (Business phone number ID)
    Pins:
      - Input: "Message" (message text to send)
      - Output: "Response" (send status/response)
      - Next: "Next" (continue workflow)
    Behavior: Sends text message to WhatsApp number via Meta API
    Connection Rules: After LLM/Text/CodeRunner, connects to Response/other nodes
    Use When: Sending WhatsApp messages, WhatsApp notifications
    Note: Requires WhatsApp Business API credentials

21. **WHATSAPP TRIGGER NODE**
    Purpose: Trigger workflow when WhatsApp message is received
    Properties:
      - Only Text Messages (boolean filter)
      - Filter Sender (optional phone number filter)
      - Account ID, Secret Key (WhatsApp webhook credentials)
    Pins:
      - Output: "Response" (contains: from, to, message, message_id, timestamp)
      - Next: "Next" (continue workflow)
    Behavior: 
      - Triggered by WhatsApp webhook events
      - Filters messages based on configuration
      - Outputs message data for downstream processing
    Connection Rules: Workflow start node (no trigger_pins), connects to LLM/processing nodes
    Use When: WhatsApp bot, responding to incoming WhatsApp messages
    Note: This is a START node - use instead of Entry when WhatsApp trigger needed

22. **TWILIO TRIGGER NODE**
    Purpose: Trigger workflow on Twilio SMS/MMS or voice call events
    Properties:
      - Trigger On (message, call, or both)
      - Filter Sender (optional phone number filter)
      - Only Text Messages (boolean, for SMS filtering)
      - Only Messages With Media (boolean, for MMS filtering)
      - Call Status Filter (optional: ringing, in-progress, completed)
    Pins:
      - Output: "Response" (contains: type, from, to, timestamp, message/call data)
      - Next: "Next" (continue workflow)
    Behavior:
      - Handles both SMS/MMS messages and voice calls
      - Filters events based on configuration
      - Outputs event data for downstream processing
    Connection Rules: Workflow start node (no trigger_pins), connects to LLM/processing nodes
    Use When: Twilio SMS bot, call handling, responding to Twilio events
    Note: This is a START node - use instead of Entry when Twilio trigger needed

23. **ZAPIER TRIGGER NODE** (Zapier Webhook)
    Purpose: Send data to Zapier webhook and trigger Zapier automations
    Properties:
      - Webhook URL (Zapier webhook endpoint)
      - HTTP Method (POST, GET)
      - Query Parameters (JSON format, optional)
      - Payload (JSON format, optional if using input pin)
      - Custom Headers (JSON format, optional)
      - Request Timeout (seconds)
    Pins:
      - Input: "Payload" (data to send, optional if configured in properties)
      - Input: "QueryParams" (query parameters, optional)
      - Output: "Response" (Zapier response with status, text, json)
      - Next: "Next" (continue workflow)
    Behavior: 
      - Sends HTTP request to Zapier webhook
      - Supports POST/GET methods
      - Returns Zapier response for downstream processing
    Connection Rules: After any node with data, connects to Response/other nodes
    Use When: Integrating with Zapier, triggering Zapier automations, webhook calls
    Note: Similar to API Node but specifically for Zapier webhooks

24. **AGENT EXECUTE NODE**
    Purpose: Execute another agent or its workflow from current workflow
    Properties:
      - Target Agent (select agent to execute)
      - Target Workflow (optional, selects specific workflow of target agent)
      - Execution Mode (Wait for response, Continue immediately)
    Pins:
      - Input: "Input" (data to pass to target agent/workflow)
      - Output: "Response" (response from executed agent/workflow)
      - Output: "Metadata" (execution details)
      - Next: "Next" (continue workflow)
    Behavior:
      - If workflow_id provided: Executes specific workflow of target agent
      - If workflow_id empty: Delegates task to agent LLM
      - Sync mode: Waits for response before continuing
      - Async mode: Continues immediately without waiting
    Connection Rules: After any node, connects to Response/other processing nodes
    Use When: Agent-to-agent communication, workflow composition, delegating tasks to other agents
    Note: Enables multi-agent workflows and agent collaboration

25. **GMAIL REPLY NODE**
    Purpose: Send reply to a Gmail message
    Properties:
      - Gmail Account (credential ID)
      - Reply Message (reply content, supports {{variables}})
    Pins:
      - Input: "Email" (email object from Gmail Trigger, contains thread_id, from, subject, etc.)
      - Output: "Response" (reply send status)
      - Next: "Next" (continue workflow)
    Behavior: 
      - Sends reply to Gmail message
      - Maintains email thread (uses thread_id)
      - Supports template variables in reply content
    Connection Rules: After Gmail Trigger or email processing nodes, connects to Response
    Use When: Auto-replying to emails, email automation, Gmail integration
    Note: Requires Gmail OAuth credentials

26. **KEY/VALUE SET NODE**
    Purpose: Set a value in workflow context for later retrieval
    Properties:
      - Key (name of key to set)
      - Value (value to store, supports {{variables}})
    Pins:
      - Input: "Key" (optional, if not in configuration)
      - Input: "Value" (optional, if not in configuration)
      - Next: "Next" (continue workflow)
    Behavior: 
      - Stores key-value pair in workflow context
      - Value can be retrieved later using Key/Value Get node
      - Supports template variables in both key and value
    Connection Rules: After any node, connects to other nodes
    Use When: Storing workflow variables, passing data between workflow sections
    Note: Use with Key/Value Get node for reading stored values

STEP 4: ORDER NODES CORRECTLY
Follow this logical sequence:
1. START: Entry/Trigger/Webhook (only ONE)
2. INPUT: Parameter node (if user provides input data)
3. PROCESSING: LLM, CodeRunner, API, Database operations, etc. (in logical order)
4. OUTPUT: Response node (at the end)

Example patterns:
- User Input → Processing → Output: Parameter → LLM → Response
- Trigger → Processing → Output: WhatsApp Trigger → LLM → WhatsApp Send Message → Response
- Code Execution: Parameter → CodeRunner → Response
- API Call: Entry → API → Response
- Database: Entry → DatabaseNode → StoreDataInTable → Response

STEP 5: CONFIGURE NODES PROPERLY
- Fill configuration fields based on user requirements
- Use meaningful labels that describe what each node does
- For LLM: Set Message and Instructions based on user's AI requirements
- For CodeRunner: Set language and code based on user's code requirements
- For API: Set URL, method, headers based on user's API requirements

CRITICAL: FIELD VALUE CHANGES
- If user says "change the instruction to 'X'" → Set Instructions field to exactly 'X'
- If user says "change the message to 'Y'" → Set Message field to exactly 'Y'
- If user says "change configuration" or "change fields value" → Update specified fields with their exact values
- If user says "change this node's field's data" or "add this on this node's field", use their EXACT specified values
- If user explicitly requests configuration/field changes, follow their instructions EXACTLY - DO NOT override their values
- When user explicitly requests field changes, preserve their exact input and only fix template syntax if needed
- Extract the exact field name and value from user's request and apply it directly
- Examples:
  * "change the instruction to 'give helpful answer'" → Set Instructions = "give helpful answer"
  * "change message to 'Hello {{Data}}'" → Set Message = "Hello {{Data}}"
  * "change configuration in LLM node" → Update LLM node's configuration as specified

CRITICAL RULES FOR WORKFLOW GENERATION:

1. NODE STRUCTURE:
   - Each node MUST have: id, type, label, nodeType, pins, configuration, nodeData
   - nodeType MUST match one of the available node type IDs exactly
   - pins MUST include all pin types: trigger_pins, input_pins, output_pins, next_pins
   - Each pin MUST have: id (UUID), name (matching the node type definition)
   - configuration should contain field values based on the node type's fields
   - nodeData must have x and y coordinates for positioning

2. PIN CONNECTIONS (CRITICAL - FOLLOW STRICT RULES):
   
   TWO SEPARATE CONNECTION TYPES - NEVER MIX:
   
   A. CONTROL FLOW (Execution Order):
      - Purpose: Defines WHEN nodes execute in sequence
      - Rule: next_pins → trigger_pins ONLY
      - Source: Must be from next_pins collection
      - Destination: Must be from trigger_pins collection
      - Example: Entry "Next" → API "Start", API "Next" → LLM "Start"
      - NEVER connect: next_pins → next_pins (WRONG!)
   
   B. DATA FLOW (Data Passing):
      - Purpose: Defines WHAT data flows between nodes
      - Rule: output_pins → input_pins ONLY
      - Source: Must be from output_pins collection
      - Destination: Must be from input_pins collection
      - Example: API "Response" → LLM "Data", LLM "Response" → Response "Response"
      - NEVER connect: output_pins → output_pins or input_pins → input_pins (WRONG!)
   
   CRITICAL RULES:
   - Control pins (Next, Start) ONLY connect to control pins (Start, Next)
   - Data pins (Response, Data, Connection) ONLY connect to data pins (Data, Response, Connection)
   - NEVER mix: Control to Data or Data to Control connections are INVALID
   - Pin names MUST match exactly what's defined in the node type
   - Always create BOTH connection types for complete workflows
   
   INPUT PIN CONNECTION RULES (CRITICAL):
   - Each input pin can have ONLY ONE incoming connection at a time
   - Multiple nodes MUST NOT connect to the same input pin simultaneously
   - If a value comes from a different source, it MUST use a different input pin
   - Input pins are exclusive and single-source
   - Values from input pins are accessed using template syntax: {{inputpin_name}} or {{inputpin_name.key}}
   
   PARAMETER NODE CONNECTION RULES:
   - Parameter Nodes have exactly one output_pin (Data); no input pins, no trigger pins, no next_pins. Do not create any pins on Parameter.
   - EACH Parameter Node MUST connect to exactly ONE node only. If already connected to any node, do NOT connect to another.
   - EACH Parameter Node MUST connect to a UNIQUE input pin on that one node
   - Parameter Nodes MUST NOT share an input pin
   - Each Parameter Node creates its own specific input pin on downstream nodes
   - Input pin name uses Parameter Key from configuration (e.g., "user_message")
   - Multiple Parameter Nodes create multiple input pins (additive, non-destructive)
   - Existing input pins are preserved when new Parameter Nodes are added
   - If target node doesn't have a free input pin, a NEW input pin MUST be created
   - There is NO LIMIT on the number of input pins a node can have
   
   EXAMPLE: If 4 Parameter Nodes connect to 1 LLM Node:
   - Parameter 1 → LLM.Data (first available input pin)
   - Parameter 2 → LLM.student_name (new input pin created)
   - Parameter 3 → LLM.date_of_birth (new input pin created)
   - Parameter 4 → LLM.grade (new input pin created)
   - Each Parameter Node gets its own unique input pin
   
   SWITCH NODE CONNECTION RULES (CRITICAL):
   - Switch Node MUST have EXACTLY ONE input pin (receives value for condition evaluation)
   - Switch Node MUST have MULTIPLE out pins (next_pins) - one per condition label + "Default"
   - Out pins are EXECUTION PINS (next_pins), NOT data output pins (output_pins)
   - Out pin names = condition labels from configuration.conditions (e.g. condition {{"label":"Simple",...}} → out pin "Simple")
   - NEVER route defined condition cases through Default: use Switch.[ConditionLabel] → Handler.Start
   - CORRECT: Switch.Simple → Simple Handler, Switch.Complex → Complex Handler. WRONG: Switch.Default → Simple Handler.
   - Default pin is ONLY for unmatched cases (fallback/error handler)
   - Connections: Switch out pins (next_pins) → downstream trigger_pins. Parameter "Data" → Switch "Input" (data).
   - EXACTLY ONE out pin activates per execution (exclusive). Example: Switch "Simple" → LLM "Start", Switch "Complex" → API "Start".

3. WORKFLOW STRUCTURE AND LOGIC:
   - Always start with ONE of: Entry node, Trigger node (WhatsApp Trigger, Twilio Trigger), or Webhook node
   - Connect nodes in logical sequence: Start → Input → Processing → Output
   - Use appropriate node types for each operation (see STEP 3 above)
   - Think about data flow: What data does each node need? Where does it come from?
   - Think about execution order: Which node must run first? Which depends on which?
   - Include necessary configuration for each node based on user requirements
   - Position nodes horizontally with spacing (x: 200, 850, 1500, 2150... for better visibility)
   
   COMMON WORKFLOW PATTERNS:
   - "User provides code and executes it": Entry → Parameter → CodeRunner → Response
   - "AI responds to WhatsApp messages": WhatsApp Trigger → LLM → WhatsApp Send Message → Response
   - "AI responds to Twilio SMS": Twilio Trigger → LLM → Response
   - "Process data with AI": Entry → Parameter → LLM → Response
   - "LLM outputs JSON format": Entry → Parameter → LLM → ToJson → Response (MUST use ToJson when LLM outputs JSON!)
   - "AI generates JSON data": Entry → LLM → ToJson → (other nodes using parsed JSON) → Response
   - "Call external API": Entry → API → Response
   - "Store data in database": Entry → DatabaseConnection → StoreDataInTable → Response
   - "Fetch data from database": Entry → DatabaseConnection → FetchDataFromTable → Response
   - "Complex processing": Entry → Parameter → CodeRunner → LLM → Response
   - "Multi-turn chat": Entry → Parameter → GlobalData → LLM → GlobalData → Response
   - "Process array items": Entry → (node with array output) → Iterator → (process each) → Iterator Finished → Response
   - "Send email notification": Entry → LLM → EmailSend → Response
   - "Workflow composition": Entry → WorkflowExecute → Response
   - "Agent delegation": Entry → AgentExecute → Response
   - "Conditional routing": Entry → Parameter → Switch → Switch "A" (out pin) → LLM → Response, Switch "B" (out pin) → API → Response, Switch "default" (out pin) → Response
     * Switch Node evaluates input value and activates EXACTLY ONE out pin
     * Only nodes connected to the active out pin are executed
     * Switch out pins (next_pins) connect to downstream trigger_pins (execution flow)
   - "Store workflow variable": Entry → KeyValueSet → (other nodes) → KeyValueGet → Response
   - "Gmail auto-reply": Gmail Trigger → Gmail Reply → Response
   - "Zapier integration": Entry → ZapierTrigger → Response
   - "Extract JSON field": Entry → ToJson → Text → Response
   - "Create chart": Entry → FetchDataFromTable → BarChart → Response

CRITICAL: WORKFLOW START NODES (MUTUALLY EXCLUSIVE - USE ONLY ONE):
   These node types are for STARTING workflows. Use ONLY ONE based on the prompt:
   
   - Entry Node: Simple workflow start (no external trigger)
     * Entry node has ONLY one "Next" pin (control flow only)
     * Entry node does NOT receive or pass any data
     * Use Entry node ONLY when: Simple manual workflow start, no external events, no webhooks
     * DO NOT use Entry if prompt mentions: WhatsApp, Twilio, webhook, trigger, external events
   
   - WhatsApp Trigger Node: WhatsApp message received trigger
     * Use when: Prompt mentions WhatsApp messages, WhatsApp webhook, WhatsApp bot
     * Receives WhatsApp message events via webhook
     * Outputs: from, to, message, message_id, timestamp
     * Has filters: only_text, filter_sender
     * DO NOT use Entry or other triggers if using WhatsApp Trigger
   
   - Twilio Trigger Node: Twilio SMS/MMS or voice call trigger
     * Use when: Prompt mentions Twilio calls, SMS, MMS, Twilio webhook
     * Handles both messages and calls
     * Outputs: type, from, to, timestamp, message/call data
     * Has filters: event_type, filter_sender, only_text, has_media, call_status
     * DO NOT use Entry or other triggers if using Twilio Trigger
   
   - Zapier Trigger Node: Zapier webhook trigger (NOT a start node - sends TO Zapier)
     * Note: This is NOT a workflow start node - it sends data TO Zapier webhooks
     * Use for: Integrating with Zapier automations, sending data to Zapier
     * This node requires a Start node (Entry/Trigger) before it
   
   RULE: Only ONE start node type per workflow. Choose Entry, WhatsApp Trigger, or Twilio Trigger based on prompt requirements.

4. CONFIGURATION (CRITICAL - MATCH USER REQUIREMENTS):
   - Fill in configuration fields based on EXACT user requirements from the prompt
   - If user says "change the instruction to 'X'" or "change instruction to 'X'", set Instructions field to exactly 'X'
   - If user says "change the message to 'Y'" or "change message to 'Y'", set Message field to exactly 'Y'
   - If user says "change configuration" or "change fields value", extract the field names and values and apply them exactly
   - When user requests field changes, parse their request to identify:
     * Which node (by label or nodeType)
     * Which field (Instructions, Message, Code, URL, etc.)
     * What value to set (use their exact text)
   - Examples of field change requests:
     * "change the instruction to 'give helpful answer' in llm node" → Find LLM node, set Instructions = "give helpful answer"
     * "change message to 'Hello {{Data}}'" → Find node with Message field, set Message = "Hello {{Data}}"
     * "change configuration in LLM node" → Update LLM node's configuration with specified values
   - Use field IDs from the node type definition
   
   NODE-SPECIFIC CONFIGURATION GUIDELINES:
   
   - **LLM Node**:
     * Message/Interaction: Use exact prompt/message user wants to send to AI
     * Instructions: System instructions if user specifies AI behavior
     * CRITICAL: If LLM outputs JSON format → MUST add ToJson node after!
     * Pattern: LLM "Response" (JSON string) → ToJson "Text" → ToJson "JSON" (parsed object)
     * Use {{variable}} syntax for dynamic data injection
   
   - **CodeRunner Node**:
     * Language: Select based on requirement (Python, JavaScript, Node.js, C, Java)
     * Code: Use exact code user provides, or create appropriate code based on requirements
     * Dependencies: List external packages one per line (e.g., "requests", "pytz")
     * CRITICAL: Code MUST include print() statement for output!
   
   - **Parameter Node**:
     * Parameter Key: Use descriptive key (e.g., user_message, input_data)
     * Label: Human-readable name
     * Description: Explain parameter purpose
     * Debug Value: Sample value for testing
   
   - **API Node**:
     * URL: Use exact endpoint user mentions (supports {{variables}})
     * Method: Appropriate HTTP method (GET, POST, PUT, PATCH, DELETE)
     * Headers: MUST be valid JSON format: {{"Authorization": "Bearer {{token}}"}}
     * Body: Request payload (usually JSON, supports {{variables}})
     * CRITICAL: Headers must be JSON, not plain text!
   
   - **Database Connection Node**:
     * Database Type: e.g., MySQL
     * Host, Port, Database Name, Username, Password: Connection details
     * CA Certificate: Optional, for SSL connections
   
   - **Store Data in Table Node**:
     * Table Name: Exact table name from database
     * Table Schema: SQL DDL (CREATE TABLE statement)
     * Map columns using {{column_name}} syntax
   
   - **Fetch Data From Table Node**:
     * Table Name: Exact table name
     * Table Schema: SQL DDL
     * Take: Limit rows (e.g., 10)
     * Skip: Offset rows (e.g., 0)
   
   - **Text Node**:
     * Property Key: Field name (e.g., "status")
     * Value Path: JSON path (e.g., {{data.status}})
   
   - **Email Send Node**:
     * Resend API Key: API key for email service
     * From Email, From Name: Sender details
     * To Emails: Comma-separated (supports {{variables}})
     * Subject, Body: Email content (supports {{variables}}, HTML allowed)
   
   - **Send Email (Mailtrap) Node**:
     * SMTP Username, Password: Mailtrap credentials
     * From Email, From Name, To Emails, Subject, Body: Email details
     * Use for testing only, not production
   
   - **Bar Chart Node**:
     * Chart Title: Chart name (supports {{variables}})
     * X Axis: Categories (e.g., {{data.months}})
     * Y Axis: Values (e.g., {{data.sales}})
     * Other Instructions: Optional formatting
   
   - **Workflow Execute Node**:
     * Workflow ID: Select target workflow to execute
   
   - **Value_Get Node** (Key/Value Get):
     * Key: Name of key to retrieve (must exist in workflow context)
   
   - **Key/Value Set Node**:
     * Key: Name of key to set (supports {{variables}})
     * Value: Value to store (supports {{variables}})
     * Can also receive Key/Value from input pins
   
   - **Switch Node**:
     * configuration.conditions: [{{"label":"Simple","operator":"equals"|"contains"|"startswith"|"endswith"|"regex"|"greater_than"|"less_than","value":"simple"}}, ...]
     * "label" becomes the out pin name (e.g. "Simple" → next_pin "Simple"). Always include "Default" pin.
     * Map each condition to its handler: Switch.Simple → Simple Handler, Switch.Complex → Complex Handler. NEVER route condition cases through Default.
   
   - **WhatsApp Send Message Node**:
     * TO: WhatsApp number with country code (e.g., +1234567890)
     * Access Token: WhatsApp API access token
     * Phone Number ID: Business phone number ID
     * Message comes from input pin "Message"
   
   - **WhatsApp Trigger Node**:
     * Only Text Messages: Boolean (filter non-text messages)
     * Filter Sender: Optional phone number filter
     * Account ID: WhatsApp account identifier
     * Secret Key: Webhook secret key
   
   - **Twilio Trigger Node**:
     * Trigger On: message, call, or both
     * Filter Sender: Optional phone number filter
     * Only Text Messages: Boolean (for SMS filtering)
     * Only Messages With Media: Boolean (for MMS filtering)
     * Call Status Filter: Optional (ringing, in-progress, completed)
   
   - **Zapier Trigger Node**:
     * Webhook URL: Zapier webhook endpoint URL
     * HTTP Method: POST or GET
     * Query Parameters: JSON format (optional)
     * Payload: JSON format (optional if using input pin)
     * Custom Headers: JSON format (optional)
     * Request Timeout: Seconds (default 10)
   
   - **Agent Execute Node**:
     * Target Agent: Select agent to execute
     * Target Workflow: Optional, select specific workflow of target agent
     * Execution Mode: Wait for response (sync) or Continue immediately (async)
   
   - **Gmail Reply Node**:
     * Gmail Account: Credential ID for Gmail OAuth
     * Reply Message: Reply content (supports {{variables}})
     * Requires Email input pin with email object (from Gmail Trigger)
   
   - **Iterator Node**:
     * No configuration needed, operates on input array
   
   - **ToJson Node**:
     * No configuration needed, automatic conversion
   
   - **Global Data Node**:
     * No configuration needed, manages chat history automatically
   
   - **Entry Node**:
     * No configuration needed, workflow starter
   
   - **Response Node**:
     * No configuration needed, receives data via pins
   
   GENERAL RULES:
   - For text fields, provide meaningful values based on prompt
   - For select fields, use one of the available options
   - Use {{variable}} syntax for dynamic values
   - IMPORTANT: If user mentions specific values, use them exactly. Don't make up values.

5. CONNECTIONS:
   - Each connection needs: source_node, source_pin, destination_node, destination_pin
   - source_pin and destination_pin must be actual pin IDs (you'll generate UUIDs)
   - Connect nodes sequentially: node1 → node2 → node3, etc.

RETURN FORMAT (JSON):
{{
  "nodes": [
    {{
      "label": "Node Name",
      "nodeType": "ExactNodeTypeID",
      "configuration": {{"field_id": "value"}},
      "x": 100,
      "y": 100
    }}
  ],
  "connections": [
    {{
      "source_node_index": 0,
      "destination_node_index": 1,
      "source_pin_name": "PinName",
      "destination_pin_name": "PinName",
      "connection_type": "control" // or "data"
    }}
  ]
}}

CONNECTION RULES:
- connection_type: "control" = next_pins → trigger_pins (execution order)
- connection_type: "data" = output_pins → input_pins (data passing)
- Use node indices (0, 1, 2...) in connections, not node IDs
- Specify pin names (not IDs) in connections
- For control: source_pin_name must be from next_pins, dest_pin_name must be from trigger_pins
- For data: source_pin_name must be from output_pins, dest_pin_name must be from input_pins

CRITICAL: MINIMAL & INTENTIONAL CONNECTIONS (NO REDUNDANT OR CROSS-BRANCH WIRING)

RULE: Minimal & Intentional Connections
The workflow engine MUST create ONLY the minimum required connections needed for correct execution. 
Connections MUST be intentional, branch-isolated, and logically scoped. 
The system MUST NOT create unnecessary, duplicate, or cross-branch connections.

CORE PRINCIPLE:
A node should ONLY be connected to:
- The node that MUST execute immediately before it
- Within the SAME execution branch
Nothing more.

SWITCH BRANCH ISOLATION RULE:
1. Branch isolation is mandatory
   - Each Switch Node out pin represents an isolated execution branch.
   - Nodes connected to one out pin MUST NOT connect to nodes in another branch.
2. No cross-branch connections
   - Nodes in branch A MUST NOT connect to:
     - Nodes in branch B
     - Nodes in default branch
   - Each branch is a closed execution path.

LLM → RESPONSE CONNECTION RULE:
3. One-to-one execution flow
   - Each LLM Node MUST connect ONLY to its corresponding Response Node.
   - Do NOT connect one LLM Node to multiple Response Nodes.
   - Do NOT connect multiple LLM Nodes to the same Response Node unless explicitly required.
   Correct:
   - Type A LLM → Type A Response
   - Type B LLM → Type B Response
   - Default LLM → Default Response
   Incorrect:
   - Type A LLM → Type A Response, Type B Response, Default Response
   - Type B LLM → Type A Response

NO FAN-IN / FAN-OUT BY DEFAULT:
4. No automatic fan-out
   - A single node MUST NOT automatically connect to multiple downstream nodes.
5. No automatic fan-in
   - Multiple nodes MUST NOT automatically connect into a single node.
   Fan-in or fan-out is allowed ONLY if:
   - Explicitly requested by the user
   - Or explicitly required by node type (e.g., Join / Merge node)

CONNECTION CREATION RULE:
6. Create the fewest possible connections
   - For each execution path:
     - Entry → Switch
     - Switch.out_pin → LLM
     - LLM → Response
   - STOP once a terminal node (Response) is reached.
7. Terminal nodes stop propagation
   - Response Nodes are terminal.
   - No further connections should be created after them.

VISUAL & LOGICAL CLEANLINESS:
8. No duplicate connections
   - Do NOT create multiple edges between the same two nodes.
9. No speculative wiring
   - Do NOT connect nodes "just in case".
   - Only connect nodes that are guaranteed to run together.

VALIDATION ENFORCEMENT:
- Enforce branch isolation from Switch out pins.
- Enforce one-to-one LLM → Response mapping.
- Prevent cross-branch and redundant connections.
- Prefer minimal, linear execution paths.
- Fail validation if unnecessary connections are detected.

CRITICAL: CONNECT MATCHING PINS WITHIN SAME BRANCH ONLY!
- ALWAYS create control flow connections: Entry → Node1 → Node2 → ... → Response (within same branch)
- For data flow: Connect matching output pins to input pins ONLY within the same execution branch
  * Example: If source has "Response" and "Chat History" outputs, and dest has matching inputs in SAME branch, connect BOTH
  * Example: If source has "Response" output and dest has "Response" input in SAME branch, connect them
  * Example: If source has "Chat History" output and dest has "Chat History" input in SAME branch, connect them
  * DO NOT connect across different Switch branches

CRITICAL RULE: LLM JSON OUTPUT → MUST USE TOJSON NODE!
- If LLM node outputs JSON format (mentioned in prompt or LLM instructions), you MUST:
  1. Add ToJson node immediately after LLM node
  2. Connect: LLM "Response" → ToJson "Text" (JSON string input)
  3. Use ToJson "JSON" output (parsed JSON object) for subsequent nodes
  4. Example: LLM → ToJson → CodeRunner (uses parsed JSON)
  5. Example: LLM → ToJson → API (uses parsed JSON in request body)
  6. Example: LLM → ToJson → StoreDataInTable (uses parsed JSON for database)
- This ensures JSON string from LLM is properly parsed into JSON object for use in other nodes

IMPORTANT: DYNAMIC PIN CREATION
- INPUT PINS: If a node needs to receive data but doesn't have the required input pin, the system will automatically add it
  * Example: If "User Node.js Code" outputs "Data" and "Run Node.js Code" needs it, connect them even if "Run Node.js Code" doesn't have "Data" input pin
  * The system will automatically create the missing input pin when needed
- OUTPUT PINS: If a node needs to output data but doesn't have the required output pin, the system will automatically add it
  * Example: If a node needs to send data to another node but doesn't have an output pin, the system will create it
- You should still specify the connection - the system will handle pin creation

CODE TEMPLATE SYNTAX:
- When data is connected to nodes with code fields (CodeRunner, Python, etc.), use template syntax:
  * For simple data: "{{Data}}" or "{{Response}}"
  * For object properties: "{{Data.keyName}}" or "{{Response.message}}"
  * Example: If LLM outputs "{{"code": "console.log('hello')"}}", use "{{Response.code}}" in CodeRunner
- The system will automatically inject template syntax into code fields when data connections exist
- Use the input pin name in template syntax: "{{InputPinName}}" or "{{InputPinName.property}}"

WORKFLOW NAMING AND DESCRIPTION:
- Generate a clear, descriptive workflow_name based on what the workflow does
- Generate a comprehensive workflow_description that explains:
  * How the workflow works (step by step process)
  * What inputs it expects
  * What outputs it produces
  * What the workflow can be used for
  * Make it detailed and informative, not brief

- The system will auto-connect any missing connections, but you should specify all logical connections
- Generate meaningful labels and configurations based on user requirements
- NOTE: The system will automatically append the node type name in parentheses to labels
  * Example: If you specify label "User Code" for nodeType "Parameter", the final label will be "User Code (Parameter Node)"
  * This helps users understand which node type is being used
- Ensure all required fields in configuration are filled appropriately
- If user needs multiple instances of the same node type, create them as requested

FINAL CHECKLIST BEFORE GENERATING:
1. ✓ Did I understand what the user wants to achieve?
2. ✓ Did I select the correct start node? Only ONE start node!
   - Entry Node: Simple manual start
   - WhatsApp Trigger: WhatsApp message received
   - Twilio Trigger: Twilio SMS/call received
3. ✓ Did I use Parameter node if user provides input data?
4. ✓ Did I select the right processing nodes based on requirements?
   - LLM for AI/chat/text generation
   - CodeRunner for custom code execution
   - API for external HTTP requests
   - DatabaseConnection + StoreDataInTable for saving data
   - DatabaseConnection + FetchDataFromTable for reading data
   - Iterator for processing arrays
   - Switch for conditional routing
   - EmailSend/Mailtrap for sending emails
   - WhatsApp Send Message for WhatsApp messages
   - Gmail Reply for Gmail replies
   - WorkflowExecute for calling other workflows
   - AgentExecute for agent delegation
   - ZapierTrigger for Zapier integration
   - BarChart for chart generation
   - Text for extracting JSON values
   - ToJson for parsing JSON strings
   - KeyValueSet/Get for workflow variables
   - GlobalData for chat history (if multi-turn conversation)
5. ✓ If LLM outputs JSON format, did I add ToJson node after LLM? (CRITICAL!)
6. ✓ Did I connect LLM "Response" → ToJson "Text" if LLM outputs JSON?
7. ✓ For database operations, did I include DatabaseConnection node before StoreDataInTable/FetchDataFromTable?
8. ✓ For CodeRunner, did I include print() statement in code for output?
9. ✓ For API Node, are headers in valid JSON format?
10. ✓ For WhatsApp Send Message, did I configure TO, Access Token, and Phone Number ID?
11. ✓ For Trigger nodes (WhatsApp/Twilio), did I configure filters appropriately?
12. ✓ For Agent Execute, did I select Target Agent and Execution Mode?
13. ✓ For Gmail Reply, did I configure Gmail Account and Reply Message?
14. ✓ Did I order nodes logically (Start → Input → Process → Output)?
15. ✓ Did I configure each node with values that match user requirements exactly?
16. ✓ Did I create both control flow (next_pins → trigger_pins) AND data flow (output_pins → input_pins) connections?
17. ✓ Did I include a Response node at the end? (MANDATORY!)
18. ✓ For multi-turn conversations, did I include GlobalData node and connect Chat History?
19. ✓ For conditional logic, did I use Switch node appropriately?
20. ✓ Does the workflow make logical sense and match the user's prompt?

REMEMBER: Think step-by-step, select nodes based on their purpose, order them logically, and configure them accurately based on the user's exact requirements."""
    
    def generate_or_modify_workflow(self, prompt: str, conversation_history: List[Dict[str, str]] = None, existing_workflow: Dict[str, Any] = None) -> Dict[str, Any]:
        """
        Generate a new workflow or modify an existing one based on conversation history.
        
        Args:
            prompt: Current user prompt
            conversation_history: List of previous messages [{"role": "user/assistant", "content": "..."}]
            existing_workflow: Existing workflow data (nodes, connections) if modifying
        
        Returns:
            Generated or modified workflow
        """
        system_prompt = self._build_system_prompt()
        
        # Build conversation context
        conversation_context = ""
        if conversation_history and len(conversation_history) > 0:
            conversation_context = "\n\nCONVERSATION HISTORY:\n"
            for msg in conversation_history[-10:]:  # Last 10 messages for context
                role = msg.get("role", "user")
                content = msg.get("content", "")
                conversation_context += f"{role.upper()}: {content}\n"
        
        # Detect if user is explicitly requesting connection changes (do this before building context)
        prompt_lower = prompt.lower()
        explicit_connection_request = any(keyword in prompt_lower for keyword in [
            "connect", "connection", "link", "wire", "join",
            "remove connection", "delete connection", "disconnect", "unlink",
            "remove the connection", "delete the connection",
            "connect to", "link to", "wire to"
        ])
        
        # Detect if user is explicitly requesting configuration/field changes
        explicit_config_request = any(keyword in prompt_lower for keyword in [
            "change this node's field", "change this node field", "change node's field",
            "modify this node's field", "modify this node field", "modify node's field",
            "update this node's field", "update this node field", "update node's field",
            "change field", "modify field", "update field",
            "change this field", "modify this field", "update this field",
            "change the field", "modify the field", "update the field",
            "add this on this node's field", "add on this node's field", "add on field",
            "set field", "set this field", "set the field",
            "change configuration", "modify configuration", "update configuration",
            "change config", "modify config", "update config",
            "change this configuration", "modify this configuration", "update this configuration",
            "change the configuration", "modify the configuration", "update the configuration",
            "change this node's", "modify this node's", "update this node's",
            "change the", "modify the", "update the",
            "set", "change to", "update to", "modify to",
            # Specific field change patterns
            "change the instruction", "change instruction", "modify the instruction", "update the instruction",
            "change the message", "change message", "modify the message", "update the message",
            "change instructions to", "change message to", "change instruction to",
            "set instruction", "set message", "set instructions",
            "change fields value", "change field value", "modify fields value", "update fields value",
            "change configurations", "change fields", "modify fields", "update fields"
        ])
        
        # Build existing workflow context if modifying
        existing_context = ""
        if existing_workflow:
            nodes_summary = []
            for node in existing_workflow.get("nodes", []):
                node_type = node.get("nodeType", "")
                label = node.get("label", "")
                nodes_summary.append(f"- {label} ({node_type})")
            
            # Build connections summary
            connections_summary = []
            node_id_to_label = {node.get("id"): node.get("label", "") for node in existing_workflow.get("nodes", [])}
            for conn in existing_workflow.get("connections", []):
                source_label = node_id_to_label.get(conn.get("source_node"), "Unknown")
                dest_label = node_id_to_label.get(conn.get("destination_node"), "Unknown")
                connections_summary.append(f"- {source_label} → {dest_label}")
            
            existing_context = f"""
EXISTING WORKFLOW STRUCTURE:
Current workflow has {len(existing_workflow.get('nodes', []))} nodes:
{chr(10).join(nodes_summary)}

Current workflow has {len(existing_workflow.get('connections', []))} connections:
{chr(10).join(connections_summary) if connections_summary else '- No connections'}

IMPORTANT: You are MODIFYING an existing workflow. The user wants changes to this workflow.
- If user wants to add nodes, add them appropriately
- If user wants to remove nodes, remove them from the returned workflow
- If user wants to delete/remove connections, DO NOT include those connections in the returned workflow
- If user says "delete connection between X and Y", remove that specific connection
- If user says "delete connections" or "remove connections", remove all connections (or specific ones if mentioned)
- If user wants to modify node configurations, update them EXACTLY as requested
- If user says "change this node's field" or "add this on this node's field", follow their instructions EXACTLY
- If user says "change the instruction to 'X'" or "change the message to 'Y'", update that specific field with their exact value
- If user says "change configuration" or "change fields value", update the specified fields with their exact values
- If user explicitly requests configuration/field changes, use their specified values EXACTLY - DO NOT override them
- When user specifies a field value (e.g., "change instruction to 'give helpful answer'"), use their EXACT text
- If user wants to change connections, update them
- Preserve nodes and connections that the user doesn't mention changing
- Always return the COMPLETE workflow structure (all remaining nodes and connections), not just changes
- If user requests deletion, exclude deleted items from the returned workflow

CRITICAL CONNECTION RULES:
{"- USER HAS EXPLICITLY REQUESTED CONNECTION CHANGES - FOLLOW THEIR INSTRUCTIONS EXACTLY" if explicit_connection_request else ""}

CRITICAL CONFIGURATION RULES:
{"- USER HAS EXPLICITLY REQUESTED CONFIGURATION/FIELD CHANGES - FOLLOW THEIR INSTRUCTIONS EXACTLY" if explicit_config_request else ""}
{"- If user says 'change the instruction to X' or 'change the message to Y', use their EXACT specified values" if explicit_config_request else ""}
{"- If user says 'change this node's field's data' or 'add this on this node's field', use their EXACT specified values" if explicit_config_request else ""}
{"- Extract the exact field name and value from user's request and apply it directly to the node's configuration" if explicit_config_request else ""}
{"- Examples: 'change instruction to helpful' → Set Instructions='helpful', 'change message to hello' → Set Message='hello'" if explicit_config_request else ""}
{"- DO NOT override user-specified field values with auto-generated content" if explicit_config_request else ""}
- If user says "connect X to Y" or "link X to Y", create ONLY that specific connection
- If user says "remove connection between X and Y", remove ONLY that specific connection
- If user says "remove connections" or "delete connections", remove ONLY the connections they specify
- DO NOT add extra connections beyond what the user explicitly requests
- DO NOT auto-connect nodes unless the user asks you to create a complete workflow
- Preserve all existing connections that the user doesn't mention changing
- When user explicitly requests connection changes, return ONLY the connections they want (plus preserved existing ones)
"""
        
        try:
            # Enhanced user prompt
            user_prompt = f"""{existing_context}

{conversation_context}

CURRENT REQUEST: {prompt}

IMPORTANT: Before generating/modifying the workflow, think through these questions:
1. What is the user trying to achieve? (Main goal)
2. Is this modifying an existing workflow or creating a new one?
3. How should the workflow start? (Entry, Trigger, or Webhook?)
4. What input data is needed? (Should I use Parameter node?)
5. What processing is required? (LLM for AI, CodeRunner for code, API for external calls, etc.)
6. If using LLM: Will it output JSON format? → MUST add ToJson node after LLM to parse it!
7. What should be the output? (Always end with Response node)

CRITICAL RULE: If LLM outputs JSON format, you MUST:
- Add ToJson node immediately after LLM
- Connect: LLM "Response" → ToJson "Text"
- Use ToJson "JSON" output for subsequent nodes that need parsed JSON

Then generate/modify the workflow following this logical sequence:
- Start node (Entry/Trigger/Webhook) → Input node (if needed) → Processing nodes → Output node (Response)

CRITICAL REQUIREMENTS - WORKFLOW NAME AND DESCRIPTION:
IMPORTANT: Only include workflow_name and workflow_description if this is a NEW workflow (no existing workflow provided).
If an existing workflow is being modified, DO NOT include workflow_name or workflow_description in your response.
The backend will preserve existing workflow name and description - do not change them.

For NEW workflows only:
1. workflow_name: A clear, descriptive name (3-8 words) that accurately describes what the workflow does
   - Examples: "WhatsApp AI Response Workflow", "Node.js Code Execution Workflow", "Data Processing Pipeline"
   - DO NOT use generic names like "AI Generated Workflow" or "Workflow"
   - Base it on the actual functionality described in the prompt

2. workflow_description: A COMPLETE, detailed description (minimum 150 words) that includes:
   - Step-by-step explanation of how the workflow operates
   - What triggers or starts the workflow
   - What each node does in sequence
   - What inputs/data the workflow expects or receives
   - What outputs/results the workflow produces
   - What use cases or scenarios this workflow is designed for
   - Any important configuration or setup requirements
   - DO NOT truncate or use ellipsis (...)
   - Make it comprehensive enough for someone to understand the workflow without seeing it

Return format:
- For NEW workflows: Include workflow_name and workflow_description
- For EXISTING workflows: DO NOT include workflow_name or workflow_description (only nodes and connections)
{{
  "workflow_name": "Specific Descriptive Name Based on Functionality",  // ONLY for new workflows
  "workflow_description": "Complete detailed description...",  // ONLY for new workflows
  "nodes": [...],
  "connections": [...]
}}"""
            
            # Build messages array with conversation history
            messages = [{"role": "system", "content": system_prompt}]
            
            # Add conversation history (excluding last user message which is in prompt)
            if conversation_history and len(conversation_history) > 1:
                for msg in conversation_history[:-1]:  # All except last
                    messages.append({
                        "role": msg.get("role", "user"),
                        "content": msg.get("content", "")
                    })
            
            # Add current user prompt
            messages.append({"role": "user", "content": user_prompt})
            
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=0.7,
                response_format={"type": "json_object"}
            )
            
            generated_data = json.loads(response.choices[0].message.content)
            
            # Use the same explicit_connection_request and explicit_config_request detected earlier
            processed_workflow = self._process_generated_workflow(
                generated_data, 
                existing_workflow,
                respect_explicit_connections=explicit_connection_request,
                respect_explicit_config=explicit_config_request
            )
            
            # Only extract workflow name and description if this is a NEW workflow (no existing_workflow)
            # For existing workflows, preserve the existing name/description - don't change them
            if not existing_workflow:
                # This is a new workflow - extract name and description
                workflow_name = generated_data.get("workflow_name", "").strip()
                workflow_description = generated_data.get("workflow_description", "").strip()
                
                # If AI didn't generate proper name/description, create them from workflow structure
                if not workflow_name or workflow_name.lower() in ["ai generated workflow", "workflow", "generated workflow"]:
                    workflow_name = self._generate_workflow_name_from_structure(processed_workflow, prompt)
                
                if not workflow_description or len(workflow_description) < 100 or "..." in workflow_description:
                    workflow_description = self._generate_workflow_description_from_structure(processed_workflow, prompt)
                
                processed_workflow["workflow_name"] = workflow_name
                processed_workflow["workflow_description"] = workflow_description
            else:
                # Existing workflow - don't include name/description (will be preserved by backend)
                processed_workflow["workflow_name"] = None
                processed_workflow["workflow_description"] = None
            
            return processed_workflow
            
        except Exception as e:
            raise Exception(f"AI workflow generation/modification failed: {str(e)}")
    
    def generate_workflow(self, prompt: str) -> Dict[str, Any]:
        """Generate a workflow from a natural language prompt"""
        return self.generate_or_modify_workflow(prompt, conversation_history=None, existing_workflow=None)
    
    def _generate_workflow_name_from_structure(self, workflow: Dict[str, Any], prompt: str) -> str:
        """Generate a meaningful workflow name based on the workflow structure"""
        nodes = workflow.get("nodes", [])
        if not nodes:
            return "Custom Workflow"
        
        # Extract node types to understand workflow purpose
        node_types = []
        node_labels = []
        for node in nodes:
            node_type = node.get("nodeType", "")
            label = node.get("label", "")
            if node_type:
                node_types.append(node_type)
            if label:
                # Remove node type suffix if present
                clean_label = label.split("(")[0].strip()
                if clean_label:
                    node_labels.append(clean_label)
        
        # Build name based on node types and labels
        name_parts = []
        
        # Check for common patterns
        if "WhatsApp Trigger" in node_types or "WhatsApp Send Message" in node_types:
            name_parts.append("WhatsApp")
        if "LLM" in node_types:
            name_parts.append("AI")
        if "CodeRunner" in node_types or "Python" in node_types:
            name_parts.append("Code Execution")
        if "Entry" in node_types:
            name_parts.append("Automation")
        
        # Use meaningful labels if available
        if node_labels:
            # Take first meaningful label
            for label in node_labels:
                if label.lower() not in ["entry", "response", "node"]:
                    name_parts.append(label)
                    break
        
        # Fallback to prompt analysis
        if not name_parts:
            prompt_lower = prompt.lower()
            if "whatsapp" in prompt_lower:
                name_parts.append("WhatsApp")
            if "code" in prompt_lower or "nodejs" in prompt_lower or "python" in prompt_lower:
                name_parts.append("Code")
            if "ai" in prompt_lower or "llm" in prompt_lower or "chat" in prompt_lower:
                name_parts.append("AI")
            if "message" in prompt_lower or "send" in prompt_lower:
                name_parts.append("Messaging")
        
        if not name_parts:
            name_parts.append("Automated")
        
        name_parts.append("Workflow")
        
        return " ".join(name_parts)
    
    def _generate_workflow_description_from_structure(self, workflow: Dict[str, Any], prompt: str) -> str:
        """Generate a comprehensive workflow description based on the workflow structure"""
        nodes = workflow.get("nodes", [])
        connections = workflow.get("connections", [])
        
        if not nodes:
            return f"This workflow was generated from the following request: {prompt}"
        
        description_parts = []
        
        # Introduction
        description_parts.append("This workflow is an automated process designed to handle specific tasks based on the user's requirements.")
        description_parts.append("")
        
        # Workflow structure
        description_parts.append("WORKFLOW STRUCTURE:")
        description_parts.append("")
        
        # Describe each node in sequence
        for i, node in enumerate(nodes, 1):
            node_type = node.get("nodeType", "")
            label = node.get("label", "")
            node_name = label.split("(")[0].strip() if "(" in label else label
            
            node_type_name = self._get_node_type_display_name(node_type)
            
            description_parts.append(f"Step {i}: {node_name or node_type_name}")
            description_parts.append(f"  - Type: {node_type_name}")
            
            # Describe what this node does
            node_description = self._get_node_description(node_type, node.get("configuration", {}))
            if node_description:
                description_parts.append(f"  - Function: {node_description}")
            description_parts.append("")
        
        # Describe connections and data flow
        if connections:
            description_parts.append("DATA FLOW:")
            description_parts.append("The workflow processes data through the following sequence:")
            description_parts.append("")
            
            # Group connections by source node
            node_lookup = {node["id"]: node for node in nodes}
            for i in range(len(nodes) - 1):
                if i < len(nodes):
                    source_node = nodes[i]
                    dest_node = nodes[i + 1] if i + 1 < len(nodes) else None
                    
                    if dest_node:
                        source_label = source_node.get("label", "").split("(")[0].strip()
                        dest_label = dest_node.get("label", "").split("(")[0].strip()
                        description_parts.append(f"  • {source_label} → {dest_label}")
            description_parts.append("")
        
        # Inputs and outputs
        description_parts.append("INPUTS:")
        entry_nodes = [n for n in nodes if n.get("nodeType") in ["Entry", "WhatsApp Trigger", "Twilio Trigger"]]
        if entry_nodes:
            for node in entry_nodes:
                node_label = node.get("label", "").split("(")[0].strip()
                description_parts.append(f"  - The workflow starts with {node_label}, which receives external input or triggers")
        else:
            description_parts.append("  - The workflow begins with the first node, which receives input data")
        description_parts.append("")
        
        description_parts.append("OUTPUTS:")
        response_nodes = [n for n in nodes if n.get("nodeType") == "Response"]
        if response_nodes:
            description_parts.append("  - The workflow produces output through the Response node")
        else:
            last_node = nodes[-1] if nodes else None
            if last_node:
                last_label = last_node.get("label", "").split("(")[0].strip()
                description_parts.append(f"  - The workflow completes with {last_label}, which provides the final output")
        description_parts.append("")
        
        # Use cases
        description_parts.append("USE CASES:")
        description_parts.append(f"  - This workflow can be used to automate the process described in the original request: '{prompt}'")
        description_parts.append("  - It provides a structured, repeatable way to handle the specified tasks")
        description_parts.append("  - The workflow can be triggered manually or automatically based on configured triggers")
        description_parts.append("")
        
        # Configuration note
        description_parts.append("CONFIGURATION:")
        description_parts.append("  - Each node in the workflow can be configured with specific parameters")
        description_parts.append("  - Data flows between nodes through connected pins, allowing for seamless information transfer")
        description_parts.append("  - The workflow is ready to execute once all required configurations are set")
        
        return "\n".join(description_parts)
    
    def _get_node_type_display_name(self, node_type: str) -> str:
        """Get a human-readable name for a node type"""
        node_type_map = {
            "Entry": "Entry Node",
            "Response": "Response Node",
            "LLM": "LLM Node (AI Language Model)",
            "CodeRunner": "Code Runner Node",
            "Python": "Python Node",
            "Parameter": "Parameter Node",
            "WhatsApp Trigger": "WhatsApp Trigger Node",
            "WhatsApp Send Message": "WhatsApp Send Message Node",
            "Twilio Trigger": "Twilio Trigger Node",
            "API": "API Node",
            "DatabaseNode": "Database Node",
            "StoreDataInTable": "Store Data in Table Node"
        }
        return node_type_map.get(node_type, node_type)
    
    def _get_node_description(self, node_type: str, configuration: Dict[str, Any]) -> str:
        """Get a description of what a node does"""
        descriptions = {
            "Entry": "Entry point that initiates the workflow execution",
            "Response": "Final output node that returns the workflow results",
            "LLM": "Processes text using AI language model to generate intelligent responses",
            "CodeRunner": "Executes custom code (Node.js, Python, C, or Java) to perform specific operations",
            "Python": "Runs Python code for data processing or custom logic",
            "Parameter": "Provides input data or parameters to the workflow",
            "WhatsApp Trigger": "Receives incoming WhatsApp messages and triggers the workflow",
            "WhatsApp Send Message": "Sends messages through WhatsApp",
            "Twilio Trigger": "Receives incoming calls or messages via Twilio",
            "API": "Makes HTTP requests to external APIs",
            "DatabaseNode": "Interacts with databases to store or retrieve data",
            "StoreDataInTable": "Stores data in a database table"
        }
        return descriptions.get(node_type, "Performs specific operations as configured")
    
    def _process_generated_workflow(self, generated_data: Dict[str, Any], existing_workflow: Dict[str, Any] = None, respect_explicit_connections: bool = False, respect_explicit_config: bool = False) -> Dict[str, Any]:
        """Process AI-generated workflow and create proper node/connection structure"""
        nodes = []
        connections = []
        
        # Create node type lookup
        node_type_lookup = {nt["id"]: nt for nt in self.node_types}
        
        # Build lookup for existing nodes if modifying workflow
        existing_nodes_by_key = {}  # Key: "label|nodeType" -> node
        existing_nodes_by_id = {}  # Key: node_id -> node
        if existing_workflow:
            for existing_node in existing_workflow.get("nodes", []):
                # Create key from label and nodeType for matching
                label = existing_node.get("label", "").strip()
                node_type = existing_node.get("nodeType", "").strip()
                key = f"{label}|{node_type}"
                existing_nodes_by_key[key] = existing_node
                # Also create a map by ID for later reference
                node_id = existing_node.get("id")
                if node_id:
                    existing_nodes_by_id[node_id] = existing_node
        
        # Generate nodes with proper structure
        for i, node_data in enumerate(generated_data.get("nodes", [])):
            node_type_id = node_data.get("nodeType")
            node_type_def = node_type_lookup.get(node_type_id)
            
            if not node_type_def:
                raise Exception(f"Unknown node type: {node_type_id}")
            
            # Create node with label that includes node type name in parentheses
            base_label = node_data.get("label", node_type_def.get("name", "Node"))
            node_type_name = node_type_def.get("name", node_type_id)
            
            # Add node type name in parentheses if not already present
            if f"({node_type_name})" not in base_label and f"({node_type_id})" not in base_label:
                label = f"{base_label} ({node_type_name})"
            else:
                label = base_label
            
            # Try to match with existing node to preserve ID, position, and configuration
            existing_node = None
            match_key = f"{label}|{node_type_id}"
            if match_key in existing_nodes_by_key:
                existing_node = existing_nodes_by_key[match_key]
            else:
                # Try matching by base label without node type suffix
                base_label_clean = base_label.strip()
                for key, ex_node in existing_nodes_by_key.items():
                    if ex_node.get("nodeType") == node_type_id:
                        ex_label = ex_node.get("label", "").strip()
                        ex_base = ex_label.split("(")[0].strip()
                        if ex_base == base_label_clean:
                            existing_node = ex_node
                            break
            
            # Generate pins with UUIDs, preserving existing pin IDs when possible
            pins = {
                "trigger_pins": [],
                "input_pins": [],
                "output_pins": [],
                "next_pins": []
            }
            
            # Build pin lookup from existing node if available
            existing_pins_by_name = {}
            if existing_node:
                for pin_type in ["trigger_pins", "input_pins", "output_pins", "next_pins"]:
                    for pin in existing_node.get("pins", {}).get(pin_type, []):
                        pin_name = pin.get("name", "")
                        if pin_name:
                            existing_pins_by_name[f"{pin_type}|{pin_name}"] = pin.get("id")
            
            # RULE: Parameter nodes have exactly one output_pin ("Data"), no input/trigger/next pins.
            # Never use node type def pins for Parameter; do not create any other pins.
            if node_type_id == "Parameter":
                pin_id = existing_pins_by_name.get("output_pins|Data", str(uuid.uuid4()))
                pins = {
                    "trigger_pins": [],
                    "input_pins": [],
                    "output_pins": [{"id": pin_id, "name": "Data"}],
                    "next_pins": []
                }
            else:
                for pin_type in ["trigger_pins", "input_pins", "output_pins", "next_pins"]:
                    for pin_def in node_type_def.get("pins", {}).get(pin_type, []):
                        pin_name = pin_def.get("name", "")
                        pin_key = f"{pin_type}|{pin_name}"
                        # Preserve existing pin ID if available, otherwise generate new one
                        pin_id = existing_pins_by_name.get(pin_key, str(uuid.uuid4()))
                        pins[pin_type].append({
                            "id": pin_id,
                            "name": pin_name
                        })
            
            if existing_node:
                # Preserve existing node ID, position, and configuration
                existing_config = existing_node.get("configuration", {}).copy()
                existing_node_data = existing_node.get("nodeData", {})
                
                node = {
                    "id": existing_node.get("id", f"node_{uuid.uuid4().hex[:8]}"),
                    "type": "node",
                    "label": label,
                    "nodeType": node_type_id,
                    "pins": pins,  # Use pins with preserved IDs when possible
                    "configuration": existing_config,  # PRESERVE existing configuration
                    "nodeData": existing_node_data.copy() if existing_node_data else {  # PRESERVE existing position
                        "x": node_data.get("x", 100 + (i * 300)),
                        "y": node_data.get("y", 100)
                    }
                }
                # Handle configuration updates based on user intent
                new_config = node_data.get("configuration", {})
                if new_config:
                    if respect_explicit_config:
                        # User explicitly requested configuration changes - use their values exactly
                        # Update/override existing config with user's requested values
                        for key, value in new_config.items():
                            # Use user's exact value - don't modify it
                            node["configuration"][key] = value
                            print(f"Applied explicit configuration change: node '{label}' field '{key}' = '{value}' (as requested by user)")
                        print(f"Applied explicit configuration changes to node '{label}' as requested by user")
                    else:
                        # Only add new configuration keys that don't exist yet (preserve user's manual changes)
                        for key, value in new_config.items():
                            # Only add if key doesn't exist in existing config (preserve user changes)
                            if key not in node["configuration"]:
                                node["configuration"][key] = value
            else:
                # New node - create with default values
                node = {
                    "id": f"node_{uuid.uuid4().hex[:8]}",
                    "type": "node",
                    "label": label,
                    "nodeType": node_type_id,
                    "pins": pins,
                    "configuration": node_data.get("configuration", {}),
                    "nodeData": {
                        "x": node_data.get("x", 100 + (i * 300)),
                        "y": node_data.get("y", 100)
                    }
                }
            nodes.append(node)
        
        # Post-process: Ensure only ONE start node type is used (Entry, Trigger, or Webhook)
        # Check for multiple start nodes - only one should exist
        start_node_types = ["Entry", "WhatsApp Trigger", "Twilio Trigger", "Webhook"]
        start_nodes_found = []
        for i, node in enumerate(nodes):
            node_type = node.get("nodeType", "")
            if node_type in start_node_types:
                start_nodes_found.append((i, node_type, node))
        
        # If multiple start nodes found, keep only the first one and remove others
        if len(start_nodes_found) > 1:
            print(f"WARNING: Multiple start nodes detected: {[n[1] for n in start_nodes_found]}. Keeping first one: {start_nodes_found[0][1]}")
            # Remove duplicate start nodes (keep first, remove rest)
            indices_to_remove = sorted([n[0] for n in start_nodes_found[1:]], reverse=True)
            for idx in indices_to_remove:
                removed_node = nodes.pop(idx)
                print(f"Removed duplicate start node: {removed_node.get('label', removed_node.get('nodeType'))}")
        
        # Post-process: Check if Entry node is incorrectly used when Parameter node is needed
        # Entry node has no data output pins, so if connections expect data from first node, use Parameter
        if nodes and nodes[0].get("nodeType") == "Entry":
            first_node = nodes[0]
            
            # Check if any connections from first node expect data (not just control flow)
            has_data_connections = False
            for conn_data in generated_data.get("connections", []):
                source_idx = conn_data.get("source_node_index")
                if source_idx == 0:  # First node
                    conn_type = conn_data.get("connection_type", "data")
                    if conn_type == "data":
                        has_data_connections = True
                        break
            
            # If Entry node has data connections, it's wrong - Entry has no data pins
            # Replace with Parameter node
            if has_data_connections:
                print(f"WARNING: Entry node used but data connections detected. Replacing with Parameter node.")
                # Find Parameter node type definition
                parameter_node_def = node_type_lookup.get("Parameter")
                if parameter_node_def:
                    # Replace Entry with Parameter
                    parameter_pins = {
                        "trigger_pins": [],
                        "input_pins": [],
                        "output_pins": [{"id": str(uuid.uuid4()), "name": "Data"}],
                        "next_pins": []
                    }
                    
                    nodes[0]["nodeType"] = "Parameter"
                    nodes[0]["pins"] = parameter_pins
                    # Update label if it's generic
                    current_label = nodes[0].get("label", "")
                    if "Entry" in current_label or "entry" in current_label.lower():
                        new_label = current_label.replace("Entry", "Parameter").replace("entry", "Parameter")
                        if "Parameter" not in new_label:
                            new_label = f"{new_label.split('(')[0].strip()} (Parameter Node)"
                        nodes[0]["label"] = new_label
        
        # Ensure Switch Nodes have correct out pins based on workflow connections
        nodes = self._ensure_switch_node_out_pins(nodes, generated_data.get("connections", []))
        
        ai_connections = []
        connection_set = set()  # Track existing connections to avoid duplicates
        
        # Process AI-generated connections (validate and filter)
        for conn_data in generated_data.get("connections", []):
            source_idx = conn_data.get("source_node_index")
            dest_idx = conn_data.get("destination_node_index")
            source_pin_name = conn_data.get("source_pin_name")
            dest_pin_name = conn_data.get("destination_pin_name")
            conn_type = conn_data.get("connection_type", "data")
            
            if source_idx is None or dest_idx is None or source_idx >= len(nodes) or dest_idx >= len(nodes):
                continue
            
            source_node = nodes[source_idx]
            dest_node = nodes[dest_idx]
            
            source_pin = None
            dest_pin = None
            
            if conn_type == "control":
                # Control flow: next_pins → trigger_pins ONLY
                # Find source pin in next_pins
                for pin in source_node["pins"]["next_pins"]:
                    if pin["name"] == source_pin_name:
                        source_pin = pin
                        break
                
                # Find destination pin in trigger_pins ONLY (never next_pins)
                for pin in dest_node["pins"]["trigger_pins"]:
                    if pin["name"] == dest_pin_name:
                        dest_pin = pin
                        break
            else:
                # Data flow: output_pins → input_pins ONLY
                # Find source pin in output_pins
                for pin in source_node["pins"]["output_pins"]:
                    if pin["name"] == source_pin_name:
                        source_pin = pin
                        break
                
                # Find destination pin in input_pins
                for pin in dest_node["pins"]["input_pins"]:
                    if pin["name"] == dest_pin_name:
                        dest_pin = pin
                        break
            
            # Only add if both pins found and types match
            if source_pin and dest_pin:
                conn = {
                    "source_node": source_node["id"],
                    "source_pin": source_pin["id"],
                    "destination_node": dest_node["id"],
                    "destination_pin": dest_pin["id"]
                }
                conn_key = (conn["source_node"], conn["source_pin"], 
                           conn["destination_node"], conn["destination_pin"])
                if conn_key not in connection_set:
                    connection_set.add(conn_key)
                    ai_connections.append(conn)
        
        # Auto-repair: Add missing connections following the rules
        # Step 1: Add missing CONTROL FLOW connections (next_pins → trigger_pins)
        # This ensures execution order: Entry → Node1 → Node2 → ... → Response
        
        # First, ensure Entry node connects to the first processing node
        entry_node = next((n for n in nodes if n.get("nodeType") == "Entry"), None)
        if entry_node:
            entry_node_id = entry_node["id"]
            entry_next_pins = entry_node["pins"].get("next_pins", [])
            
            if entry_next_pins:
                # Find the first node after Entry that has trigger pins
                entry_index = next((i for i, n in enumerate(nodes) if n["id"] == entry_node_id), -1)
                if entry_index >= 0:
                    # Look for next node with trigger pins (could be at entry_index + 1 or later)
                    for i in range(entry_index + 1, len(nodes)):
                        next_node = nodes[i]
                        next_trigger_pins = next_node["pins"].get("trigger_pins", [])
                        
                        if next_trigger_pins:
                            # Create connection: Entry "Next" → Next Node "Start"
                            control_conn = {
                                "source_node": entry_node_id,
                                "source_pin": entry_next_pins[0]["id"],
                                "destination_node": next_node["id"],
                                "destination_pin": next_trigger_pins[0]["id"]
                            }
                            
                            conn_key = (control_conn["source_node"], control_conn["source_pin"],
                                       control_conn["destination_node"], control_conn["destination_pin"])
                            if conn_key not in connection_set:
                                connection_set.add(conn_key)
                                ai_connections.append(control_conn)
                                print(f"Auto-created Entry node connection: Entry -> {next_node.get('label', next_node.get('nodeType'))}")
                            break  # Only connect Entry to first available node
        
        # Step 1b: Add missing CONTROL FLOW connections for all other nodes
        for i in range(len(nodes) - 1):
            source_node = nodes[i]
            dest_node = nodes[i + 1]
            
            # Skip if source is Entry (already handled above)
            if source_node.get("nodeType") == "Entry":
                continue
            
            # Control Flow: next_pins → trigger_pins
            source_next_pins = source_node["pins"]["next_pins"]
            dest_trigger_pins = dest_node["pins"]["trigger_pins"]
            
            # Only connect if source has next_pins AND dest has trigger_pins
            if source_next_pins and dest_trigger_pins:
                control_conn = {
                    "source_node": source_node["id"],
                    "source_pin": source_next_pins[0]["id"],  # Use first "Next" pin
                    "destination_node": dest_node["id"],
                    "destination_pin": dest_trigger_pins[0]["id"]  # Use first "Start" pin
                }
                
                conn_key = (control_conn["source_node"], control_conn["source_pin"],
                           control_conn["destination_node"], control_conn["destination_pin"])
                if conn_key not in connection_set:
                    connection_set.add(conn_key)
                    ai_connections.append(control_conn)
        
        # Step 2: Add missing DATA FLOW connections (output_pins → input_pins)
        # This ensures data passes between nodes that need it
        # IMPORTANT: Connect ALL matching pins, not just the first one!
        # NOTE: Skip Global Data nodes - they manage history automatically and don't have input pins
        for i in range(len(nodes) - 1):
            source_node = nodes[i]
            dest_node = nodes[i + 1]
            
            # Skip if destination is Global Data node (no input pins, manages history automatically)
            if dest_node.get("nodeType") == "GlobalData":
                continue
            
            source_output_pins = source_node["pins"]["output_pins"]
            dest_input_pins = dest_node["pins"]["input_pins"]
            
            # Only connect if both have appropriate pins
            if source_output_pins and dest_input_pins:
                # Connect ALL matching pins (e.g., "Response" → "Response", "Chat History" → "Chat History")
                # This ensures complete data flow like in the second image
                matched_pins = []  # Track which input pins have been matched
                
                for output_pin in source_output_pins:
                    output_name_lower = output_pin["name"].lower()
                    best_match = None
                    best_match_score = 0
                    
                    # Find best matching input pin for this output pin
                    for input_pin in dest_input_pins:
                        # Skip if already matched
                        if input_pin["id"] in matched_pins:
                            continue
                        
                        input_name_lower = input_pin["name"].lower()
                        match_score = 0
                        
                        # Exact match (highest priority)
                        if output_name_lower == input_name_lower:
                            match_score = 100
                            best_match = input_pin
                            best_match_score = match_score
                            break  # Perfect match, use it immediately
                        
                        # Common patterns with scoring
                        if output_name_lower == "response" and input_name_lower in ["response", "data", "input"]:
                            match_score = 80 if input_name_lower == "response" else 60
                        elif output_name_lower == "chat history" and input_name_lower == "chat history":
                            match_score = 100
                        elif output_name_lower == "connection" and input_name_lower == "connection":
                            match_score = 100
                        elif output_name_lower == "metadata" and input_name_lower == "metadata":
                            match_score = 100
                        elif output_name_lower == "data" and input_name_lower in ["data", "input"]:
                            match_score = 80 if input_name_lower == "data" else 60
                        elif output_name_lower in ["output", "text", "json"] and input_name_lower in ["data", "input"]:
                            match_score = 50
                        
                        # Update best match if this is better
                        if match_score > best_match_score:
                            best_match = input_pin
                            best_match_score = match_score
                    
                    # Connect if we found a match
                    if best_match and best_match_score > 0:
                        data_conn = {
                            "source_node": source_node["id"],
                            "source_pin": output_pin["id"],
                            "destination_node": dest_node["id"],
                            "destination_pin": best_match["id"]
                        }
                        
                        conn_key = (data_conn["source_node"], data_conn["source_pin"],
                                   data_conn["destination_node"], data_conn["destination_pin"])
                        if conn_key not in connection_set:
                            connection_set.add(conn_key)
                            ai_connections.append(data_conn)
                            matched_pins.append(best_match["id"])  # Mark as used
        
        # Validate all connections before returning
        connections = self._validate_connections(ai_connections, nodes)
        
        # Apply minimal connection rules: remove redundant and cross-branch connections
        is_valid, error_msg, connections = self._validate_minimal_connections(nodes, connections)
        if not is_valid:
            print(f"WARNING: Minimal connection validation failed: {error_msg}")
        
        # Remove redundant connections (duplicates, fan-out/fan-in, terminal node violations)
        connections = self._remove_redundant_connections(nodes, connections)
        
        # Only auto-generate connections if user hasn't explicitly requested specific connections
        if not respect_explicit_connections:
            # Auto-generate missing connections if needed (fallback)
            if len(connections) < len(nodes) - 1:
                print(f"WARNING: Only {len(connections)} connections found for {len(nodes)} nodes! Enhancing with auto-generated connections...")
                auto_connections = self._auto_generate_connections(nodes, connections)
                
                # Merge auto-generated connections with existing ones (avoid duplicates)
                # STRICT RULE: Track ALL pins to enforce one-connection-per-pin
                existing_conn_keys = {
                    (c.get("source_node"), c.get("source_pin"), c.get("destination_node"), c.get("destination_pin"))
                    for c in connections
                }
                connected_pins = set()  # {pin_id}
                for conn in connections:
                    if conn.get("source_pin"):
                        connected_pins.add(conn.get("source_pin"))
                    if conn.get("destination_pin"):
                        connected_pins.add(conn.get("destination_pin"))
                
                for auto_conn in auto_connections:
                    conn_key = (
                        auto_conn.get("source_node"),
                        auto_conn.get("source_pin"),
                        auto_conn.get("destination_node"),
                        auto_conn.get("destination_pin")
                    )
                    source_pin_id = auto_conn.get("source_pin")
                    dest_pin_id = auto_conn.get("destination_pin")
                    
                    # STRICT RULE: Check if connection already exists
                    if conn_key in existing_conn_keys:
                        continue
                    
                    # STRICT RULE: Check if source pin already has a connection
                    if source_pin_id in connected_pins:
                        print(f"Skipping auto-generated connection: Source pin already has a connection. Each pin can have ONLY ONE connection.")
                        continue
                    
                    # STRICT RULE: Check if destination pin already has a connection
                    if dest_pin_id in connected_pins:
                        print(f"Skipping auto-generated connection: Destination pin already has a connection. Each pin can have ONLY ONE connection.")
                        continue
                    
                    connections.append(auto_conn)
                    existing_conn_keys.add(conn_key)
                    connected_pins.add(source_pin_id)
                    connected_pins.add(dest_pin_id)
                
                print(f"Enhanced workflow with {len(connections)} total connections ({len(auto_connections)} auto-generated)")
            
            # Final validation and repair (only if not respecting explicit connections)
            connections = self._validate_and_repair_connections(nodes, connections)
            
            # Apply minimal connection rules after repair
            is_valid, error_msg, connections = self._validate_minimal_connections(nodes, connections)
            if not is_valid:
                print(f"WARNING: Minimal connection validation failed: {error_msg}")
            
            # Remove redundant connections
            connections = self._remove_redundant_connections(nodes, connections)
        else:
            # User explicitly requested connection changes - only validate, don't auto-repair
            print("User explicitly requested connection changes - respecting their instructions exactly")
            connections = self._validate_connections(connections, nodes)
            
            # Still apply minimal connection rules (but don't auto-repair)
            is_valid, error_msg, connections = self._validate_minimal_connections(nodes, connections)
            if not is_valid:
                print(f"WARNING: Minimal connection validation failed: {error_msg}")
        
        # Only auto-add pins if user hasn't explicitly requested connection changes
        if not respect_explicit_connections:
            # Step 0: Ensure Switch Nodes have correct out pins based on actual connections
            nodes = self._ensure_switch_node_out_pins_from_connections(nodes, connections)
            
            # Step 0.5: Connect Switch Node out pins to downstream nodes based on workflow structure
            nodes, connections = self._connect_switch_node_out_pins(nodes, connections)
            
            # Step 1: Ensure all Parameter Nodes have required input pins on downstream nodes
            # This handles cases where 3, 4, 5, 6, or more Parameter Nodes need to connect
            nodes, connections = self._ensure_parameter_node_input_pins(nodes, connections)
            
            # Step 1.5: Ensure Parameter nodes connect to LLM nodes when LLM needs user input
            # CRITICAL: LLM nodes often need user input data, so connect Parameter nodes automatically
            nodes, connections = self._ensure_parameter_to_llm_connections(nodes, connections)
            
            # Step 2: Add missing input pins dynamically when needed for data connections
            nodes, connections = self._add_missing_input_pins(nodes, connections)
            
            # Step 3: Add missing output pins dynamically when needed for data connections
            nodes, connections = self._add_missing_output_pins(nodes, connections)
        else:
            # User explicitly requested connections - only add pins that are absolutely necessary for existing connections
            # Don't auto-add pins for new connections
            print("Skipping auto-pin addition - respecting explicit user connection requests")
        
        # RULE: Each Parameter node connects to exactly ONE node. Prune any extra connections.
        connections = self._enforce_parameter_single_connection(nodes, connections)
        
        # Inject template syntax into code fields for data connections
        # RULE: If user explicitly requested configuration changes, don't override their values
        nodes = self._inject_template_syntax(nodes, connections, respect_explicit_config=respect_explicit_config)
        
        # CRITICAL: Normalize Parameter nodes - exactly one output_pin, no input/trigger/next pins. Never create pins on Parameter.
        nodes = self._normalize_parameter_node_pins(nodes)
        
        # Validate Parameter Nodes have output pins
        is_valid, error_message = self._validate_parameter_nodes(nodes)
        if not is_valid:
            raise Exception(f"Parameter Node validation failed: {error_message}")
        
        # CRITICAL: Clean up Switch nodes to ensure they have EXACTLY ONE input pin
        nodes = self._cleanup_switch_node_input_pins(nodes)
        
        # Validate Switch Nodes have correct pin structure
        is_valid, error_message = self._validate_switch_nodes(nodes)
        if not is_valid:
            raise Exception(f"Switch Node validation failed: {error_message}")
        
        # Validate input pin connection constraints
        is_valid, error_message = self._validate_input_pin_connections(connections, nodes)
        if not is_valid:
            raise Exception(f"Input pin connection validation failed: {error_message}")
        
        # CRITICAL: Ensure Response nodes have required connections BEFORE validation
        # Build branch mapping for Response node connection enforcement
        node_to_branch = {}
        node_lookup = {node["id"]: node for node in nodes}
        
        # Build branch membership from connections
        # CRITICAL: Track all nodes in Switch branches, including Response nodes
        for conn in connections:
            source_node_id = conn.get("source_node")
            source_pin_id = conn.get("source_pin")
            dest_node_id = conn.get("destination_node")
            
            source_node = node_lookup.get(source_node_id)
            if source_node and source_node.get("nodeType") == "Switch":
                # Find which out pin this is
                for out_pin in source_node.get("pins", {}).get("next_pins", []):
                    if out_pin.get("id") == source_pin_id:
                        switch_id = source_node_id
                        out_pin_id = source_pin_id
                        node_to_branch[dest_node_id] = (switch_id, out_pin_id)
                        # Recursively mark downstream nodes (including Response nodes)
                        self._mark_branch_nodes(dest_node_id, switch_id, out_pin_id, 
                                               node_to_branch, connections, node_lookup)
                        break
            
            # Also check if destination is a Response node and trace back to find its branch
            dest_node = node_lookup.get(dest_node_id)
            if dest_node and dest_node.get("nodeType") == "Response":
                # If Response node is not in a branch yet, try to find its branch by tracing back
                if dest_node_id not in node_to_branch:
                    # Check if source node is in a branch
                    source_branch = node_to_branch.get(source_node_id)
                    if source_branch:
                        # Response node is in the same branch as its source
                        node_to_branch[dest_node_id] = source_branch
                        print(f"Traced Response node '{dest_node.get('label', 'Unknown')}' to branch from source node")
        
        # Additional pass: Ensure all Response nodes are in branches if they should be
        # Look for Response nodes that come after Switch-connected nodes
        for response_node in [n for n in nodes if n.get("nodeType") == "Response"]:
            response_node_id = response_node.get("id")
            if response_node_id not in node_to_branch:
                # Check connections to this Response node
                for conn in connections:
                    if conn.get("destination_node") == response_node_id:
                        source_node_id = conn.get("source_node")
                        source_branch = node_to_branch.get(source_node_id)
                        if source_branch:
                            # Response node is in the same branch as its source
                            node_to_branch[response_node_id] = source_branch
                            print(f"Traced Response node '{response_node.get('label', 'Unknown')}' to branch from connection")
                            break
        
        # Track connected pins
        connected_pins = set()
        connection_set = {
            (c.get("source_node"), c.get("source_pin"), c.get("destination_node"), c.get("destination_pin"))
            for c in connections
        }
        for conn in connections:
            if conn.get("source_pin"):
                connected_pins.add(conn.get("source_pin"))
            if conn.get("destination_pin"):
                connected_pins.add(conn.get("destination_pin"))
        
        # Ensure Response nodes have required connections
        connections = self._ensure_response_node_connections(nodes, connections, node_to_branch, 
                                                             connected_pins, connection_set)
        
        # Validate Response nodes have required connections
        is_valid, error_message = self._validate_response_node_connections(connections, nodes)
        if not is_valid:
            raise Exception(f"Response node connection validation failed: {error_message}")
        
        return {
            "nodes": nodes,
            "connections": connections
        }
    
    def _ensure_switch_node_out_pins(self, nodes: List[Dict], ai_connections: List[Dict]) -> List[Dict]:
        """
        Ensure Switch Nodes have the correct out pins (next_pins) based on workflow connections.
        
        Rules:
        - Switch Node MUST have EXACTLY ONE input pin
        - Switch Node MUST have MULTIPLE out pins (next_pins) - one per condition + default
        - Out pin names MUST match condition values/labels
        - Switch Node MUST always have a "default" out pin
        - Out pins are dynamically created based on connections (additive only)
        
        Args:
            nodes: List of workflow nodes
            ai_connections: List of AI-generated connections (with source_node_index, destination_node_index, source_pin_name)
        
        Returns:
            Updated list of nodes with Switch Node out pins created
        """
        node_lookup = {node["id"]: node for i, node in enumerate(nodes)}
        
        # Find all Switch Nodes
        switch_nodes = [node for node in nodes if node.get("nodeType") == "Switch"]
        
        if not switch_nodes:
            return nodes  # No Switch Nodes, nothing to do
        
        # Analyze connections to determine what out pins are needed for each Switch Node
        for switch_node in switch_nodes:
            switch_node_id = switch_node.get("id")
            switch_node_index = next((i for i, n in enumerate(nodes) if n.get("id") == switch_node_id), -1)
            
            if switch_node_index < 0:
                continue
            
            # Get existing out pins (next_pins)
            existing_out_pins = switch_node.get("pins", {}).get("next_pins", [])
            existing_out_pin_names = {pin.get("name", "").lower() for pin in existing_out_pins}
            
            # Track which out pins are referenced in connections
            needed_out_pin_names = set()
            
            # CRITICAL: Create next_pins from configuration.conditions (condition labels) + Default
            # Each condition["label"] becomes an out pin; "Default" is always required for unmatched cases
            configuration = switch_node.get("configuration") or {}
            for c in configuration.get("conditions") or []:
                label = c.get("label") or c.get("value")
                if label and isinstance(label, str):
                    needed_out_pin_names.add(str(label).strip())
            
            # Analyze AI-generated connections to find out pins needed
            for conn_data in ai_connections:
                source_idx = conn_data.get("source_node_index")
                source_pin_name = conn_data.get("source_pin_name", "")
                conn_type = conn_data.get("connection_type", "data")
                
                # Only process control flow connections from Switch Node
                if source_idx == switch_node_index and conn_type == "control":
                    if source_pin_name:
                        needed_out_pin_names.add(source_pin_name.lower())
            
            # Also check existing connections if any
            # (This handles cases where connections are already established)
            
            # Ensure "default" out pin exists
            if "default" not in existing_out_pin_names:
                needed_out_pin_names.add("default")
            
            # Create missing out pins
            pins = switch_node.get("pins", {})
            if "next_pins" not in pins:
                pins["next_pins"] = []
            
            # Create out pins that are needed but don't exist
            # RULE: Out pin names use _ for spacing (e.g. "Option A" -> "Option_A")
            for out_pin_name in needed_out_pin_names:
                name_normalized = out_pin_name.lower().replace(" ", "_")
                pin_exists = any(
                    pin.get("name", "").lower().replace(" ", "_") == name_normalized
                    for pin in pins["next_pins"]
                )
                if not pin_exists:
                    # Use _ for spacing; "default" has no space so unchanged
                    display_name = out_pin_name.replace(" ", "_")
                    new_out_pin = {
                        "id": str(uuid.uuid4()),
                        "name": display_name
                    }
                    pins["next_pins"].append(new_out_pin)
                    print(f"Created out pin '{new_out_pin['name']}' for Switch Node '{switch_node.get('label', 'Unknown')}'")
            
            # Ensure exactly ONE input pin exists
            if "input_pins" not in pins:
                pins["input_pins"] = []
            
            input_pins = pins["input_pins"]
            if len(input_pins) == 0:
                # Create default input pin if none exists
                default_input_pin = {
                    "id": str(uuid.uuid4()),
                    "name": "Input"
                }
                pins["input_pins"].append(default_input_pin)
                print(f"Created default input pin 'Input' for Switch Node '{switch_node.get('label', 'Unknown')}'")
            elif len(input_pins) > 1:
                # Switch Node should have exactly ONE input pin - keep only the first one
                print(f"WARNING: Switch Node '{switch_node.get('label', 'Unknown')}' has {len(input_pins)} input pins. Keeping only the first one.")
                pins["input_pins"] = [input_pins[0]]
            
            # Update node pins
            switch_node["pins"] = pins
        
        return nodes
    
    def _ensure_switch_node_out_pins_from_connections(self, nodes: List[Dict], connections: List[Dict]) -> List[Dict]:
        """
        Ensure Switch Nodes have the correct out pins (next_pins) based on actual connections.
        This is called after connections are processed to ensure all referenced out pins exist.
        
        Args:
            nodes: List of workflow nodes
            connections: List of actual connections (with source_node, source_pin, etc.)
        
        Returns:
            Updated list of nodes with Switch Node out pins created
        """
        node_lookup = {node["id"]: node for node in nodes}
        
        # Find all Switch Nodes
        switch_nodes = [node for node in nodes if node.get("nodeType") == "Switch"]
        
        if not switch_nodes:
            return nodes  # No Switch Nodes, nothing to do
        
        # Analyze connections to determine what out pins are needed for each Switch Node
        for switch_node in switch_nodes:
            switch_node_id = switch_node.get("id")
            
            # Get existing out pins (next_pins)
            pins = switch_node.get("pins", {})
            if "next_pins" not in pins:
                pins["next_pins"] = []
            
            existing_out_pins = pins["next_pins"]
            existing_out_pin_ids = {pin.get("id") for pin in existing_out_pins}
            existing_out_pin_names = {pin.get("name", "").lower() for pin in existing_out_pins}
            
            # CRITICAL: Create next_pins from configuration.conditions (condition labels) + Default
            # Each condition["label"] becomes an out pin; "Default" is MANDATORY for unmatched cases
            # RULE: Out pin names use _ for spacing (e.g. "Option A" -> "Option_A")
            configuration = switch_node.get("configuration") or {}
            for c in configuration.get("conditions") or []:
                label = (c.get("label") or c.get("value")) if isinstance(c, dict) else None
                if label and isinstance(label, str):
                    raw = str(label).strip()
                    norm = raw.lower().replace(" ", "_")
                    if norm and norm not in existing_out_pin_names:
                        display_name = raw.replace(" ", "_")
                        new_out_pin = {"id": str(uuid.uuid4()), "name": display_name}
                        pins["next_pins"].append(new_out_pin)
                        existing_out_pin_ids.add(new_out_pin["id"])
                        existing_out_pin_names.add(norm)
                        print(f"Created out pin '{new_out_pin['name']}' from conditions for Switch Node '{switch_node.get('label', 'Unknown')}'")
            
            # Re-read after possibly adding from conditions
            existing_out_pin_names = {p.get("name", "").lower() for p in pins["next_pins"]}
            
            # Track which out pins are referenced in connections but don't exist
            missing_out_pin_ids = set()
            
            # Analyze actual connections to find out pins that are being used
            for conn in connections:
                source_node_id = conn.get("source_node")
                source_pin_id = conn.get("source_pin")
                
                if source_node_id == switch_node_id and source_pin_id:
                    # Check if this pin is a next_pin (out pin) - if not found, it's missing
                    if source_pin_id not in existing_out_pin_ids:
                        # Check if it's supposed to be a next_pin by checking if destination has trigger_pins
                        dest_node_id = conn.get("destination_node")
                        dest_node = node_lookup.get(dest_node_id)
                        if dest_node:
                            dest_pin_id = conn.get("destination_pin")
                            # Check if destination pin is a trigger_pin (control flow)
                            for trigger_pin in dest_node.get("pins", {}).get("trigger_pins", []):
                                if trigger_pin.get("id") == dest_pin_id:
                                    # This is a control flow connection, so source should be a next_pin
                                    missing_out_pin_ids.add(source_pin_id)
                                    break
            
            # Create missing out pins (infer name from context or use generic name)
            for missing_pin_id in missing_out_pin_ids:
                # Try to infer pin name from connection context or use a generic name
                # For now, create a generic out pin - the name can be updated later
                new_out_pin = {
                    "id": missing_pin_id,  # Use the referenced ID
                    "name": f"out_{len(existing_out_pins) + 1}"  # Generic name
                }
                pins["next_pins"].append(new_out_pin)
                print(f"Created missing out pin '{new_out_pin['name']}' (ID: {missing_pin_id}) for Switch Node '{switch_node.get('label', 'Unknown')}'")
            
            # Ensure "default" out pin exists
            if "default" not in existing_out_pin_names:
                default_out_pin = {
                    "id": str(uuid.uuid4()),
                    "name": "default"
                }
                pins["next_pins"].append(default_out_pin)
                print(f"Created required 'default' out pin for Switch Node '{switch_node.get('label', 'Unknown')}'")
            
            # Ensure exactly ONE input pin exists
            if "input_pins" not in pins:
                pins["input_pins"] = []
            
            input_pins = pins["input_pins"]
            if len(input_pins) == 0:
                # Create default input pin if none exists
                default_input_pin = {
                    "id": str(uuid.uuid4()),
                    "name": "Input"
                }
                pins["input_pins"].append(default_input_pin)
                print(f"Created default input pin 'Input' for Switch Node '{switch_node.get('label', 'Unknown')}'")
            elif len(input_pins) > 1:
                # Switch Node should have exactly ONE input pin - keep only the first one
                print(f"WARNING: Switch Node '{switch_node.get('label', 'Unknown')}' has {len(input_pins)} input pins. Keeping only the first one.")
                pins["input_pins"] = [input_pins[0]]
            
            # Update node pins
            switch_node["pins"] = pins
        
        return nodes
    
    def _connect_switch_node_out_pins(self, nodes: List[Dict], connections: List[Dict]) -> tuple[List[Dict], List[Dict]]:
        """
        SWITCH NODE – OUT PIN CONNECTION RULES (CORRECT & EXPECTED BEHAVIOR)
        
        BASIC PURPOSE:
        The Switch node routes execution based on a single input value.
        It compares the input value against defined cases and activates ONLY the matching out pin.
        
        INPUT PIN RULE:
        - Switch node ALWAYS has exactly ONE input pin.
        - This input pin receives the value that determines routing (usually from a Parameter node).
        
        OUT PIN (CASE) RULES:
        - Out pins represent CASES (not generic outputs).
        - Out pins are dynamically created based on required cases.
        - Each out pin must correspond to ONE specific case value.
        - Example: If cases are A, B, C → create out pins: Option A, Option B, Option C, Default
        
        EXECUTION BEHAVIOR:
        - When Switch receives an input value:
          - If input == "A" → ONLY Option A out pin is triggered
          - If input == "B" → ONLY Option B out pin is triggered
          - If input == "C" → ONLY Option C out pin is triggered
          - If input matches none → Default out pin is triggered (if exists)
        - Out pins are mutually exclusive - NO other out pins should execute.
        
        CONNECTION RULE (MOST IMPORTANT):
        - EACH out pin must connect ONLY to the nodes that should run for that case.
        - NEVER merge multiple cases into one execution path.
        - NEVER connect multiple out pins to the same downstream logic unless intentionally shared.
        
        Correct:
        Option A → Action A → Response A
        Option B → Action B → Response B
        Option C → Action C → Response C
        
        Incorrect:
        Option A, B → Same Action Node (unless explicitly required)
        
        STRICT RULES:
        - Switch Node out pins (next_pins) connect to downstream node Start pins (trigger_pins)
        - Each Switch out pin can connect to ONLY ONE node (max 1 connection per pin)
        - Out pin names should match node labels/conditions (e.g., "Type a" → "Respond to TypeA" LLM Node)
        - Default out pin connects to nodes that don't match specific conditions (but NOT to other case handlers)
        - After connecting Switch out pin → LLM Start, ensure LLM outputs → Response inputs
        - Response nodes are terminal - no connections after them
        
        Args:
            nodes: List of workflow nodes
            connections: List of existing connections
        
        Returns:
            Updated nodes and connections with Switch Node out pin connections
        """
        node_lookup = {node["id"]: node for node in nodes}
        updated_connections = list(connections)
        connection_set = {
            (c.get("source_node"), c.get("source_pin"), c.get("destination_node"), c.get("destination_pin"))
            for c in connections
        }
        
        # STRICT RULE: Track ALL pins to enforce one-connection-per-pin
        connected_pins = set()  # {pin_id}
        for conn in connections:
            if conn.get("source_pin"):
                connected_pins.add(conn.get("source_pin"))
            if conn.get("destination_pin"):
                connected_pins.add(conn.get("destination_pin"))
        
        # Find all Switch Nodes
        switch_nodes = [node for node in nodes if node.get("nodeType") == "Switch"]
        
        if not switch_nodes:
            return nodes, updated_connections
        
        # Build node order/index for finding downstream nodes
        node_indices = {node["id"]: i for i, node in enumerate(nodes)}
        
        for switch_node in switch_nodes:
            switch_node_id = switch_node.get("id")
            switch_node_index = node_indices.get(switch_node_id, -1)
            
            if switch_node_index < 0:
                continue
            
            # Get Switch Node out pins (next_pins)
            switch_out_pins = switch_node.get("pins", {}).get("next_pins", [])
            if not switch_out_pins:
                continue
            
            # Create mapping of out pin names (normalized)
            out_pin_map = {}
            default_out_pin = None
            for out_pin in switch_out_pins:
                pin_name = out_pin.get("name", "").lower()
                out_pin_map[pin_name] = out_pin
                if pin_name == "default":
                    default_out_pin = out_pin
            
            # Track which out pins already have connections
            connected_out_pins = set()  # {out_pin_id}
            for conn in updated_connections:
                if conn.get("source_node") == switch_node_id:
                    source_pin_id = conn.get("source_pin")
                    if any(pin.get("id") == source_pin_id for pin in switch_out_pins):
                        connected_out_pins.add(source_pin_id)
            
            # Find downstream nodes (nodes that come after Switch Node in workflow)
            downstream_nodes = []
            for i in range(switch_node_index + 1, len(nodes)):
                downstream_node = nodes[i]
                downstream_node_type = downstream_node.get("nodeType", "")
                
                # Skip Entry, Parameter, and other Switch Nodes as direct targets
                if downstream_node_type in ["Entry", "Parameter", "Switch"]:
                    continue
                
                # Skip Response nodes - they are terminal and should be connected from LLM nodes, not Switch
                if downstream_node_type == "Response":
                    continue
                
                # Skip if already connected to Switch Node via control flow
                already_connected = any(
                    c.get("source_node") == switch_node_id and
                    c.get("destination_node") == downstream_node.get("id") and
                    # Check if source pin is a next_pin (out pin)
                    any(pin.get("id") == c.get("source_pin") for pin in switch_out_pins)
                    for c in updated_connections
                )
                
                if not already_connected:
                    downstream_nodes.append(downstream_node)
            
            # Connect downstream nodes to appropriate out pins
            for downstream_node in downstream_nodes:
                downstream_node_id = downstream_node.get("id")
                downstream_label = downstream_node.get("label", "")
                downstream_label_lower = downstream_label.lower()
                downstream_node_type = downstream_node.get("nodeType", "")
                
                # Find matching out pin based on node label
                matched_out_pin = None
                best_match_score = 0
                
                # Try to match node label with out pin names
                # Examples: "Respond to TypeA" → "Type a" or "type a" out pin
                #           "Respond to TypeB" → "Type b" or "type b" out pin
                for out_pin_name, out_pin in out_pin_map.items():
                    # STRICT RULE: Skip default out pin for LLM nodes that match specific cases
                    # Default should only connect to nodes that don't match any case
                    if out_pin_name == "default":
                        # Only use default if no other case matches
                        # Don't connect default to nodes that match other cases (e.g., "Respond to TypeA")
                        continue  # Skip default for now, will handle separately
                    
                    # STRICT RULE: Check if this out pin already has a connection
                    if out_pin.get("id") in connected_out_pins:
                        continue  # This out pin already has a connection, skip
                    
                    out_pin_name_lower = out_pin_name.lower()
                    
                    # Normalize both for comparison (remove spaces, underscores, hyphens, parentheses)
                    normalized_pin_name = out_pin_name_lower.replace(" ", "").replace("_", "").replace("-", "").replace("(", "").replace(")", "")
                    normalized_label = downstream_label_lower.replace(" ", "").replace("_", "").replace("-", "").replace("(", "").replace(")", "")
                    
                    # Calculate match score
                    match_score = 0
                    
                    # Exact match (highest priority)
                    if normalized_pin_name == normalized_label:
                        match_score = 100
                    # Out pin name is contained in label (e.g., "typea" in "respondtotypea")
                    elif normalized_pin_name in normalized_label:
                        match_score = 80
                    # Label starts with out pin name
                    elif normalized_label.startswith(normalized_pin_name):
                        match_score = 70
                    # Out pin name words appear in label (e.g., "type" and "a" in "respond to type a")
                    else:
                        pin_words = normalized_pin_name.split()
                        label_words = normalized_label.split()
                        matching_words = sum(1 for word in pin_words if word in label_words)
                        if matching_words > 0:
                            match_score = 50 + (matching_words * 10)
                    
                    if match_score > best_match_score:
                        best_match_score = match_score
                        matched_out_pin = out_pin
                
                # If no good match found (score < 50), use default out pin
                # But only if default doesn't already have a connection
                if best_match_score < 50:
                    if default_out_pin and default_out_pin.get("id") not in connected_out_pins:
                        matched_out_pin = default_out_pin
                
                if not matched_out_pin:
                    continue  # No out pin available or already connected
                
                matched_out_pin_id = matched_out_pin.get("id")
                
                # STRICT RULE: Check if out pin already has a connection
                if matched_out_pin_id in connected_pins:
                    print(f"Skipping: Switch Node '{switch_node.get('label', 'Unknown')}' out pin '{matched_out_pin.get('name')}' already has a connection. Each pin can have ONLY ONE connection.")
                    continue
                
                # Get downstream node Start pin (trigger_pin)
                downstream_trigger_pins = downstream_node.get("pins", {}).get("trigger_pins", [])
                if not downstream_trigger_pins:
                    continue
                
                start_pin = downstream_trigger_pins[0]  # Use first Start pin
                start_pin_id = start_pin.get("id")
                
                # STRICT RULE: Check if destination Start pin already has a connection
                if start_pin_id in connected_pins:
                    print(f"Skipping: Destination Start pin on '{downstream_node.get('label', 'Unknown')}' already has a connection. Each pin can have ONLY ONE connection.")
                    continue
                
                # Create connection: Switch out pin → downstream node Start pin
                new_conn = {
                    "source_node": switch_node_id,
                    "source_pin": matched_out_pin_id,
                    "destination_node": downstream_node_id,
                    "destination_pin": start_pin_id
                }
                
                conn_key = (
                    new_conn["source_node"],
                    new_conn["source_pin"],
                    new_conn["destination_node"],
                    new_conn["destination_pin"]
                )
                
                # Only add if connection doesn't already exist
                if conn_key not in connection_set:
                    updated_connections.append(new_conn)
                    connection_set.add(conn_key)
                    connected_pins.add(matched_out_pin_id)
                    connected_pins.add(start_pin_id)
                    connected_out_pins.add(matched_out_pin_id)
                    print(f"Connected Switch Node '{switch_node.get('label', 'Unknown')}' out pin '{matched_out_pin.get('name')}' → '{downstream_node.get('label', 'Unknown')}' Start pin")
        
        return nodes, updated_connections
    
    def _ensure_parameter_node_input_pins(self, nodes: List[Dict], connections: List[Dict]) -> tuple[List[Dict], List[Dict]]:
        """
        PARAMETER NODE CONNECTION RULES (CORRECT & EXPECTED BEHAVIOR)
        
        BASIC PURPOSE:
        Parameter nodes collect values from the user. Each Parameter connects to exactly ONE node.
        
        CONNECTION RULES:
        1. Each Parameter node MUST connect to exactly ONE node. If already connected, do NOT connect to another.
        2. Parameter → first valid downstream node (e.g. Switch for decision, or LLM/CodeRunner for data)
        3. Parameter → Switch (for decision/routing), OR Parameter → Action (for data) — one target only
        
        NO FAN-OUT RULE:
        - A Parameter node must NOT connect to multiple nodes (no Parameter → A and Parameter → B)
        - Each new user value requires a new Parameter node AND a new input pin
        
        PIN CREATION:
        If 3 Parameter Nodes need to connect → create 3 input pins on the target node(s), one Param per target
        If 4 Parameter Nodes need to connect → create 4 input pins
        
        This function:
        1. Identifies Parameter Nodes and their target downstream node (the FIRST valid one only)
        2. Counts how many Parameter Nodes connect to each downstream node
        3. Ensures that many input pins are created/available
        4. Connects each Parameter Node to its own unique input pin on that one node
        5. Adds input pins to node configurations
        6. NEVER connects to Chat History pins
        7. Enforces: each Parameter node connects to exactly ONE node (no fan-out)
        """
        node_lookup = {node["id"]: node for node in nodes}
        updated_connections = list(connections)
        
        # Group Parameter Nodes by their target downstream node
        # {dest_node_id: [list of parameter nodes that should connect to it]}
        parameter_nodes_by_target = {}
        
        # Find all Parameter Nodes
        parameter_nodes = [node for node in nodes if node.get("nodeType") == "Parameter"]
        
        # Track existing connections to see which Parameter Nodes are already connected
        connected_parameter_nodes = set()
        connected_input_pins = set()  # {(dest_node_id, input_pin_id)}
        
        for conn in connections:
            source_node_id = conn.get("source_node")
            dest_node_id = conn.get("destination_node")
            dest_pin_id = conn.get("destination_pin")
            
            if source_node_id and dest_node_id:
                source_node = node_lookup.get(source_node_id)
                if source_node and source_node.get("nodeType") == "Parameter":
                    connected_parameter_nodes.add(source_node_id)
                
                if dest_pin_id:
                    dest_node = node_lookup.get(dest_node_id)
                    if dest_node:
                        for pin in dest_node.get("pins", {}).get("input_pins", []):
                            if pin.get("id") == dest_pin_id:
                                # RULE: Never track Chat History pins as connected
                                pin_name = pin.get("name", "").lower()
                                if "chat history" not in pin_name:
                                    connected_input_pins.add((dest_node_id, dest_pin_id))
                                break
        
        # For each Parameter Node, find its target downstream node
        # Parameter Nodes typically connect to the next node in sequence
        for i, param_node in enumerate(parameter_nodes):
            param_node_id = param_node.get("id")
            
            # Skip if already connected
            if param_node_id in connected_parameter_nodes:
                continue
            
            # RULE: Each Parameter Node connects to exactly ONE node (the first valid downstream node)
            # If already connected, skip. Do NOT connect to multiple nodes.
            param_index = next((idx for idx, n in enumerate(nodes) if n.get("id") == param_node_id), -1)
            
            if param_index >= 0:
                # Find the FIRST non-Parameter, non-GlobalData node after this Parameter Node
                for j in range(param_index + 1, len(nodes)):
                    next_node = nodes[j]
                    next_node_type = next_node.get("nodeType", "")
                    
                    # Skip Parameter Nodes and Global Data nodes as destinations
                    if next_node_type in ["Parameter", "GlobalData"]:
                        continue
                    
                    # This is the one target node - Parameter connects to it only
                    dest_node_id = next_node.get("id")
                    if dest_node_id not in parameter_nodes_by_target:
                        parameter_nodes_by_target[dest_node_id] = []
                    parameter_nodes_by_target[dest_node_id].append(param_node)
                    break  # RULE: Parameter connects to exactly one node; do not add to more targets
        
        # For each target node, ensure enough input pins exist for all Parameter Nodes
        for dest_node_id, param_nodes_list in parameter_nodes_by_target.items():
            dest_node = node_lookup.get(dest_node_id)
            if not dest_node:
                continue
            
            # Skip ToJson nodes - they have fixed input pins
            if dest_node.get("nodeType") == "ToJson":
                continue
            
            # Count how many Parameter Nodes need to connect
            num_parameter_nodes = len(param_nodes_list)
            
            # Get existing input pins on this node
            existing_input_pins = dest_node.get("pins", {}).get("input_pins", [])
            
            # RULE: Exclude Chat History pins from available pins
            available_input_pins = []
            for pin in existing_input_pins:
                pin_name = pin.get("name", "").lower()
                pin_id = pin.get("id")
                # Never use Chat History pins for Parameter Node connections
                if "chat history" not in pin_name and (dest_node_id, pin_id) not in connected_input_pins:
                    available_input_pins.append(pin)
            
            # Calculate how many new input pins we need to create
            pins_needed = num_parameter_nodes
            pins_available = len(available_input_pins)
            pins_to_create = max(0, pins_needed - pins_available)
            
            if pins_to_create > 0:
                print(f"Creating {pins_to_create} new input pin(s) on node '{dest_node.get('label', dest_node.get('nodeType'))}' for {num_parameter_nodes} Parameter Node(s)")
            
            # Create the required number of input pins
            created_pins = []
            for i in range(pins_to_create):
                # Determine input pin name from Parameter Node
                if i < len(param_nodes_list):
                    param_node = param_nodes_list[i]
                    param_config = param_node.get("configuration", {})
                    param_key = param_config.get("Parameter Key") or param_config.get("Key") or param_config.get("parameter_key")
                    
                    if param_key:
                        input_pin_name = param_key
                    else:
                        # Fallback: use node label
                        source_label = param_node.get("label", "")
                        if "Parameter" in source_label:
                            input_pin_name = source_label.split("(")[0].strip().lower().replace(" ", "_")
                        else:
                            input_pin_name = source_label.lower().replace(" ", "_") if source_label else f"param_{i+1}"
                else:
                    # Fallback name if we run out of Parameter Nodes
                    input_pin_name = f"param_{len(existing_input_pins) + i + 1}"
                
                # Check if pin with this name already exists
                pin_exists = any(
                    pin.get("name", "").lower() == input_pin_name.lower()
                    for pin in existing_input_pins
                )
                
                if not pin_exists:
                    new_input_pin = {
                        "id": str(uuid.uuid4()),
                        "name": input_pin_name,
                        "editable": True
                    }
                    dest_node["pins"]["input_pins"].append(new_input_pin)
                    created_pins.append(new_input_pin)
                    
                    # Add input pin to node configuration
                    if "configuration" not in dest_node:
                        dest_node["configuration"] = {}
                    
                    # Add input pin to configuration (for nodes that support it)
                    config_key = f"InputPin_{input_pin_name}" or input_pin_name
                    if config_key not in dest_node["configuration"]:
                        dest_node["configuration"][config_key] = ""
                    
                    print(f"Created input pin '{input_pin_name}' on node '{dest_node.get('label', dest_node.get('nodeType'))}' and added to configuration")
            
            # Now connect each Parameter Node to its own unique input pin
            all_available_pins = available_input_pins + created_pins
            
            for i, param_node in enumerate(param_nodes_list):
                param_node_id = param_node.get("id")
                
                # Skip if already connected
                if param_node_id in connected_parameter_nodes:
                    continue
                
                # Get output pin from Parameter Node
                param_output_pins = param_node.get("pins", {}).get("output_pins", [])
                if not param_output_pins:
                    continue
                
                param_output_pin = param_output_pins[0]  # Use first output pin
                
                # Find or assign an input pin for this Parameter Node
                input_pin = None
                
                # Try to find a pin that matches the parameter key
                param_config = param_node.get("configuration", {})
                param_key = param_config.get("Parameter Key") or param_config.get("Key") or param_config.get("parameter_key")
                
                if param_key:
                    # Look for matching pin by name (excluding Chat History)
                    for pin in all_available_pins:
                        pin_name = pin.get("name", "").lower()
                        if pin_name == param_key.lower() and "chat history" not in pin_name:
                            pin_id = pin.get("id")
                            if (dest_node_id, pin_id) not in connected_input_pins:
                                input_pin = pin
                                break
                
                # If no match found, use next available pin (excluding Chat History)
                if not input_pin and i < len(all_available_pins):
                    for pin in all_available_pins:
                        pin_name = pin.get("name", "").lower()
                        pin_id = pin.get("id")
                        # RULE: Never connect to Chat History pins
                        if "chat history" not in pin_name and (dest_node_id, pin_id) not in connected_input_pins:
                            input_pin = pin
                            break
                
                # Create connection if we found an input pin
                if input_pin:
                    new_conn = {
                        "source_node": param_node_id,
                        "source_pin": param_output_pin.get("id"),
                        "destination_node": dest_node_id,
                        "destination_pin": input_pin.get("id")
                    }
                    
                    # Check if connection already exists
                    conn_exists = any(
                        c.get("source_node") == param_node_id and
                        c.get("destination_node") == dest_node_id and
                        c.get("destination_pin") == input_pin.get("id")
                        for c in updated_connections
                    )
                    
                    if not conn_exists:
                        updated_connections.append(new_conn)
                        connected_input_pins.add((dest_node_id, input_pin.get("id")))
                        connected_parameter_nodes.add(param_node_id)
                        print(f"Connected Parameter Node '{param_node.get('label', 'Unknown')}' to input pin '{input_pin.get('name')}' on node '{dest_node.get('label', dest_node.get('nodeType'))}'")
        
        return nodes, updated_connections
    
    def _ensure_parameter_to_llm_connections(self, nodes: List[Dict], connections: List[Dict]) -> tuple[List[Dict], List[Dict]]:
        """
        Ensure Parameter nodes connect to LLM nodes when LLM needs user input data.
        
        RULE: If an LLM node needs user input (detected by checking configuration or lack of data connections),
        automatically connect available Parameter nodes to the LLM node.
        
        This ensures:
        - LLM nodes receive user input when needed
        - Parameter nodes are properly utilized
        - Appropriate input pins are created on LLM nodes
        """
        node_lookup = {node["id"]: node for node in nodes}
        updated_connections = list(connections)
        connection_set = {
            (c.get("source_node"), c.get("source_pin"), c.get("destination_node"), c.get("destination_pin"))
            for c in connections
        }
        
        # Track connected pins
        connected_pins = set()
        for conn in connections:
            if conn.get("source_pin"):
                connected_pins.add(conn.get("source_pin"))
            if conn.get("destination_pin"):
                connected_pins.add(conn.get("destination_pin"))
        
        # Track which Parameter nodes are already connected to which LLM nodes
        parameter_to_llm_connections = {}  # {(param_node_id, llm_node_id): True}
        for conn in connections:
            source_node = node_lookup.get(conn.get("source_node"))
            dest_node = node_lookup.get(conn.get("destination_node"))
            if source_node and dest_node:
                if source_node.get("nodeType") == "Parameter" and dest_node.get("nodeType") == "LLM":
                    param_id = source_node.get("id")
                    llm_id = dest_node.get("id")
                    parameter_to_llm_connections[(param_id, llm_id)] = True
        
        # Find all LLM nodes
        llm_nodes = [node for node in nodes if node.get("nodeType") == "LLM"]
        
        # Find all Parameter nodes
        parameter_nodes = [node for node in nodes if node.get("nodeType") == "Parameter"]
        
        if not llm_nodes or not parameter_nodes:
            return nodes, updated_connections
        
        # For each LLM node, check if it needs user input
        for llm_node in llm_nodes:
            llm_node_id = llm_node.get("id")
            llm_config = llm_node.get("configuration", {})
            llm_message = llm_config.get("Message", "") or llm_config.get("message", "")
            llm_instructions = llm_config.get("Instructions", "") or llm_config.get("instructions", "")
            
            # Check if LLM already has data connections (from Parameter or other nodes)
            has_data_connection = any(
                node_lookup.get(conn.get("source_node"), {}).get("nodeType") in ["Parameter", "API", "CodeRunner", "Text"]
                for conn in connections
                if conn.get("destination_node") == llm_node_id
            )
            
            # Check if LLM configuration references user input or needs data
            needs_user_input = False
            
            # Strategy 1: Check if LLM message/instructions reference user input
            config_text = (llm_message + " " + llm_instructions).lower()
            user_input_keywords = [
                "user", "input", "message", "request", "query", "question",
                "{{data}}", "{{input}}", "{{message}}", "{{user}}", "{{request}}"
            ]
            
            if any(keyword in config_text for keyword in user_input_keywords):
                needs_user_input = True
            
            # Strategy 2: If LLM has no data connections and has a Message/Instructions field, it likely needs input
            if not has_data_connection and (llm_message or llm_instructions):
                needs_user_input = True
            
            # Strategy 3: If LLM is in a Switch branch and doesn't have data connections, it likely needs input
            # (Switch branches often need user input for processing)
            if not has_data_connection:
                # Check if LLM is after a Switch node (likely needs user input)
                llm_index = next((i for i, n in enumerate(nodes) if n.get("id") == llm_node_id), -1)
                if llm_index > 0:
                    # Check if there's a Switch node before this LLM
                    for i in range(llm_index - 1, -1, -1):
                        if nodes[i].get("nodeType") == "Switch":
                            needs_user_input = True
                            break
            
            if not needs_user_input:
                continue
            
            # Find available Parameter nodes: must have ZERO outgoing connections to ANY node
            # RULE: Each Parameter connects to exactly ONE node. If already connected, do NOT connect to another.
            available_parameters = []
            for param_node in parameter_nodes:
                param_node_id = param_node.get("id")
                
                # Skip if already connected to this LLM
                if (param_node_id, llm_node_id) in parameter_to_llm_connections:
                    continue
                
                # RULE: Skip if this Parameter is already connected to ANY node (one-connection rule)
                param_has_any_connection = any(
                    c.get("source_node") == param_node_id for c in updated_connections
                )
                if param_has_any_connection:
                    continue
                
                # Check if Parameter node output pin is available
                param_output_pins = param_node.get("pins", {}).get("output_pins", [])
                if not param_output_pins:
                    continue
                
                available_parameters.append(param_node)
            
            # Connect available Parameter nodes to LLM node
            for param_node in available_parameters:
                param_node_id = param_node.get("id")
                param_output_pins = param_node.get("pins", {}).get("output_pins", [])
                
                if not param_output_pins:
                    continue
                
                param_output_pin_id = param_output_pins[0].get("id")
                
                # Get Parameter key/name for input pin name
                param_config = param_node.get("configuration", {})
                param_key = param_config.get("Parameter Key") or param_config.get("Key") or param_config.get("parameter_key")
                
                if param_key:
                    input_pin_name = param_key
                else:
                    # Use Parameter node label
                    param_label = param_node.get("label", "")
                    if "Parameter" in param_label:
                        input_pin_name = param_label.split("(")[0].strip().lower().replace(" ", "_")
                    else:
                        input_pin_name = param_label.lower().replace(" ", "_") if param_label else "data"
                
                # Check if LLM node already has this input pin
                llm_input_pins = llm_node.get("pins", {}).get("input_pins", [])
                existing_input_pin = None
                
                for pin in llm_input_pins:
                    pin_name = pin.get("name", "").lower()
                    # Skip Chat History pins
                    if "chat history" in pin_name:
                        continue
                    # Check if pin name matches or pin is not connected
                    if pin_name == input_pin_name.lower():
                        existing_input_pin = pin
                        break
                
                # Use existing pin or create new one
                # RULE: Each input pin can have ONLY ONE connection
                # RULE: Each Parameter connects to exactly ONE node (enforced by available_parameters check above)
                input_pin_id = None
                
                if existing_input_pin:
                    existing_pin_id = existing_input_pin.get("id")
                    # Check if this pin is already connected
                    if existing_pin_id in connected_pins:
                        # Pin already connected, create new pin with unique name
                        input_pin_name = f"{input_pin_name}_{len(llm_input_pins)}"
                        existing_input_pin = None
                    else:
                        input_pin_id = existing_pin_id
                
                if not input_pin_id:
                    # Create new input pin on LLM node
                    new_input_pin = {
                        "id": str(uuid.uuid4()),
                        "name": input_pin_name,
                        "editable": True
                    }
                    llm_node["pins"]["input_pins"].append(new_input_pin)
                    input_pin_id = new_input_pin.get("id")
                    print(f"Auto-created input pin '{input_pin_name}' on LLM node '{llm_node.get('label', 'Unknown')}' for Parameter node '{param_node.get('label', 'Unknown')}'")
                
                # Check if this specific connection already exists
                conn_key = (param_node_id, param_output_pin_id, llm_node_id, input_pin_id)
                if conn_key in connection_set:
                    continue  # Connection already exists
                
                # RULE: Parameter connects to exactly one node; available_parameters already excludes connected ones
                
                # Create connection: Parameter → LLM
                new_conn = {
                    "source_node": param_node_id,
                    "source_pin": param_output_pin_id,
                    "destination_node": llm_node_id,
                    "destination_pin": input_pin_id
                }
                
                conn_key = (
                    new_conn["source_node"],
                    new_conn["source_pin"],
                    new_conn["destination_node"],
                    new_conn["destination_pin"]
                )
                
                if conn_key not in connection_set:
                    updated_connections.append(new_conn)
                    connection_set.add(conn_key)
                    # RULE: Each Parameter connects to exactly one node; this connection uses that one slot
                    connected_pins.add(input_pin_id)
                    connected_pins.add(param_output_pin_id)  # Param output now connected; no further connections
                    parameter_to_llm_connections[(param_node_id, llm_node_id)] = True
                    print(f"Auto-connected Parameter node '{param_node.get('label', 'Unknown')}' → LLM node '{llm_node.get('label', 'Unknown')}' (LLM needs user input)")
        
        return nodes, updated_connections
    
    def _enforce_parameter_single_connection(self, nodes: List[Dict], connections: List[Dict]) -> List[Dict]:
        """
        Enforce that each Parameter node has at most ONE outgoing connection.
        If a Parameter has multiple connections, keep the first by node order and remove the rest.
        """
        node_lookup = {n["id"]: n for n in nodes}
        node_order = {n["id"]: i for i, n in enumerate(nodes)}
        # Group connections by source: only data connections from Parameter nodes
        param_out_conns = {}  # param_id -> [conn, ...]
        other_conns = []
        for c in connections:
            src = c.get("source_node")
            if not src or node_lookup.get(src, {}).get("nodeType") != "Parameter":
                other_conns.append(c)
                continue
            # Only count data connections (output_pin -> input_pin)
            if not c.get("source_pin") or not c.get("destination_pin"):
                other_conns.append(c)
                continue
            if src not in param_out_conns:
                param_out_conns[src] = []
            param_out_conns[src].append(c)
        # For each Parameter with 2+ connections, keep one (first by dest node order)
        kept_param_conns = []
        for param_id, conns in param_out_conns.items():
            if len(conns) <= 1:
                kept_param_conns.extend(conns)
                continue
            # Keep the connection whose dest appears first in nodes
            conns_sorted = sorted(conns, key=lambda c: node_order.get(c.get("destination_node"), 999))
            kept_param_conns.append(conns_sorted[0])
            for c in conns_sorted[1:]:
                print(f"Removed extra Parameter connection: {param_id} -> {c.get('destination_node')} (Parameter may connect to only one node)")
        return other_conns + kept_param_conns
    
    def _add_missing_input_pins(self, nodes: List[Dict], connections: List[Dict]) -> tuple[List[Dict], List[Dict]]:
        """
        Automatically add missing input pins to nodes when data connections require them.
        This allows nodes like CodeRunner to receive data even if they don't have input pins by default.
        NOTE: Global Data nodes never have input pins - they manage history automatically.
        NOTE: ToJson nodes have fixed input pins and should not get additional ones auto-added.
        
        RULES ENFORCED:
        - Each input pin can have ONLY ONE incoming connection
        - Parameter Nodes MUST connect to unique input pins (no sharing)
        - If input pin already exists and is connected, create a new one
        """
        node_lookup = {node["id"]: node for node in nodes}
        updated_connections = []
        
        # Track which input pins are already connected
        connected_input_pins = set()  # {(dest_node_id, input_pin_id)}
        # Track which Parameter Nodes already have connections (each Parameter Node can only connect once)
        connected_parameter_nodes = set()  # {parameter_node_id}
        
        for conn in connections:
            dest_node_id = conn.get("destination_node")
            dest_pin_id = conn.get("destination_pin")
            source_node_id = conn.get("source_node")
            
            if dest_node_id and dest_pin_id:
                # Check if destination pin is an input pin
                dest_node = node_lookup.get(dest_node_id)
                if dest_node:
                    for pin in dest_node.get("pins", {}).get("input_pins", []):
                        if pin.get("id") == dest_pin_id:
                            connected_input_pins.add((dest_node_id, dest_pin_id))
                            break
            
            # Track Parameter Nodes that already have connections
            if source_node_id:
                source_node = node_lookup.get(source_node_id)
                if source_node and source_node.get("nodeType") == "Parameter":
                    connected_parameter_nodes.add(source_node_id)
        
        for conn in connections:
            source_node = node_lookup.get(conn.get("source_node"))
            dest_node = node_lookup.get(conn.get("destination_node"))
            
            if not source_node or not dest_node:
                updated_connections.append(conn)
                continue
            
            # Skip Global Data nodes - they never have input pins and manage history automatically
            dest_node_type = dest_node.get("nodeType", "")
            if dest_node_type == "GlobalData":
                updated_connections.append(conn)
                continue
            
            # CRITICAL: Skip Switch nodes - they MUST have EXACTLY ONE input pin and should not get additional ones
            if dest_node_type == "Switch":
                updated_connections.append(conn)
                continue
            
            # RULE: Parameter nodes never have input pins. Do not add input pins to Parameter.
            if dest_node_type == "Parameter":
                updated_connections.append(conn)
                continue
            
            # RULE: Each Parameter Node connects to exactly ONE node. If already connected, do not add another.
            # (Enforced by _enforce_parameter_single_connection and _validate_input_pin_connections)
            
            # Get pin names to check if this is a data connection
            source_pin_id = conn.get("source_pin")
            dest_pin_id = conn.get("destination_pin")
            
            source_pin_name = None
            dest_pin_name = None
            
            # Find source pin name
            for pin_collection in ["output_pins", "next_pins", "trigger_pins", "input_pins"]:
                for pin in source_node.get("pins", {}).get(pin_collection, []):
                    if pin.get("id") == source_pin_id:
                        source_pin_name = pin.get("name", "")
                        break
                if source_pin_name:
                    break
            
            # Find destination pin name
            for pin_collection in ["input_pins", "trigger_pins", "output_pins", "next_pins"]:
                for pin in dest_node.get("pins", {}).get(pin_collection, []):
                    if pin.get("id") == dest_pin_id:
                        dest_pin_name = pin.get("name", "")
                        break
                if dest_pin_name:
                    break
            
            # If destination pin not found, it means we need to add it
            if not dest_pin_name:
                # Check if source is output_pin (data flow)
                source_is_data = False
                for pin in source_node.get("pins", {}).get("output_pins", []):
                    if pin.get("id") == source_pin_id:
                        source_is_data = True
                        source_pin_name = pin.get("name", "")
                        break
                
                # If it's a data connection and destination doesn't have the input pin, add it
                if source_is_data and source_pin_name:
                    # RULE: Parameter Nodes create specific input pins based on parameter key/label
                    # Each Parameter Node = one value = one specific input pin
                    is_parameter_source = source_node.get("nodeType") == "Parameter"
                    
                    # RULE: If this is a Parameter Node and it already has a connection, skip processing this connection
                    # This function only adds missing pins - it shouldn't process connections for Parameter Nodes that are already connected
                    if is_parameter_source and source_node.get("id") in connected_parameter_nodes:
                        # This Parameter Node already has a connection - just pass through the connection as-is
                        updated_connections.append(conn)
                        continue
                    
                    if is_parameter_source:
                        # For Parameter Nodes: use parameter key from configuration, or label, or output pin name
                        param_config = source_node.get("configuration", {})
                        param_key = param_config.get("Parameter Key") or param_config.get("Key") or param_config.get("parameter_key")
                        
                        if param_key:
                            # Use parameter key as input pin name (e.g., "user_message")
                            input_pin_name = param_key
                        else:
                            # Fallback: use node label or output pin name
                            source_label = source_node.get("label", "")
                            # Extract meaningful name from label (remove "Parameter Node" suffix)
                            if "Parameter" in source_label:
                                input_pin_name = source_label.split("(")[0].strip().lower().replace(" ", "_")
                            else:
                                input_pin_name = source_label.lower().replace(" ", "_") if source_label else source_pin_name
                    else:
                        # For non-Parameter nodes: use source pin name or common pattern
                        input_pin_name = source_pin_name
                        
                        # Common mapping: if source is "Response", use "Data" or "Response" as input pin name
                        if source_pin_name.lower() == "response":
                            # Check if node already has "Response" input, otherwise use "Data"
                            has_response_input = any(
                                pin.get("name", "").lower() == "response" 
                                for pin in dest_node.get("pins", {}).get("input_pins", [])
                            )
                            input_pin_name = "Response" if has_response_input else "Data"
                        elif source_pin_name.lower() in ["output", "text", "json"]:
                            input_pin_name = "Data"
                        elif source_pin_name.lower() == "data":
                            # For generic "Data" output, check if we should use a more specific name
                            # If source is a Parameter node (already handled above), use parameter key
                            # Otherwise, use "Data"
                            input_pin_name = "Data"
                    
                        # RULE: Check if input pin with this name exists (excluding Chat History)
                        existing_pin = None
                        for pin in dest_node.get("pins", {}).get("input_pins", []):
                            pin_name = pin.get("name", "").lower()
                            # RULE: Never use Chat History pins for Parameter Node connections
                            if pin_name == input_pin_name.lower() and "chat history" not in pin_name:
                                existing_pin = pin
                                break
                    
                    # RULE: If input pin exists but is already connected, create a new one
                    # RULE: Parameter Nodes MUST connect to unique input pins (no sharing)
                    if existing_pin:
                        existing_pin_id = existing_pin.get("id")
                        dest_node_id = dest_node.get("id")
                        
                        # Check if this input pin is already connected
                        if (dest_node_id, existing_pin_id) in connected_input_pins:
                            # Input pin is already connected - create a new one
                            # For Parameter Nodes, always create unique input pins
                            if is_parameter_source:
                                # Create a new unique input pin for this Parameter Node
                                new_input_pin = {
                                    "id": str(uuid.uuid4()),
                                    "name": input_pin_name,
                                    "editable": True
                                }
                                dest_node["pins"]["input_pins"].append(new_input_pin)
                                
                                # Add input pin to node configuration
                                if "configuration" not in dest_node:
                                    dest_node["configuration"] = {}
                                config_key = f"InputPin_{input_pin_name}" or input_pin_name
                                if config_key not in dest_node["configuration"]:
                                    dest_node["configuration"][config_key] = ""
                                
                                conn["destination_pin"] = new_input_pin["id"]
                                connected_input_pins.add((dest_node_id, new_input_pin["id"]))
                                
                                source_label = source_node.get("label", source_node.get("nodeType"))
                                print(f"Auto-added unique input pin '{input_pin_name}' to node {dest_node.get('label', dest_node.get('nodeType'))} for Parameter Node '{source_label}' (existing pin was already connected) and added to configuration")
                            else:
                                # For non-Parameter nodes, reuse existing pin if not connected
                                conn["destination_pin"] = existing_pin_id
                                connected_input_pins.add((dest_node_id, existing_pin_id))
                        else:
                            # Input pin exists but is not connected - use it
                            conn["destination_pin"] = existing_pin_id
                            connected_input_pins.add((dest_node_id, existing_pin_id))
                    else:
                        # Input pin doesn't exist - create it
                        # Skip ToJson nodes - they have fixed input pins and should not get additional ones auto-added
                        if dest_node_type == "ToJson":
                            # Don't add new input pin to ToJson, but keep the connection (it will fail gracefully if pin doesn't exist)
                            updated_connections.append(conn)
                            continue
                        
                        # RULE: Never create Chat History pins
                        if "chat history" in input_pin_name.lower():
                            # Skip creating Chat History pins - they are managed separately
                            updated_connections.append(conn)
                            continue
                        
                        # RULE: Additive, non-destructive - add new input pin without removing existing ones
                        new_input_pin = {
                            "id": str(uuid.uuid4()),
                            "name": input_pin_name,
                            "editable": True  # Mark as editable since it was auto-added
                        }
                        dest_node["pins"]["input_pins"].append(new_input_pin)
                        
                        # Add input pin to node configuration
                        if "configuration" not in dest_node:
                            dest_node["configuration"] = {}
                        
                        # Add input pin to configuration (for nodes that support it)
                        config_key = f"InputPin_{input_pin_name}" or input_pin_name
                        if config_key not in dest_node["configuration"]:
                            dest_node["configuration"][config_key] = ""
                        
                        # Update connection to use the new pin ID
                        conn["destination_pin"] = new_input_pin["id"]
                        dest_node_id = dest_node.get("id")
                        connected_input_pins.add((dest_node_id, new_input_pin["id"]))
                        
                        source_label = source_node.get("label", source_node.get("nodeType"))
                        print(f"Auto-added input pin '{input_pin_name}' to node {dest_node.get('label', dest_node.get('nodeType'))} for Parameter Node '{source_label}' and added to configuration")
            
            updated_connections.append(conn)
        
        return nodes, updated_connections
    
    def _add_missing_output_pins(self, nodes: List[Dict], connections: List[Dict]) -> tuple[List[Dict], List[Dict]]:
        """
        Automatically add missing output pins to nodes when data connections require them.
        This allows nodes to output data even if they don't have output pins by default.
        """
        node_lookup = {node["id"]: node for node in nodes}
        updated_connections = []
        
        for conn in connections:
            source_node = node_lookup.get(conn.get("source_node"))
            dest_node = node_lookup.get(conn.get("destination_node"))
            
            if not source_node or not dest_node:
                updated_connections.append(conn)
                continue
            
            # Get pin names to check if this is a data connection
            source_pin_id = conn.get("source_pin")
            dest_pin_id = conn.get("destination_pin")
            
            source_pin_name = None
            dest_pin_name = None
            
            # Find source pin name
            for pin_collection in ["output_pins", "next_pins", "trigger_pins", "input_pins"]:
                for pin in source_node.get("pins", {}).get(pin_collection, []):
                    if pin.get("id") == source_pin_id:
                        source_pin_name = pin.get("name", "")
                        break
                if source_pin_name:
                    break
            
            # Find destination pin name
            for pin_collection in ["input_pins", "trigger_pins", "output_pins", "next_pins"]:
                for pin in dest_node.get("pins", {}).get(pin_collection, []):
                    if pin.get("id") == dest_pin_id:
                        dest_pin_name = pin.get("name", "")
                        break
                if dest_pin_name:
                    break
            
            # If source pin not found, it means we need to add it as output pin
            if not source_pin_name:
                # RULE: Parameter nodes NEVER get new pins. They have exactly one output_pin by default. Do not add.
                if source_node.get("nodeType") == "Parameter":
                    updated_connections.append(conn)
                    continue
                # Check if destination is input_pin (data flow)
                dest_is_data = False
                for pin in dest_node.get("pins", {}).get("input_pins", []):
                    if pin.get("id") == dest_pin_id:
                        dest_is_data = True
                        dest_pin_name = pin.get("name", "")
                        break
                
                # If it's a data connection and source doesn't have the output pin, add it
                if dest_is_data and dest_pin_name:
                    # Determine the output pin name (use destination pin name or common pattern)
                    output_pin_name = dest_pin_name
                    
                    # Common mapping: if dest is "Data", use "Data" as output pin name
                    # If dest is "Response", use "Response" or "Data" as output pin name
                    if dest_pin_name.lower() == "response":
                        # Check if node already has "Response" output, otherwise use "Data"
                        has_response_output = any(
                            pin.get("name", "").lower() == "response" 
                            for pin in source_node.get("pins", {}).get("output_pins", [])
                        )
                        output_pin_name = "Response" if has_response_output else "Data"
                    elif dest_pin_name.lower() in ["input", "data"]:
                        output_pin_name = "Data"
                    
                    # Check if this output pin already exists
                    pin_exists = any(
                        pin.get("name", "").lower() == output_pin_name.lower()
                        for pin in source_node.get("pins", {}).get("output_pins", [])
                    )
                    
                    if not pin_exists:
                        # Add the missing output pin
                        new_output_pin = {
                            "id": str(uuid.uuid4()),
                            "name": output_pin_name,
                            "editable": True  # Mark as editable since it was auto-added
                        }
                        source_node["pins"]["output_pins"].append(new_output_pin)
                        
                        # Update connection to use the new pin ID
                        conn["source_pin"] = new_output_pin["id"]
                        
                        print(f"Auto-added output pin '{output_pin_name}' to node {source_node.get('label', source_node.get('nodeType'))} for data connection to {dest_node.get('label', dest_node.get('nodeType'))}")
            
            updated_connections.append(conn)
        
        return nodes, updated_connections
    
    def _inject_template_syntax(self, nodes: List[Dict], connections: List[Dict], respect_explicit_config: bool = False) -> List[Dict]:
        """
        Inject template syntax ({{Data}} or {{Data.key}}) into code fields when data connections exist.
        This allows nodes to use connected data in their code.
        
        RULE: If user explicitly requested configuration changes, don't override their specified values.
        """
        node_lookup = {node["id"]: node for node in nodes}
        
        # Build a map of which input pins receive data from which output pins
        input_pin_connections = {}  # {node_id: {input_pin_name: source_info}}
        
        for conn in connections:
            source_node_id = conn.get("source_node")
            dest_node_id = conn.get("destination_node")
            source_pin_id = conn.get("source_pin")
            dest_pin_id = conn.get("destination_pin")
            
            source_node = node_lookup.get(source_node_id)
            dest_node = node_lookup.get(dest_node_id)
            
            if not source_node or not dest_node:
                continue
            
            # Find source pin name
            source_pin_name = None
            for pin_collection in ["output_pins", "next_pins", "trigger_pins", "input_pins"]:
                for pin in source_node.get("pins", {}).get(pin_collection, []):
                    if pin.get("id") == source_pin_id:
                        source_pin_name = pin.get("name", "")
                        break
                if source_pin_name:
                    break
            
            # Find destination pin name
            dest_pin_name = None
            for pin_collection in ["input_pins", "trigger_pins", "output_pins", "next_pins"]:
                for pin in dest_node.get("pins", {}).get(pin_collection, []):
                    if pin.get("id") == dest_pin_id:
                        dest_pin_name = pin.get("name", "")
                        break
                if dest_pin_name:
                    break
            
            # Only process data flow connections (output -> input)
            if source_pin_name and dest_pin_name:
                # Check if this is a data connection (not control)
                source_is_data = any(
                    pin.get("id") == source_pin_id
                    for pin in source_node.get("pins", {}).get("output_pins", [])
                )
                dest_is_data = any(
                    pin.get("id") == dest_pin_id
                    for pin in dest_node.get("pins", {}).get("input_pins", [])
                )
                
                if source_is_data and dest_is_data:
                    if dest_node_id not in input_pin_connections:
                        input_pin_connections[dest_node_id] = {}
                    input_pin_connections[dest_node_id][dest_pin_name] = {
                        "source_pin_name": source_pin_name,
                        "source_node_label": source_node.get("label", source_node.get("nodeType"))
                    }
        
        # Now inject template syntax into ALL configuration fields for ALL nodes
        # This includes code fields, text fields, message fields, etc.
        
        for node in nodes:
            node_type = node.get("nodeType")
            node_id = node.get("id")
            configuration = node.get("configuration", {})
            
            if not configuration:
                continue
            
            # Check if this node has input pins with data connections
            has_data_connections = node_id in input_pin_connections
            
            # Process ALL configuration fields, not just code fields
            fields_updated = False
            
            for field_id, field_value in configuration.items():
                if not isinstance(field_value, str):
                    continue
                
                updated_value = field_value
                
                # RULE: If user explicitly requested configuration changes, respect their values
                # Only do minimal template syntax fixes (normalize braces) without overriding content
                if respect_explicit_config:
                    # User explicitly set this value - normalize braces and pin names, don't add template variables
                    # STEP 1: Normalize all brace patterns to exactly {{variable}}
                    # RULE: Normalize {var} → {{var}}, {{{var}}} → {{var}}, {{{{var}}}} → {{var}}, etc.
                    brace_pattern = r'\{+([A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z0-9_]+)*)\}+'
                    
                    def normalize_braces(match):
                        """Normalize braces to exactly {{variable}}"""
                        var_name = match.group(1)
                        return f"{{{{{var_name}}}}}"
                    
                    # Normalize all brace patterns to exactly {{variable}}
                    normalized_value = re.sub(brace_pattern, normalize_braces, updated_value)
                    
                    if normalized_value != updated_value:
                        updated_value = normalized_value
                        fields_updated = True
                        print(f"Normalized braces in {node.get('label', node_type)} field '{field_id}' (preserving user-specified value)")
                    
                    # STEP 2: If node has data connections, normalize variable names to match input pin names exactly
                    if has_data_connections:
                        input_pin_names = list(input_pin_connections[node_id].keys())
                        
                        # Pattern to match any template variable: {{variable}} or {variable} or {{{variable}}}, etc.
                        template_var_pattern = r'\{+([A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z0-9_]+)*)\}+'
                        
                        def replace_with_correct_pin_name(match):
                            """Replace template variable with correct input pin name (exact match)"""
                            var_name = match.group(1)
                            base_name = var_name.split('.')[0]
                            
                            # Check if variable matches any input pin name (case-insensitive)
                            for pin_name in input_pin_names:
                                if base_name.lower() == pin_name.lower():
                                    # Match found - use EXACT pin name (preserve case) and preserve property access if any
                                    if '.' in var_name:
                                        property_part = var_name.split('.', 1)[1]
                                        return f"{{{{{pin_name}.{property_part}}}}}"
                                    else:
                                        return f"{{{{{pin_name}}}}}"
                            
                            # No match found - normalize braces but keep variable name as-is
                            return f"{{{{{var_name}}}}}"
                        
                        # Replace template variables with correct pin names (exact match)
                        corrected_value = re.sub(template_var_pattern, replace_with_correct_pin_name, updated_value)
                        
                        if corrected_value != updated_value:
                            updated_value = corrected_value
                            fields_updated = True
                            print(f"Normalized template variable names to match input pin names in {node.get('label', node_type)} field '{field_id}'")
                    
                    # Don't inject additional template syntax - user explicitly set this value
                    if updated_value != field_value:
                        configuration[field_id] = updated_value
                    continue
                
                # STEP 1: Normalize all brace patterns to exactly {{variable}}
                # RULE: Normalize {var} → {{var}}, {{{var}}} → {{var}}, {{{{var}}}} → {{var}}, etc.
                # Pattern to match any number of braces with variable name
                brace_pattern = r'\{+([A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z0-9_]+)*)\}+'
                
                def normalize_braces(match):
                    """Normalize braces to exactly {{variable}}"""
                    var_name = match.group(1)
                    return f"{{{{{var_name}}}}}"
                
                # Normalize all brace patterns to exactly {{variable}}
                normalized_value = re.sub(brace_pattern, normalize_braces, updated_value)
                
                if normalized_value != updated_value:
                    updated_value = normalized_value
                    fields_updated = True
                    print(f"Normalized braces in {node.get('label', node_type)} field '{field_id}': {field_value[:50]} -> {updated_value[:50]}")
                
                # STEP 2: Normalize template variables to match input pin names exactly
                # RULE: Replace any template variable with the correct input pin name (destination node's input pin name)
                # CRITICAL: Use destination node's INPUT PIN NAME, NOT source node's OUTPUT PIN NAME
                # Find all template variables in the text and ensure they match input pin names
                if has_data_connections:
                    # Get all input pin names for this node (destination node's input pins)
                    input_pin_names = list(input_pin_connections[node_id].keys())
                    
                    # Build mapping: source_pin_name -> destination_input_pin_name
                    # This helps replace source node output pin names with destination input pin names
                    source_to_dest_pin_map = {}
                    for dest_input_pin_name, source_info in input_pin_connections[node_id].items():
                        source_pin_name = source_info.get("source_pin_name", "")
                        if source_pin_name:
                            source_to_dest_pin_map[source_pin_name.lower()] = dest_input_pin_name
                    
                    # Pattern to match any template variable: {{variable}} or {variable} or {{{variable}}}, etc.
                    template_var_pattern = r'\{+([A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z0-9_]+)*)\}+'
                    
                    def replace_with_correct_pin_name(match):
                        """Replace template variable with correct input pin name (destination node's input pin name)"""
                        var_name = match.group(1)
                        # Extract base name (without property access)
                        base_name = var_name.split('.')[0]
                        
                        # RULE 1: If variable matches a source output pin name, replace with destination input pin name
                        if base_name.lower() in source_to_dest_pin_map:
                            dest_pin_name = source_to_dest_pin_map[base_name.lower()]
                            # Use destination input pin name (exact case)
                            if '.' in var_name:
                                # Has property access: {{dest_pin_name.property}}
                                property_part = var_name.split('.', 1)[1]
                                return f"{{{{{dest_pin_name}.{property_part}}}}}"
                            else:
                                # No property access: {{dest_pin_name}}
                                return f"{{{{{dest_pin_name}}}}}"
                        
                        # RULE 2: If variable matches any input pin name (case-insensitive), use exact input pin name
                        for pin_name in input_pin_names:
                            if base_name.lower() == pin_name.lower():
                                # Match found - use EXACT pin name (preserve case) and preserve property access if any
                                if '.' in var_name:
                                    # Has property access: {{pin_name.property}}
                                    property_part = var_name.split('.', 1)[1]
                                    return f"{{{{{pin_name}.{property_part}}}}}"
                                else:
                                    # No property access: {{pin_name}} - use exact pin name
                                    return f"{{{{{pin_name}}}}}"
                        
                        # No match found - normalize braces but keep variable name as-is
                        return f"{{{{{var_name}}}}}"
                    
                    # Replace template variables with correct pin names (destination input pin names)
                    corrected_value = re.sub(template_var_pattern, replace_with_correct_pin_name, updated_value)
                    
                    if corrected_value != updated_value:
                        updated_value = corrected_value
                        fields_updated = True
                        print(f"Normalized template variable names to match input pin names (destination node's input pins) in {node.get('label', node_type)} field '{field_id}'")
                
                # STEP 3: If node has data connections, inject template syntax for connected pins
                # RULE: Template variable name MUST match input pin name exactly
                # Example: If input pin is "Data" → use {{Data}}, if input pin is "order" → use {{order}}
                if has_data_connections:
                    for input_pin_name, source_info in input_pin_connections[node_id].items():
                        # CRITICAL: Use double curly braces for Jinja2: {{pin_name}} - pin name must match exactly
                        # The input_pin_name is the EXACT name of the input pin (e.g., "Data", "order", "student_name")
                        template_var = f"{{{{{input_pin_name}}}}}"
                        
                        # Check if template syntax already exists with correct pin name (case-insensitive match)
                        # Pattern to match any brace variation with this pin name: {pin_name}, {{pin_name}}, {{{pin_name}}}, etc.
                        pin_name_pattern = r'\{+' + re.escape(input_pin_name) + r'\}+'
                        already_exists = bool(re.search(pin_name_pattern, updated_value, re.IGNORECASE))
                        
                        # RULE: Normalize any existing template variables with this pin name to exactly {{pin_name}}
                        # This ensures {pin_name}, {{{pin_name}}}, {{{{pin_name}}}} all become {{pin_name}}
                        # CRITICAL: Use EXACT input pin name (preserve case) - if pin is "order", use {{order}}, not {{Order}}
                        def normalize_pin_name_braces(match):
                            """Normalize braces for this specific pin name to exactly {{pin_name}} with exact case"""
                            return f"{{{{{input_pin_name}}}}}"
                        
                        normalized_pin_value = re.sub(pin_name_pattern, normalize_pin_name_braces, updated_value, flags=re.IGNORECASE)
                        if normalized_pin_value != updated_value:
                            updated_value = normalized_pin_value
                            fields_updated = True
                            print(f"Normalized template variable '{input_pin_name}' to exactly {{{{{input_pin_name}}}}} in {node.get('label', node_type)} field '{field_id}'")
                        
                        if not already_exists:
                            # For code fields, add example code
                            if field_id in ["code", "Code", "code_snippet", "script"]:
                                if not updated_value.strip():
                                    if node_type == "CodeRunner":
                                        updated_value = f"// Use {input_pin_name} from previous node\nconst data = {template_var};\nconsole.log(data);"
                                    elif node_type == "Python":
                                        updated_value = f"# Use {input_pin_name} from previous node\ndata = {template_var}\nprint(data)"
                                    else:
                                        updated_value = f"// Use {input_pin_name} from previous node\n{template_var}"
                                    fields_updated = True
                                else:
                                    # Add comment about available data
                                    comment = f"\n// Available: {template_var} (from {source_info['source_node_label']})"
                                    if comment not in updated_value:
                                        updated_value = updated_value + comment
                                        fields_updated = True
                            # For text fields (Message, Instructions, etc.), add template syntax
                            # RULE: If field is empty, set it to template variable
                            # RULE: If field has content, append template variable if not already present
                            elif field_id in ["Message", "Instructions", "Text", "TO", "Subject", "Body"]:
                                if not updated_value.strip():
                                    # Field is empty - set to template variable
                                    updated_value = template_var
                                    fields_updated = True
                                else:
                                    # Field has content - check if template variable is already present
                                    # Check for any variation: {pin_name}, {{pin_name}}, {{{pin_name}}}, etc.
                                    pin_name_pattern_check = r'\{+' + re.escape(input_pin_name) + r'\}+'
                                    if not re.search(pin_name_pattern_check, updated_value, re.IGNORECASE):
                                        # Template variable not present - append it
                                        # For Message field, append on new line or space
                                        if field_id == "Message":
                                            updated_value = f"{updated_value}\n{template_var}"
                                        else:
                                            updated_value = f"{updated_value} {template_var}"
                                        fields_updated = True
                
                # Update the field value
                if updated_value != field_value:
                    configuration[field_id] = updated_value
            
            # Update node configuration if any fields were updated
            if fields_updated:
                node["configuration"] = configuration
                print(f"Updated template syntax in {node.get('label', node_type)} configuration fields")
        
        return nodes
    
    def _normalize_parameter_node_pins(self, nodes: List[Dict]) -> List[Dict]:
        """
        Normalize Parameter nodes: exactly one output_pin, no input/trigger/next pins.
        Parameter nodes never have input pins, trigger pins, or next_pins. They have
        one and only one output_pin by default. Do not create any other pins.
        """
        for node in nodes:
            if node.get("nodeType") != "Parameter":
                continue
            pins = node.get("pins", {})
            op = pins.get("output_pins", [])
            if len(op) == 0:
                pins["output_pins"] = [{"id": str(uuid.uuid4()), "name": "Data"}]
            elif len(op) > 1:
                pins["output_pins"] = [op[0]]
            pins["trigger_pins"] = []
            pins["input_pins"] = []
            pins["next_pins"] = []
        return nodes

    def _validate_parameter_nodes(self, nodes: List[Dict]) -> tuple[bool, str]:
        """
        Validate that Parameter Nodes have exactly ONE output pin and no input/trigger/next pins.
        Parameter nodes never have input pins, trigger pins, or next_pins (out pins).
        """
        for node in nodes:
            if node.get("nodeType") == "Parameter":
                p = node.get("pins", {})
                op = p.get("output_pins", [])
                if len(op) != 1:
                    return False, f"Parameter Node '{node.get('label', 'Unknown')}' must have exactly one output pin."
                if p.get("input_pins"):
                    return False, f"Parameter Node '{node.get('label', 'Unknown')}' must not have input pins."
                if p.get("trigger_pins"):
                    return False, f"Parameter Node '{node.get('label', 'Unknown')}' must not have trigger pins."
                if p.get("next_pins"):
                    return False, f"Parameter Node '{node.get('label', 'Unknown')}' must not have next_pins (out pins)."
        return True, ""
    
    def _cleanup_switch_node_input_pins(self, nodes: List[Dict]) -> List[Dict]:
        """
        Clean up Switch nodes to ensure they have EXACTLY ONE input pin.
        If a Switch node has multiple input pins, keep only the first one.
        
        Returns:
            Updated nodes list with Switch nodes having exactly one input pin
        """
        for node in nodes:
            if node.get("nodeType") == "Switch":
                input_pins = node.get("pins", {}).get("input_pins", [])
                
                if len(input_pins) > 1:
                    # Keep only the first input pin
                    first_input_pin = input_pins[0]
                    node["pins"]["input_pins"] = [first_input_pin]
                    print(f"CLEANUP: Switch Node '{node.get('label', 'Unknown')}' had {len(input_pins)} input pins. Kept only the first one: '{first_input_pin.get('name', 'Unknown')}'")
                elif len(input_pins) == 0:
                    # If no input pin exists, create a default one
                    default_input_pin = {
                        "id": str(uuid.uuid4()),
                        "name": "Input",
                        "editable": False
                    }
                    node["pins"]["input_pins"] = [default_input_pin]
                    print(f"CLEANUP: Switch Node '{node.get('label', 'Unknown')}' had no input pins. Created default 'Input' pin")
        
        return nodes
    
    def _validate_switch_nodes(self, nodes: List[Dict]) -> tuple[bool, str]:
        """
        Validate Switch Node rules:
        - Switch Node MUST have EXACTLY ONE input pin
        - Switch Node MUST have MULTIPLE out pins (next_pins)
        - Switch Node MUST have a "default" out pin
        - Out pins are execution pins (next_pins), not data output pins
        
        Returns:
            (is_valid, error_message)
        """
        for node in nodes:
            if node.get("nodeType") == "Switch":
                node_label = node.get("label", "Unknown")
                pins = node.get("pins", {})
                
                # Rule 1: Switch Node MUST have EXACTLY ONE input pin
                input_pins = pins.get("input_pins", [])
                if len(input_pins) == 0:
                    return False, f"Switch Node '{node_label}' has no input pins. Switch Nodes MUST have EXACTLY ONE input pin."
                if len(input_pins) > 1:
                    return False, f"Switch Node '{node_label}' has {len(input_pins)} input pins. Switch Nodes MUST have EXACTLY ONE input pin."
                
                # Rule 2: Switch Node MUST have MULTIPLE out pins (next_pins for execution flow)
                out_pins = pins.get("next_pins", [])
                if len(out_pins) == 0:
                    return False, f"Switch Node '{node_label}' has no out pins. Switch Nodes MUST have at least one out pin (including 'default')."
                
                # Rule 3: Switch Node MUST have a "default" out pin
                has_default = any(
                    pin.get("name", "").lower() == "default"
                    for pin in out_pins
                )
                if not has_default:
                    return False, f"Switch Node '{node_label}' is missing the required 'default' out pin. Switch Nodes MUST always have a 'default' out pin."
                
                # Rule 4: Out pins should be in next_pins (execution flow), not output_pins (data flow)
                output_pins = pins.get("output_pins", [])
                if len(output_pins) > 0:
                    # Check if output pins are being used incorrectly for Switch Node
                    # Switch Nodes should use next_pins for execution routing, not output_pins
                    print(f"WARNING: Switch Node '{node_label}' has {len(output_pins)} output pins. Switch Nodes route execution via next_pins (out pins), not output_pins.")
        
        return True, ""
    
    def _validate_input_pin_connections(self, connections: List[Dict], nodes: List[Dict]) -> tuple[bool, str]:
        """
        Validate input pin connection constraints:
        - Each input pin can have ONLY ONE incoming connection
        - Parameter Nodes MUST connect to unique input pins (no sharing)
        
        Returns:
            (is_valid, error_message)
        """
        node_lookup = {node["id"]: node for node in nodes}
        
        # Track input pin connections: {destination_node_id: {input_pin_id: [connections]}}
        input_pin_connections = {}
        
        # Track Parameter Node connections: {parameter_node_id: set of destination_input_pin_ids}
        parameter_connections = {}  # {parameter_node_id: {input_pin_id1, input_pin_id2, ...}}
        
        # Track unique connections to avoid counting duplicates
        seen_connections = set()  # {(source_node_id, dest_node_id, source_pin_id, dest_pin_id)}
        
        for conn in connections:
            source_node = node_lookup.get(conn.get("source_node"))
            dest_node = node_lookup.get(conn.get("destination_node"))
            dest_pin_id = conn.get("destination_pin")
            source_pin_id = conn.get("source_pin")
            
            if not source_node or not dest_node:
                continue
            
            # Skip duplicate connections (same source, dest, and pins)
            conn_key = (source_node.get("id"), dest_node.get("id"), source_pin_id, dest_pin_id)
            if conn_key in seen_connections:
                continue  # Skip duplicate connection
            seen_connections.add(conn_key)
            
            # Check if destination pin is an input pin
            dest_is_input_pin = False
            for pin in dest_node.get("pins", {}).get("input_pins", []):
                if pin.get("id") == dest_pin_id:
                    dest_is_input_pin = True
                    break
            
            if dest_is_input_pin:
                # Track input pin connections
                dest_node_id = dest_node.get("id")
                if dest_node_id not in input_pin_connections:
                    input_pin_connections[dest_node_id] = {}
                if dest_pin_id not in input_pin_connections[dest_node_id]:
                    input_pin_connections[dest_node_id][dest_pin_id] = []
                
                input_pin_connections[dest_node_id][dest_pin_id].append(conn)
                
                # Track Parameter Node connections
                if source_node.get("nodeType") == "Parameter":
                    param_node_id = source_node.get("id")
                    if param_node_id not in parameter_connections:
                        parameter_connections[param_node_id] = set()
                    parameter_connections[param_node_id].add(dest_pin_id)
        
        # Validate: Each input pin can have ONLY ONE incoming connection
        for dest_node_id, pin_conns in input_pin_connections.items():
            dest_node = node_lookup.get(dest_node_id)
            dest_node_label = dest_node.get("label", dest_node.get("nodeType", "Unknown")) if dest_node else "Unknown"
            
            for input_pin_id, conns in pin_conns.items():
                if len(conns) > 1:
                    # Find input pin name
                    input_pin_name = "Unknown"
                    if dest_node:
                        for pin in dest_node.get("pins", {}).get("input_pins", []):
                            if pin.get("id") == input_pin_id:
                                input_pin_name = pin.get("name", "Unknown")
                                break
                    
                    source_labels = []
                    for conn in conns:
                        source_node = node_lookup.get(conn.get("source_node"))
                        if source_node:
                            source_labels.append(source_node.get("label", source_node.get("nodeType", "Unknown")))
                    
                    return False, f"Input pin '{input_pin_name}' on node '{dest_node_label}' has {len(conns)} incoming connections from {source_labels}. Each input pin can have ONLY ONE incoming connection."
        
        # RULE: Each Parameter Node MUST connect to exactly ONE node. If connected to any node, do NOT connect to another.
        for param_node_id, input_pin_ids in parameter_connections.items():
            if len(input_pin_ids) > 1:
                param_node = node_lookup.get(param_node_id)
                param_label = param_node.get("label", param_node.get("nodeType", "Unknown")) if param_node else "Unknown"
                return False, f"Parameter node '{param_label}' has {len(input_pin_ids)} outgoing connections. Each Parameter node MUST connect to exactly ONE node only."
        
        # Validate: Parameter Nodes connect to unique input pins (no sharing)
        # Check if multiple Parameter Nodes connect to the same input pin
        input_pin_to_params = {}  # {input_pin_id: [parameter_node_ids]}
        for param_node_id, input_pin_ids in parameter_connections.items():
            for input_pin_id in input_pin_ids:
                if input_pin_id not in input_pin_to_params:
                    input_pin_to_params[input_pin_id] = []
                input_pin_to_params[input_pin_id].append(param_node_id)
        
        for input_pin_id, param_node_ids in input_pin_to_params.items():
            if len(param_node_ids) > 1:
                # Find the node and pin name
                dest_node_label = "Unknown"
                input_pin_name = "Unknown"
                for node in nodes:
                    for pin in node.get("pins", {}).get("input_pins", []):
                        if pin.get("id") == input_pin_id:
                            dest_node_label = node.get("label", node.get("nodeType", "Unknown"))
                            input_pin_name = pin.get("name", "Unknown")
                            break
                    if input_pin_name != "Unknown":
                        break
                
                param_labels = []
                for param_node_id in param_node_ids:
                    param_node = node_lookup.get(param_node_id)
                    if param_node:
                        param_labels.append(param_node.get("label", param_node.get("nodeType", "Unknown")))
                
                return False, f"Input pin '{input_pin_name}' on node '{dest_node_label}' is shared by {len(param_node_ids)} Parameter Nodes ({param_labels}). Each Parameter Node MUST connect to a UNIQUE input pin."
        
        return True, ""
    
    def _validate_response_node_connections(self, connections: List[Dict], nodes: List[Dict]) -> tuple[bool, str]:
        """
        Validate that Response nodes have the REQUIRED connections:
        
        MANDATORY RULES:
        1. A Response Node MUST always be connected to a previous node.
        2. When a Response Node is added after ANY previous node, TWO connections are REQUIRED:
           A. CONTROL FLOW: Previous Node Out/Next/Output → Response Node Start (trigger pin)
           B. DATA FLOW: Previous Node Response/Output/Result → Response Node Response (input pin)
        3. If both have Chat History pins, they should be connected.
        
        Returns:
            (is_valid, error_message)
        """
        node_lookup = {node["id"]: node for node in nodes}
        
        # Find all Response nodes
        response_nodes = [node for node in nodes if node.get("nodeType") == "Response"]
        
        for response_node in response_nodes:
            response_node_id = response_node.get("id")
            response_label = response_node.get("label", response_node.get("nodeType", "Unknown"))
            
            # Find connections TO this Response node
            incoming_connections = [
                conn for conn in connections
                if conn.get("destination_node") == response_node_id
            ]
            
            if not incoming_connections:
                return False, f"Response node '{response_label}' has NO incoming connections. Response nodes MUST always be connected to a previous node."
            
            # Check for required connections
            has_control_flow = False  # Previous Out/Next → Response Start
            has_data_flow = False     # Previous Response/Output → Response Response Input
            
            for conn in incoming_connections:
                source_node_id = conn.get("source_node")
                source_node = node_lookup.get(source_node_id)
                
                if not source_node:
                    continue
                
                # Get pin names
                source_pin_name = self._get_pin_name_by_id(nodes, source_node_id, conn.get("source_pin"))
                dest_pin_name = self._get_pin_name_by_id(nodes, response_node_id, conn.get("destination_pin"))
                
                if not source_pin_name or not dest_pin_name:
                    continue
                
                source_lower = source_pin_name.lower()
                dest_lower = dest_pin_name.lower()
                
                # Check for CONTROL FLOW connection: Previous Out/Next/Output → Response Start
                if source_lower in ["next", "out", "output"] and dest_lower == "start":
                    has_control_flow = True
                
                # Check for DATA FLOW connection: Previous Response/Output/Result → Response Response Input
                if source_lower in ["response", "output", "result"] and dest_lower == "response":
                    has_data_flow = True
            
            # Validate required connections
            if not has_control_flow:
                return False, f"Response node '{response_label}' is missing REQUIRED CONTROL FLOW connection. Previous node Out/Next/Output pin MUST connect to Response Start pin."
            
            if not has_data_flow:
                # Check if previous node has Response/Output/Result pin AND Response node has Response input pin
                # Only require connection if both pins exist and are available
                previous_nodes = [
                    node_lookup.get(conn.get("source_node"))
                    for conn in incoming_connections
                    if node_lookup.get(conn.get("source_node"))
                ]
                
                # Check if Response node has Response input pin
                response_has_response_input = False
                response_input_pins = response_node.get("pins", {}).get("input_pins", [])
                for pin in response_input_pins:
                    pin_name = pin.get("name", "").lower()
                    if pin_name == "response":
                        response_has_response_input = True
                        break
                
                # Check if previous node has Response/Output/Result pin
                previous_has_response_output = False
                previous_response_pin_id = None
                for prev_node in previous_nodes:
                    if prev_node:
                        output_pins = prev_node.get("pins", {}).get("output_pins", [])
                        for pin in output_pins:
                            pin_name = pin.get("name", "").lower()
                            if pin_name in ["response", "output", "result"]:
                                previous_has_response_output = True
                                previous_response_pin_id = pin.get("id")
                                break
                        if previous_has_response_output:
                            break
                
                # Only require data flow connection if:
                # 1. Previous node has Response/Output/Result pin
                # 2. Response node has Response input pin
                # 3. Both pins are available (not already connected)
                if previous_has_response_output and response_has_response_input:
                    # Find the previous node that has the Response/Output pin
                    previous_node_with_output = None
                    for prev_node in previous_nodes:
                        if prev_node:
                            output_pins = prev_node.get("pins", {}).get("output_pins", [])
                            for pin in output_pins:
                                pin_name = pin.get("name", "").lower()
                                if pin_name in ["response", "output", "result"]:
                                    previous_node_with_output = prev_node
                                    previous_response_pin_id = pin.get("id")
                                    break
                            if previous_node_with_output:
                                break
                    
                    if previous_node_with_output:
                        # Check if pins are already connected to something else
                        previous_pin_connected = any(
                            c.get("source_pin") == previous_response_pin_id
                            for c in connections
                            if c.get("source_node") == previous_node_with_output.get("id")
                        )
                        response_pin_connected = any(
                            c.get("destination_pin") == pin.get("id")
                            for c in connections
                            for pin in response_input_pins
                            if pin.get("name", "").lower() == "response"
                        )
                        
                        # Only fail if pins are available but not connected to each other
                        if not previous_pin_connected and not response_pin_connected:
                            return False, f"Response node '{response_label}' is missing REQUIRED DATA FLOW connection. Previous node Response/Output/Result pin MUST connect to Response Response input pin."
                        # If pins are already connected to other things, that's okay - don't fail validation
        
        return True, ""
    
    def _validate_connections(self, connections: List[Dict], nodes: List[Dict]) -> List[Dict]:
        """
        Validate connections according to CONNECTION_PIN_LOGIC.md rules:
        - Control flow: next_pins → trigger_pins ONLY
        - Data flow: output_pins → input_pins ONLY
        - Never mix types
        - STRICT RULE: Each pin can have ONLY ONE connection (max 1 connection per pin)
        - RULE: Parameter Nodes MUST connect to unique input pins (no sharing)
        - RULE: Response nodes have NO outgoing connections (terminal nodes)
        - RULE: Entry node can connect to ONLY ONE next node
        """
        valid_connections = []
        node_lookup = {node["id"]: node for node in nodes}
        
        # Track ALL pin connections to enforce strict one-connection-per-pin rule
        # Track by pin ID: {pin_id: connection} - each pin can only have ONE connection
        pin_connection_map = {}  # {pin_id: connection}
        
        # Track source pin connections (to prevent multiple connections from same source pin)
        source_pin_connections = {}  # {source_node_id: {source_pin_id: connection}}
        # Track destination pin connections (to prevent multiple connections to same dest pin)
        dest_pin_connections = {}  # {dest_node_id: {dest_pin_id: connection}}
        
        # Control pin names (execution flow)
        control_pin_names = {"next", "start", "iterate", "default", "finished"}
        # Data pin names (data passing)
        data_pin_names = {"response", "data", "connection", "output", "metadata", 
                         "chat history", "text", "json", "input", "value", "key"}
        
        for conn in connections:
            source_node = node_lookup.get(conn["source_node"])
            dest_node = node_lookup.get(conn["destination_node"])
            
            if not source_node or not dest_node:
                continue  # Skip invalid node references
            
            # STRICT RULE: Response nodes have NO outgoing connections
            if source_node.get("nodeType") == "Response":
                print(f"REJECTED: Response node '{source_node.get('label', 'Unknown')}' cannot have outgoing connections. Response nodes are terminal.")
                continue
            
            # Find source pin
            source_pin = None
            source_pin_type = None  # "control" or "data"
            source_pin_collection = None
            
            for collection in ["next_pins", "trigger_pins", "output_pins", "input_pins"]:
                for pin in source_node["pins"].get(collection, []):
                    if pin["id"] == conn["source_pin"]:
                        source_pin = pin
                        source_pin_collection = collection
                        if collection in ["next_pins", "trigger_pins"]:
                            source_pin_type = "control"
                        else:
                            source_pin_type = "data"
                        break
                if source_pin:
                    break
            
            # Find destination pin
            dest_pin = None
            dest_pin_type = None
            dest_pin_collection = None
            
            for collection in ["next_pins", "trigger_pins", "output_pins", "input_pins"]:
                for pin in dest_node["pins"].get(collection, []):
                    if pin["id"] == conn["destination_pin"]:
                        dest_pin = pin
                        dest_pin_collection = collection
                        if collection in ["next_pins", "trigger_pins"]:
                            dest_pin_type = "control"
                        else:
                            dest_pin_type = "data"
                        break
                if dest_pin:
                    break
            
            if not source_pin or not dest_pin:
                continue  # Skip if pins not found
            
            source_pin_id = source_pin.get("id")
            dest_pin_id = dest_pin.get("id")
            source_node_id = source_node.get("id")
            dest_node_id = dest_node.get("id")
            
            # STRICT RULE: Each pin can have ONLY ONE connection
            # Check if source pin already has a connection
            if source_pin_id in pin_connection_map:
                existing_conn = pin_connection_map[source_pin_id]
                existing_dest = node_lookup.get(existing_conn.get("destination_node"))
                existing_dest_label = existing_dest.get("label", existing_dest.get("nodeType", "Unknown")) if existing_dest else "Unknown"
                current_dest_label = dest_node.get("label", dest_node.get("nodeType", "Unknown"))
                source_pin_name = source_pin.get("name", "Unknown")
                source_node_label = source_node.get("label", source_node.get("nodeType", "Unknown"))
                
                print(f"REJECTED: Source pin '{source_pin_name}' on node '{source_node_label}' already has a connection to '{existing_dest_label}'. Cannot add connection to '{current_dest_label}'. Each pin can have ONLY ONE connection.")
                continue
            
            # Check if destination pin already has a connection
            if dest_pin_id in pin_connection_map:
                existing_conn = pin_connection_map[dest_pin_id]
                existing_source = node_lookup.get(existing_conn.get("source_node"))
                existing_source_label = existing_source.get("label", existing_source.get("nodeType", "Unknown")) if existing_source else "Unknown"
                current_source_label = source_node.get("label", source_node.get("nodeType", "Unknown"))
                dest_pin_name = dest_pin.get("name", "Unknown")
                dest_node_label = dest_node.get("label", dest_node.get("nodeType", "Unknown"))
                
                print(f"REJECTED: Destination pin '{dest_pin_name}' on node '{dest_node_label}' already has a connection from '{existing_source_label}'. Cannot add connection from '{current_source_label}'. Each pin can have ONLY ONE connection.")
                continue
            
            # STRICT RULE: Entry node can connect to ONLY ONE next node
            if source_node.get("nodeType") == "Entry":
                # Check if Entry node already has any outgoing connections
                entry_has_connection = any(
                    c.get("source_node") == source_node_id
                    for c in valid_connections
                )
                if entry_has_connection:
                    print(f"REJECTED: Entry node '{source_node.get('label', 'Unknown')}' already has a connection. Entry node can connect to ONLY ONE next node.")
                    continue
            
            # Validate connection type matching
            if source_pin_type != dest_pin_type:
                continue  # Skip mixed type connections (control to data or vice versa)
            
            # Validate collection matching
            if source_pin_type == "control":
                # Control flow: next_pins → trigger_pins ONLY
                if source_pin_collection != "next_pins" or dest_pin_collection != "trigger_pins":
                    continue  # Invalid control flow connection
            else:
                # Data flow: output_pins → input_pins ONLY
                if source_pin_collection != "output_pins" or dest_pin_collection != "input_pins":
                    continue  # Invalid data flow connection
            
            # Store connections in maps
            pin_connection_map[source_pin_id] = conn
            pin_connection_map[dest_pin_id] = conn
            
            if source_node_id not in source_pin_connections:
                source_pin_connections[source_node_id] = {}
            source_pin_connections[source_node_id][source_pin_id] = conn
            
            if dest_node_id not in dest_pin_connections:
                dest_pin_connections[dest_node_id] = {}
            dest_pin_connections[dest_node_id][dest_pin_id] = conn
            
            valid_connections.append(conn)
        
        return valid_connections
    
    def _auto_generate_connections(self, nodes: List[Dict], existing_connections: List[Dict] = None) -> List[Dict]:
        """
        Auto-generate connections between nodes in order - includes both control and data flow.
        Based on template_generator.py logic.
        
        Args:
            nodes: List of nodes in the workflow
            existing_connections: Existing connections to check for conflicts
        """
        if existing_connections is None:
            existing_connections = []
        
        connections = []
        connection_set = set()
        
        # STRICT RULE: Track ALL pins (source and destination) to enforce one-connection-per-pin
        connected_pins_from_existing = set()  # {pin_id} - tracks ALL pins that have connections
        connected_input_pins_from_existing = set()  # {(dest_node_id, input_pin_id)} - for backward compatibility
        connected_parameter_nodes_from_existing = set()  # {parameter_node_id}
        entry_node_has_connection = False  # Track if Entry node already has a connection
        
        node_lookup = {node["id"]: node for node in nodes}
        for conn in existing_connections:
            source_node_id = conn.get("source_node")
            dest_node_id = conn.get("destination_node")
            source_pin_id = conn.get("source_pin")
            dest_pin_id = conn.get("destination_pin")
            
            # Track ALL pins (source and destination)
            if source_pin_id:
                connected_pins_from_existing.add(source_pin_id)
            if dest_pin_id:
                connected_pins_from_existing.add(dest_pin_id)
            
            # Track Entry node connections
            if source_node_id:
                source_node = node_lookup.get(source_node_id)
                if source_node and source_node.get("nodeType") == "Entry":
                    entry_node_has_connection = True
            
            if dest_node_id and dest_pin_id:
                dest_node = node_lookup.get(dest_node_id)
                if dest_node:
                    for pin in dest_node.get("pins", {}).get("input_pins", []):
                        if pin.get("id") == dest_pin_id:
                            # RULE: Never track Chat History pins as connected
                            pin_name = pin.get("name", "").lower()
                            if "chat history" not in pin_name:
                                connected_input_pins_from_existing.add((dest_node_id, dest_pin_id))
                            break
            
            # Track Parameter Nodes that already have connections
            if source_node_id:
                source_node = node_lookup.get(source_node_id)
                if source_node and source_node.get("nodeType") == "Parameter":
                    connected_parameter_nodes_from_existing.add(source_node_id)
        
        # Find Entry node (should be first)
        entry_node = next((n for n in nodes if n.get("nodeType") == "Entry"), None)
        if not entry_node:
            # If no Entry, use first node
            entry_node = nodes[0] if nodes else None
        
        # Find Response node (should be last)
        response_node = next((n for n in nodes if n.get("nodeType") == "Response"), None)
        
        # Get processing nodes (everything except Entry and Response)
        processing_nodes = [n for n in nodes if n.get("nodeType") not in ["Entry", "Response"]]
        
        # Build ordered node list: Entry -> processing nodes -> Response
        ordered_nodes = []
        if entry_node:
            ordered_nodes.append(entry_node)
        ordered_nodes.extend(processing_nodes)
        if response_node:
            ordered_nodes.append(response_node)
        
        if len(ordered_nodes) < 2:
            return connections
        
        # STEP 1: Create control flow connections (Next -> Start)
        # CRITICAL: Handle Switch node branches - LLM nodes should connect to Response nodes, not other LLM nodes
        
        # Build Switch branch mapping: {switch_node_id: {out_pin_id: [nodes_in_branch]}}
        switch_branches = {}
        node_to_branch = {}  # {node_id: (switch_node_id, out_pin_id)}
        
        # Find all Switch nodes and their branches
        for node in nodes:
            if node.get("nodeType") == "Switch":
                switch_id = node.get("id")
                switch_branches[switch_id] = {}
                for out_pin in node.get("pins", {}).get("next_pins", []):
                    out_pin_id = out_pin.get("id")
                    switch_branches[switch_id][out_pin_id] = []
        
        # Build branch membership from existing connections
        for conn in existing_connections:
            source_node_id = conn.get("source_node")
            source_pin_id = conn.get("source_pin")
            dest_node_id = conn.get("destination_node")
            
            source_node = node_lookup.get(source_node_id)
            if source_node and source_node.get("nodeType") == "Switch":
                for switch_id, branches in switch_branches.items():
                    if switch_id == source_node_id:
                        for out_pin_id, branch_nodes in branches.items():
                            if out_pin_id == source_pin_id:
                                if dest_node_id not in branch_nodes:
                                    branch_nodes.append(dest_node_id)
                                    node_to_branch[dest_node_id] = (switch_id, out_pin_id)
                                    # Recursively mark downstream nodes in this branch
                                    self._mark_branch_nodes(dest_node_id, switch_id, out_pin_id, 
                                                           node_to_branch, existing_connections, node_lookup)
        
        # Create control flow connections
        for i in range(len(ordered_nodes) - 1):
            current = ordered_nodes[i]
            next_node = ordered_nodes[i + 1]
            
            # STRICT RULE: Entry node can connect to ONLY ONE next node
            if current.get("nodeType") == "Entry" and entry_node_has_connection:
                print(f"Skipping auto-connection from Entry node '{current.get('label', 'Unknown')}' - Entry node already has a connection. Entry node can connect to ONLY ONE next node.")
                break  # Stop processing if Entry already has connection
            
            # STRICT RULE: Response nodes have NO outgoing connections
            if current.get("nodeType") == "Response":
                print(f"Skipping auto-connection from Response node '{current.get('label', 'Unknown')}' - Response nodes are terminal.")
                continue
            
            # CRITICAL RULE: Prevent LLM nodes from connecting to other LLM nodes
            # LLM nodes should connect to Response nodes, not to other LLM nodes
            if current.get("nodeType") == "LLM" and next_node.get("nodeType") == "LLM":
                print(f"Skipping auto-connection: LLM node '{current.get('label', 'Unknown')}' should connect to Response node, not to another LLM node '{next_node.get('label', 'Unknown')}'")
                continue
            
            # CRITICAL RULE: If current node is in a Switch branch, only connect to nodes in the same branch
            current_branch = node_to_branch.get(current.get("id"))
            next_branch = node_to_branch.get(next_node.get("id"))
            
            if current_branch and next_branch:
                # Both nodes are in branches - they must be in the same branch
                if current_branch != next_branch:
                    print(f"Skipping auto-connection: '{current.get('label', 'Unknown')}' and '{next_node.get('label', 'Unknown')}' are in different Switch branches. Branches must be isolated.")
                    continue
            
            # Find "Next" pin on current node
            current_next_pin = self._find_pin_id_by_name(current["pins"], "Next", ["next_pins"])
            # Find "Start" pin on next node
            next_start_pin = self._find_pin_id_by_name(next_node["pins"], "Start", ["trigger_pins"])
            
            if current_next_pin and next_start_pin:
                # STRICT RULE: Check if source pin already has a connection
                if current_next_pin in connected_pins_from_existing:
                    print(f"Skipping auto-connection: Source pin 'Next' on '{current.get('label', 'Unknown')}' already has a connection. Each pin can have ONLY ONE connection.")
                    continue
                
                # STRICT RULE: Check if destination pin already has a connection
                if next_start_pin in connected_pins_from_existing:
                    print(f"Skipping auto-connection: Destination pin 'Start' on '{next_node.get('label', 'Unknown')}' already has a connection. Each pin can have ONLY ONE connection.")
                    continue
                
                control_conn = {
                    "source_node": current["id"],
                    "source_pin": current_next_pin,
                    "destination_node": next_node["id"],
                    "destination_pin": next_start_pin
                }
                
                conn_key = (control_conn["source_node"], control_conn["source_pin"],
                           control_conn["destination_node"], control_conn["destination_pin"])
                if conn_key not in connection_set:
                    connection_set.add(conn_key)
                    connections.append(control_conn)
                    # Track pins as connected
                    connected_pins_from_existing.add(current_next_pin)
                    connected_pins_from_existing.add(next_start_pin)
                    # Track Entry node connection
                    if current.get("nodeType") == "Entry":
                        entry_node_has_connection = True
                    print(f"Auto-created CONTROL connection: {current.get('label', current.get('nodeType'))} -> {next_node.get('label', next_node.get('nodeType'))}")
        
        # STEP 2: Create data flow connections (output_pins -> input_pins)
        # Connect data outputs to data inputs in sequence
        # NOTE: Skip Global Data nodes - they manage history automatically and don't have input pins
        # NOTE: ToJson nodes have fixed input pins - allow connections to existing pins but don't auto-add new ones
        
        # Track which input pins are already connected (combine existing and new)
        connected_input_pins = connected_input_pins_from_existing.copy()
        # Track which Parameter Nodes already have connections (combine existing and new)
        connected_parameter_nodes = connected_parameter_nodes_from_existing.copy()
        
        for i in range(len(ordered_nodes) - 1):
            current = ordered_nodes[i]
            next_node = ordered_nodes[i + 1]
            
            # CRITICAL RULE: Prevent LLM nodes from connecting to other LLM nodes
            # LLM nodes should connect to Response nodes, not to other LLM nodes
            if current.get("nodeType") == "LLM" and next_node.get("nodeType") == "LLM":
                print(f"Skipping data connection: LLM node '{current.get('label', 'Unknown')}' should connect to Response node, not to another LLM node '{next_node.get('label', 'Unknown')}'")
                continue
            
            # CRITICAL RULE: If current node is in a Switch branch, only connect to nodes in the same branch
            current_branch = node_to_branch.get(current.get("id"))
            next_branch = node_to_branch.get(next_node.get("id"))
            
            if current_branch and next_branch:
                # Both nodes are in branches - they must be in the same branch
                if current_branch != next_branch:
                    print(f"Skipping data connection: '{current.get('label', 'Unknown')}' and '{next_node.get('label', 'Unknown')}' are in different Switch branches. Branches must be isolated.")
                    continue
            
            # Skip if destination is Global Data node (no input pins, manages history automatically)
            if next_node.get("nodeType") == "GlobalData":
                continue
            
            # RULE: Skip Parameter Nodes as destinations - they shouldn't receive connections
            if next_node.get("nodeType") == "Parameter":
                continue
            
            # RULE: Skip if source is Parameter Node and destination is also Parameter Node
            if current.get("nodeType") == "Parameter" and next_node.get("nodeType") == "Parameter":
                continue
            
            # RULE: Each Parameter Node connects to exactly ONE node. If its output pin is already
            # in connected_pins_from_existing, the loop below will skip (source pin already connected).
            
            # Get all output pins from current node
            current_output_pins = current.get("pins", {}).get("output_pins", [])
            # Get all input pins from next node
            next_input_pins = next_node.get("pins", {}).get("input_pins", [])
            
            # Try to match output pins to input pins by name
            matched_input_pins = set()
            
            for output_pin in current_output_pins:
                    output_pin_name = output_pin.get("name", "").lower()
                    output_pin_id = output_pin.get("id")
                    
                    # STRICT RULE: Check if source output pin already has a connection
                    if output_pin_id in connected_pins_from_existing:
                        continue  # Source pin already connected, skip
                    
                    # STRICT RULE: For LLM nodes, only connect Data input pin if there's actual data to pass
                    # Skip Data input pin connection if no meaningful data output exists
                    if next_node.get("nodeType") == "LLM":
                        # Check if this is a Data input pin
                        data_input_pin = next(
                            (pin for pin in next_input_pins if pin.get("name", "").lower() == "data"),
                            None
                        )
                        if data_input_pin:
                            # Only connect to Data input if:
                            # 1. Source has meaningful data output (not just control flow)
                            # 2. Source is not Entry node (Entry has no data)
                            # 3. Source is Parameter node (has data to pass)
                            # 4. Source has Response/Data/Output output pin
                            has_meaningful_data = (
                                current.get("nodeType") == "Parameter" or
                                output_pin_name in ["response", "data", "output", "text", "json"]
                            )
                            if not has_meaningful_data:
                                print(f"Skipping Data input pin connection to LLM node '{next_node.get('label', 'Unknown')}' - no meaningful data to pass from '{current.get('label', 'Unknown')}'")
                                continue  # Skip Data input pin connection
                    
                    best_match = None
                    best_match_score = 0
                    
                    for input_pin in next_input_pins:
                        if input_pin["id"] in matched_input_pins:
                            continue  # Skip already matched pins
                        
                        input_pin_name = input_pin.get("name", "").lower()
                        input_pin_id = input_pin.get("id")
                        
                        # STRICT RULE: Check if destination input pin already has a connection
                        if input_pin_id in connected_pins_from_existing:
                            continue  # Destination pin already connected, skip
                        
                        # RULE: Never connect to Chat History pins
                        if "chat history" in input_pin_name:
                            continue  # Skip Chat History pins
                        
                        # RULE: Check if input pin is already connected (backward compatibility)
                        if (next_node["id"], input_pin_id) in connected_input_pins:
                            continue  # Skip already connected input pins
                        
                        match_score = 0
                        
                        # Exact match (highest priority)
                        if output_pin_name == input_pin_name:
                            match_score = 100
                            best_match = input_pin
                            best_match_score = match_score
                            break  # Perfect match, use it immediately
                        
                        # Common patterns with scoring
                        if output_pin_name == "response" and input_pin_name in ["response", "data", "input"]:
                            match_score = 80 if input_pin_name == "response" else 60
                        elif output_pin_name == "chat history" and input_pin_name == "chat history":
                            match_score = 100
                        elif output_pin_name == "connection" and input_pin_name == "connection":
                            match_score = 100
                        elif output_pin_name == "metadata" and input_pin_name == "metadata":
                            match_score = 100
                        elif output_pin_name == "data" and input_pin_name in ["data", "input"]:
                            match_score = 80 if input_pin_name == "data" else 60
                        elif output_pin_name in ["output", "text", "json"] and input_pin_name in ["data", "input"]:
                            match_score = 50
                        
                        # Update best match if this is better
                        if match_score > best_match_score:
                            best_match = input_pin
                            best_match_score = match_score
                    
                    # If no match found but we have output pin, create input pin on destination node
                    # Skip this for Global Data and ToJson nodes (they have fixed input pins)
                    if not best_match or best_match_score == 0:
                        # Skip ToJson nodes - they have fixed input pins and should not get additional ones auto-added
                        if next_node.get("nodeType") == "ToJson":
                            continue
                        # RULE: Parameter nodes never have input pins. Do not add input pins to Parameter.
                        if next_node.get("nodeType") == "Parameter":
                            continue
                        
                        # Determine input pin name based on output pin name
                        input_pin_name = output_pin.get("name", "")
                        if output_pin_name == "response":
                            # Check if node already has "Response" input, otherwise use "Data"
                            has_response_input = any(
                                pin.get("name", "").lower() == "response" 
                                for pin in next_node.get("pins", {}).get("input_pins", [])
                            )
                            input_pin_name = "Response" if has_response_input else "Data"
                        elif output_pin_name in ["output", "text", "json"]:
                            input_pin_name = "Data"
                        
                        # Check if this input pin already exists
                        existing_input = next(
                            (pin for pin in next_node.get("pins", {}).get("input_pins", [])
                             if pin.get("name", "").lower() == input_pin_name.lower()),
                            None
                        )
                        
                        if existing_input:
                            # Check if existing input pin is already connected
                            existing_input_id = existing_input.get("id")
                            if (next_node["id"], existing_input_id) in connected_input_pins:
                                # Input pin already connected
                                # For Parameter Nodes, create a new unique input pin
                                if current.get("nodeType") == "Parameter":
                                    # Determine unique name based on parameter key
                                    param_config = current.get("configuration", {})
                                    param_key = param_config.get("Parameter Key") or param_config.get("Key") or param_config.get("parameter_key")
                                    if param_key:
                                        input_pin_name = param_key
                                    else:
                                        source_label = current.get("label", "")
                                        if "Parameter" in source_label:
                                            input_pin_name = source_label.split("(")[0].strip().lower().replace(" ", "_")
                                        else:
                                            input_pin_name = source_label.lower().replace(" ", "_") if source_label else output_pin.get("name", "")
                                    
                                    # Check if pin with this name already exists and is connected
                                    existing_with_new_name = next(
                                        (pin for pin in next_node.get("pins", {}).get("input_pins", [])
                                         if pin.get("name", "").lower() == input_pin_name.lower()),
                                        None
                                    )
                                    
                                    if existing_with_new_name:
                                        existing_new_id = existing_with_new_name.get("id")
                                        if (next_node["id"], existing_new_id) in connected_input_pins:
                                            # Already connected, skip this Parameter Node
                                            continue
                                        else:
                                            # Use existing pin that's not connected
                                            best_match = existing_with_new_name
                                            best_match_score = 50
                                    else:
                                        # Create new input pin with parameter-specific name
                                        new_input_pin = {
                                            "id": str(uuid.uuid4()),
                                            "name": input_pin_name,
                                            "editable": True
                                        }
                                        next_node["pins"]["input_pins"].append(new_input_pin)
                                        best_match = new_input_pin
                                        best_match_score = 50
                                        print(f"Auto-added unique input pin '{input_pin_name}' to node {next_node.get('label', next_node.get('nodeType'))} for Parameter Node '{current.get('label', 'Unknown')}'")
                                else:
                                    # Non-Parameter node - skip if pin is already connected
                                    continue
                            else:
                                # Existing pin is not connected - use it
                                best_match = existing_input
                                best_match_score = 50  # Use existing pin
                        else:
                            # Create new input pin (but not for Global Data or ToJson nodes)
                            new_input_pin = {
                                "id": str(uuid.uuid4()),
                                "name": input_pin_name,
                                "editable": True  # Mark as editable since it was auto-added
                            }
                            next_node["pins"]["input_pins"].append(new_input_pin)
                            best_match = new_input_pin
                            best_match_score = 50
                            print(f"Auto-added input pin '{input_pin_name}' to node {next_node.get('label', next_node.get('nodeType'))} for data connection from {current.get('label', current.get('nodeType'))}")
                    
                    # Connect if we found a match
                    if best_match and best_match_score > 0:
                        best_match_id = best_match.get("id")
                        
                        # STRICT RULE: Double-check that source pin is not already connected
                        if output_pin_id in connected_pins_from_existing:
                            continue  # Source pin already connected, skip
                        
                        # STRICT RULE: Double-check that destination pin is not already connected
                        if best_match_id in connected_pins_from_existing:
                            continue  # Destination pin already connected, skip
                        
                        # RULE: Double-check that input pin is not already connected (backward compatibility)
                        if (next_node["id"], best_match_id) in connected_input_pins:
                            continue  # Input pin already connected, skip
                        
                        # RULE: Each Parameter connects to exactly ONE node. output_pin_id in
                        # connected_pins_from_existing (checked above) blocks a second connection.
                        
                        data_conn = {
                            "source_node": current["id"],
                            "source_pin": output_pin_id,
                            "destination_node": next_node["id"],
                            "destination_pin": best_match_id
                        }
                        
                        conn_key = (data_conn["source_node"], data_conn["source_pin"],
                                   data_conn["destination_node"], data_conn["destination_pin"])
                        if conn_key not in connection_set:
                            connection_set.add(conn_key)
                            connections.append(data_conn)
                            matched_input_pins.add(best_match_id)
                            connected_input_pins.add((next_node["id"], best_match_id))
                            # Track pins as connected (output_pin check prevents Parameter from second connection)
                            connected_pins_from_existing.add(output_pin_id)
                            connected_pins_from_existing.add(best_match_id)
                            
                            print(f"Auto-created DATA connection: {current.get('label', current.get('nodeType'))} '{output_pin.get('name')}' -> {next_node.get('label', next_node.get('nodeType'))} '{best_match.get('name')}'")
        
        # STEP 3: Ensure LLM nodes connect to Response nodes with all required pins
        # CRITICAL: After Switch branches, LLM nodes should connect to Response nodes (not other LLM nodes)
        # Connect: LLM Next → Response Start, LLM Response → Response Response, LLM Chat History → Response Chat History
        connections = self._ensure_llm_to_response_connections(nodes, connections, node_to_branch, 
                                                               connected_pins_from_existing, connection_set)
        
        # STEP 4: Ensure ALL Response nodes have required connections from previous nodes
        # MANDATORY: Response nodes MUST always be connected to a previous node
        # Required connections: Previous Out/Next → Response Start, Previous Response/Output → Response Response Input
        connections = self._ensure_response_node_connections(nodes, connections, node_to_branch, 
                                                             connected_pins_from_existing, connection_set)
        
        return connections
    
    def _ensure_llm_to_response_connections(self, nodes: List[Dict], connections: List[Dict], 
                                            node_to_branch: Dict, connected_pins: set, connection_set: set) -> List[Dict]:
        """
        Ensure LLM nodes connect to Response nodes with all required pins:
        - LLM Next → Response Start (control flow)
        - LLM Response → Response Response (data flow)
        - LLM Chat History → Response Chat History (data flow)
        
        CRITICAL: LLM nodes should NOT connect to other LLM nodes.
        Each LLM node should connect to its corresponding Response node in the same branch.
        """
        node_lookup = {node["id"]: node for node in nodes}
        updated_connections = list(connections)
        
        # Find all LLM nodes
        llm_nodes = [node for node in nodes if node.get("nodeType") == "LLM"]
        
        for llm_node in llm_nodes:
            llm_node_id = llm_node.get("id")
            llm_branch = node_to_branch.get(llm_node_id)
            
            # Find Response node in the same branch
            # If LLM is in a branch, find Response node in same branch
            # Otherwise, find the next Response node after this LLM
            target_response_node = None
            
            if llm_branch:
                # Find Response node in the same branch
                for node in nodes:
                    node_branch = node_to_branch.get(node.get("id"))
                    if node.get("nodeType") == "Response" and node_branch == llm_branch:
                        target_response_node = node
                        break
            else:
                # Find next Response node after this LLM
                llm_index = next((i for i, n in enumerate(nodes) if n.get("id") == llm_node_id), -1)
                if llm_index >= 0:
                    for i in range(llm_index + 1, len(nodes)):
                        if nodes[i].get("nodeType") == "Response":
                            target_response_node = nodes[i]
                            break
            
            if not target_response_node:
                continue
            
            response_node_id = target_response_node.get("id")
            
            # Check if LLM already connects to a Response node
            llm_connects_to_response = any(
                c.get("source_node") == llm_node_id and 
                node_lookup.get(c.get("destination_node"), {}).get("nodeType") == "Response"
                for c in updated_connections
            )
            
            if llm_connects_to_response:
                # Check if it's connecting to the correct Response node
                existing_response_conn = next(
                    (c for c in updated_connections 
                     if c.get("source_node") == llm_node_id and 
                     node_lookup.get(c.get("destination_node"), {}).get("nodeType") == "Response"),
                    None
                )
                if existing_response_conn:
                    existing_response_id = existing_response_conn.get("destination_node")
                    if existing_response_id == response_node_id:
                        continue  # Already connected to correct Response node
            
            # Ensure LLM Next → Response Start connection
            llm_next_pin = self._find_pin_id_by_name(llm_node["pins"], "Next", ["next_pins"])
            response_start_pin = self._find_pin_id_by_name(target_response_node["pins"], "Start", ["trigger_pins"])
            
            if llm_next_pin and response_start_pin:
                # Check if pins are already connected
                if llm_next_pin not in connected_pins and response_start_pin not in connected_pins:
                    control_conn = {
                        "source_node": llm_node_id,
                        "source_pin": llm_next_pin,
                        "destination_node": response_node_id,
                        "destination_pin": response_start_pin
                    }
                    conn_key = (control_conn["source_node"], control_conn["source_pin"],
                               control_conn["destination_node"], control_conn["destination_pin"])
                    if conn_key not in connection_set:
                        updated_connections.append(control_conn)
                        connection_set.add(conn_key)
                        connected_pins.add(llm_next_pin)
                        connected_pins.add(response_start_pin)
                        print(f"Auto-connected LLM '{llm_node.get('label', 'Unknown')}' Next → Response '{target_response_node.get('label', 'Unknown')}' Start")
            
            # Ensure LLM Response → Response Response connection
            llm_response_pin = self._find_pin_id_by_name(llm_node["pins"], "Response", ["output_pins"])
            response_response_pin = self._find_pin_id_by_name(target_response_node["pins"], "Response", ["input_pins"])
            
            if llm_response_pin and response_response_pin:
                if llm_response_pin not in connected_pins and response_response_pin not in connected_pins:
                    data_conn = {
                        "source_node": llm_node_id,
                        "source_pin": llm_response_pin,
                        "destination_node": response_node_id,
                        "destination_pin": response_response_pin
                    }
                    conn_key = (data_conn["source_node"], data_conn["source_pin"],
                               data_conn["destination_node"], data_conn["destination_pin"])
                    if conn_key not in connection_set:
                        updated_connections.append(data_conn)
                        connection_set.add(conn_key)
                        connected_pins.add(llm_response_pin)
                        connected_pins.add(response_response_pin)
                        print(f"Auto-connected LLM '{llm_node.get('label', 'Unknown')}' Response → Response '{target_response_node.get('label', 'Unknown')}' Response")
            
            # Ensure LLM Chat History → Response Chat History connection
            llm_chat_history_pin = self._find_pin_id_by_name(llm_node["pins"], "Chat History", ["output_pins"])
            response_chat_history_pin = self._find_pin_id_by_name(target_response_node["pins"], "Chat History", ["input_pins"])
            
            if llm_chat_history_pin and response_chat_history_pin:
                if llm_chat_history_pin not in connected_pins and response_chat_history_pin not in connected_pins:
                    chat_conn = {
                        "source_node": llm_node_id,
                        "source_pin": llm_chat_history_pin,
                        "destination_node": response_node_id,
                        "destination_pin": response_chat_history_pin
                    }
                    conn_key = (chat_conn["source_node"], chat_conn["source_pin"],
                               chat_conn["destination_node"], chat_conn["destination_pin"])
                    if conn_key not in connection_set:
                        updated_connections.append(chat_conn)
                        connection_set.add(conn_key)
                        connected_pins.add(llm_chat_history_pin)
                        connected_pins.add(response_chat_history_pin)
                        print(f"Auto-connected LLM '{llm_node.get('label', 'Unknown')}' Chat History → Response '{target_response_node.get('label', 'Unknown')}' Chat History")
        
        return updated_connections
    
    def _ensure_response_node_connections(self, nodes: List[Dict], connections: List[Dict], 
                                          node_to_branch: Dict, connected_pins: set, connection_set: set) -> List[Dict]:
        """
        WORKFLOW CONNECTION RULES — RESPONSE NODE (GENERIC & MANDATORY)
        
        MANDATORY RULES:
        1. A Response Node MUST always be connected to a previous node.
        2. When a Response Node is added after ANY previous node, TWO connections are REQUIRED:
           A. CONTROL FLOW: Previous Node Out/Next/Output → Response Node Start (trigger pin)
           B. DATA FLOW: Previous Node Response/Output/Result → Response Node Response (input pin)
        3. If both have Chat History pins, connect them.
        4. These connections MUST be created automatically.
        
        CANONICAL PATTERN (ALWAYS ENFORCE):
        Previous Node
           ├─ Out / Next ─────────────▶ Response Node (Start)
           └─ Response / Output ──────▶ Response Node (Response Input)
        
        NEVER connect:
        - Response / Output pin → Response Node Start pin
        - Out / Next pin → Response Node Response input
        """
        node_lookup = {node["id"]: node for node in nodes}
        updated_connections = list(connections)
        
        # Find all Response nodes
        response_nodes = [node for node in nodes if node.get("nodeType") == "Response"]
        
        for response_node in response_nodes:
            response_node_id = response_node.get("id")
            response_branch = node_to_branch.get(response_node_id)
            
            # CRITICAL CHECK: Does this Response node have ANY incoming connections?
            has_any_incoming = any(
                conn.get("destination_node") == response_node_id 
                for conn in updated_connections
            )
            
            # If Response node has no incoming connections, we MUST find a previous node
            if not has_any_incoming:
                print(f"CRITICAL: Response node '{response_node.get('label', 'Unknown')}' has NO incoming connections. MUST find and connect previous node.")
            
            # Find the previous node that should connect to this Response node
            # Priority: Look for nodes in the same branch, then look backwards in node order
            target_previous_node = None
            
            # Strategy 1: Find previous node in the same branch (most reliable for Switch branches)
            response_index = next((i for i, n in enumerate(nodes) if n.get("id") == response_node_id), -1)
            
            if response_branch:
                if response_index > 0:
                    resp_kw = self._branch_keyword(response_node.get("label") or response_node.get("name") or "")
                    # Look backwards in the same branch; skip nodes whose Next pin is already used (wrong Handler-Response pair)
                    for i in range(response_index - 1, -1, -1):
                        node = nodes[i]
                        node_branch = node_to_branch.get(node.get("id"))
                        if node_branch != response_branch or node.get("nodeType") in ["Entry", "Parameter", "Switch", "Response"]:
                            continue
                        next_pin = self._find_pin_id_by_name(node.get("pins", {}), "Next", ["next_pins"])
                        if self._is_next_used_for_other_response(updated_connections, node.get("id"), next_pin, response_node_id):
                            continue  # Next already used for another Response
                        # Prefer name match when multiple same-branch nodes (e.g. Handler vs non-LLM)
                        node_kw = self._branch_keyword(node.get("label") or node.get("name") or "")
                        if resp_kw and node_kw and resp_kw.lower() != node_kw.lower():
                            continue  # Same branch but wrong Handler (e.g. Other Handler vs Complex Response)
                        target_previous_node = node
                        print(f"Found previous node '{target_previous_node.get('label', 'Unknown')}' in same branch for Response '{response_node.get('label', 'Unknown')}'")
                        break
                    
                    # Strategy 1b: If no node found in branch, look for nodes connected to Switch out pins in this branch only
                    if not target_previous_node:
                        switch_id, out_pin_id = response_branch
                        switch_node = node_lookup.get(switch_id)
                        if switch_node:
                            for conn in updated_connections:
                                if (conn.get("source_node") != switch_id or conn.get("source_pin") != out_pin_id):
                                    continue
                                connected_node_id = conn.get("destination_node")
                                connected_node = node_lookup.get(connected_node_id)
                                if not connected_node or connected_node.get("nodeType") in ["Entry", "Parameter", "Switch", "Response"]:
                                    continue
                                if node_to_branch.get(connected_node_id) != response_branch:
                                    continue
                                next_pin = self._find_pin_id_by_name(connected_node.get("pins", {}), "Next", ["next_pins"])
                                if self._is_next_used_for_other_response(updated_connections, connected_node_id, next_pin, response_node_id):
                                    continue
                                # Prefer Handler-Response name match (avoid wrong branch assignment)
                                node_kw = self._branch_keyword(connected_node.get("label") or connected_node.get("name") or "")
                                if resp_kw and node_kw and resp_kw.lower() != node_kw.lower():
                                    continue
                                idx = next((i for i, n in enumerate(nodes) if n.get("id") == connected_node_id), -1)
                                if 0 <= idx < response_index:
                                    target_previous_node = connected_node
                                    print(f"Found previous node '{target_previous_node.get('label', 'Unknown')}' from Switch out pin for Response '{response_node.get('label', 'Unknown')}'")
                                    break
            
            # Strategy 2: If no branch match, find previous node before this Response (comprehensive search)
            # CRITICAL: Skip nodes whose Next pin is already used; prefer Handler-Response name match to avoid
            # connecting e.g. Other Handler → Complex Response (which would leave Other Response unconnected)
            if not target_previous_node and response_index > 0:
                resp_kw = self._branch_keyword(response_node.get("label") or response_node.get("name") or "")
                candidates = []  # (node, is_llm, name_match)
                for i in range(response_index - 1, -1, -1):
                    node = nodes[i]
                    node_type = node.get("nodeType")
                    if node_type in ["Entry", "Parameter", "Switch", "Response"]:
                        continue
                    if response_branch and node_to_branch.get(node.get("id")) != response_branch:
                        continue  # Only same-branch when response is in a branch
                    next_pin = self._find_pin_id_by_name(node.get("pins", {}), "Next", ["next_pins"])
                    if self._is_next_used_for_other_response(updated_connections, node.get("id"), next_pin, response_node_id):
                        continue  # Next already used for another Response
                    node_kw = self._branch_keyword(node.get("label") or node.get("name") or "")
                    match = bool(resp_kw and node_kw and resp_kw.lower() == node_kw.lower())
                    candidates.append((node, node_type == "LLM", match))
                # Prefer: name match, then LLM; take first
                candidates.sort(key=lambda c: (not c[2], not c[1]))
                if candidates:
                    target_previous_node = candidates[0][0]
                    print(f"Found LLM/node '{target_previous_node.get('label', 'Unknown')}' before Response '{response_node.get('label', 'Unknown')}'")
                
                # If no LLM/processing with free Next, accept any processing node (skip Next-in-use)
                if not target_previous_node:
                    for i in range(response_index - 1, -1, -1):
                        node = nodes[i]
                        if node.get("nodeType") not in ["Entry", "Parameter", "Switch", "Response", "GlobalData"]:
                            if response_branch and node_to_branch.get(node.get("id")) != response_branch:
                                continue
                            next_pin = self._find_pin_id_by_name(node.get("pins", {}), "Next", ["next_pins"])
                            if self._is_next_used_for_other_response(updated_connections, node.get("id"), next_pin, response_node_id):
                                continue
                            target_previous_node = node
                            print(f"Found processing node '{target_previous_node.get('label', 'Unknown')}' before Response '{response_node.get('label', 'Unknown')}'")
                            break
                
                # Strategy 2b: If still no node found, check connections to find what connects to this Response
                if not target_previous_node:
                    for conn in updated_connections:
                        if conn.get("destination_node") != response_node_id:
                            continue
                        source_node_id = conn.get("source_node")
                        source_node = node_lookup.get(source_node_id)
                        if not source_node or source_node.get("nodeType") in ["Entry", "Parameter", "Switch", "Response"]:
                            continue
                        if response_branch and node_to_branch.get(source_node_id) != response_branch:
                            continue
                        next_pin = self._find_pin_id_by_name(source_node.get("pins", {}), "Next", ["next_pins"])
                        if self._is_next_used_for_other_response(updated_connections, source_node_id, next_pin, response_node_id):
                            continue
                        source_index = next((i for i, n in enumerate(nodes) if n.get("id") == source_node_id), -1)
                        if 0 <= source_index < response_index:
                            target_previous_node = source_node
                            print(f"Found source node '{target_previous_node.get('label', 'Unknown')}' from existing connection for Response '{response_node.get('label', 'Unknown')}'")
                            break
            
            # Strategy 3: Last resort - find ANY node before Response that can connect
            if not target_previous_node and response_index > 0:
                for i in range(response_index - 1, -1, -1):
                    node = nodes[i]
                    if node.get("nodeType") not in ["Entry", "Parameter", "Switch", "Response", "GlobalData"]:
                        if response_branch and node_to_branch.get(node.get("id")) != response_branch:
                            continue
                        next_pin = self._find_pin_id_by_name(node.get("pins", {}), "Next", ["next_pins"])
                        if self._is_next_used_for_other_response(updated_connections, node.get("id"), next_pin, response_node_id):
                            continue
                        target_previous_node = node
                        print(f"Found ANY node '{target_previous_node.get('label', 'Unknown')}' before Response '{response_node.get('label', 'Unknown')}' (last resort)")
                        break
            
            # Strategy 4: ULTIMATE FALLBACK - find ANY node before Response (even Switch/Parameter)
            if not target_previous_node and response_index > 0:
                for i in range(response_index - 1, -1, -1):
                    node = nodes[i]
                    if node.get("nodeType") not in ["Entry", "Response"]:
                        if response_branch and node_to_branch.get(node.get("id")) != response_branch:
                            continue
                        next_pin = self._find_pin_id_by_name(node.get("pins", {}), "Next", ["next_pins"])
                        if self._is_next_used_for_other_response(updated_connections, node.get("id"), next_pin, response_node_id):
                            continue
                        target_previous_node = node
                        print(f"ULTIMATE FALLBACK: Using '{target_previous_node.get('label', 'Unknown')}' ({target_previous_node.get('nodeType')}) as previous node for Response '{response_node.get('label', 'Unknown')}'")
                        break
            
            # CRITICAL: If still no previous node found, try label-based match then immediate previous
            if not target_previous_node:
                print(f"CRITICAL ERROR: Cannot find ANY previous node for Response '{response_node.get('label', 'Unknown')}'. This Response node will be unreachable.")
                resp_kw = self._branch_keyword(response_node.get("label") or response_node.get("name") or "")
                # EMERGENCY: label-based search for a Handler matching this Response (Option A Handler for Response for Option A, etc.)
                for i, n in enumerate(nodes):
                    if i >= response_index or n.get("nodeType") in ["Entry", "Parameter", "Switch", "Response"]:
                        continue
                    node_kw = self._branch_keyword(n.get("label") or n.get("name") or "")
                    if resp_kw and node_kw and resp_kw.lower() != node_kw.lower():
                        continue
                    next_pin = self._find_pin_id_by_name(n.get("pins", {}), "Next", ["next_pins"])
                    if self._is_next_used_for_other_response(updated_connections, n.get("id"), next_pin, response_node_id):
                        continue
                    target_previous_node = n
                    print(f"EMERGENCY FALLBACK: Using label-matched node '{target_previous_node.get('label', 'Unknown')}' for Response '{response_node.get('label', 'Unknown')}'")
                    break
                # Last resort: immediate previous in array (only if its Next is not used for another Response)
                if not target_previous_node and response_index > 0:
                    prev_node = nodes[response_index - 1]
                    if prev_node.get("nodeType") != "Response":
                        np = self._find_pin_id_by_name(prev_node.get("pins", {}), "Next", ["next_pins"])
                        if not self._is_next_used_for_other_response(updated_connections, prev_node.get("id"), np, response_node_id):
                            target_previous_node = prev_node
                            print(f"EMERGENCY FALLBACK: Using immediate previous node '{target_previous_node.get('label', 'Unknown')}' for Response '{response_node.get('label', 'Unknown')}'")
                
                if not target_previous_node:
                    # Try to add DATA FLOW from any incoming source that has Response/Output/Result (may have control from Switch etc.)
                    for conn in updated_connections:
                        if conn.get("destination_node") != response_node_id:
                            continue
                        src_id = conn.get("source_node")
                        src = node_lookup.get(src_id)
                        if not src or src.get("nodeType") in {"Entry", "Parameter", "Switch", "Response", "GlobalData"}:
                            continue
                        prev_resp_pin = None
                        for pname in ["Response", "Output", "Result"]:
                            prev_resp_pin = self._find_pin_id_by_name(src.get("pins", {}), pname, ["output_pins"])
                            if prev_resp_pin:
                                break
                        if not prev_resp_pin:
                            continue
                        resp_in = self._find_pin_id_by_name(response_node.get("pins", {}), "Response", ["input_pins"])
                        if not resp_in:
                            if "pins" not in response_node or response_node["pins"] is None:
                                response_node["pins"] = {}
                            rp = response_node["pins"]
                            if "input_pins" not in rp:
                                rp["input_pins"] = []
                            new_in = {"id": str(uuid.uuid4()), "name": "Response"}
                            rp["input_pins"].append(new_in)
                            resp_in = new_in["id"]
                        if prev_resp_pin in connected_pins or resp_in in connected_pins:
                            continue
                        ck = (src_id, prev_resp_pin, response_node_id, resp_in)
                        if ck in connection_set:
                            continue
                        data_conn = {"source_node": src_id, "source_pin": prev_resp_pin, "destination_node": response_node_id, "destination_pin": resp_in}
                        updated_connections.append(data_conn)
                        connection_set.add(ck)
                        connected_pins.add(prev_resp_pin)
                        connected_pins.add(resp_in)
                        print(f"ABANDON path: Added DATA FLOW from '{src.get('label','Unknown')}' to Response '{response_node.get('label','Unknown')}'")
                    print(f"ABANDONING: Response node '{response_node.get('label', 'Unknown')}' cannot be connected. Skipping.")
                    continue
            
            previous_node_id = target_previous_node.get("id")
            
            # Check if previous node already connects to this Response node
            has_control_flow = False
            has_data_flow = False
            
            for conn in updated_connections:
                if conn.get("source_node") == previous_node_id and conn.get("destination_node") == response_node_id:
                    # Check connection type
                    source_pin_name = self._get_pin_name_by_id(nodes, previous_node_id, conn.get("source_pin"))
                    dest_pin_name = self._get_pin_name_by_id(nodes, response_node_id, conn.get("destination_pin"))
                    
                    if source_pin_name and dest_pin_name:
                        source_lower = source_pin_name.lower()
                        dest_lower = dest_pin_name.lower()
                        
                        # Check if this is a control flow connection (Out/Next → Start)
                        if source_lower in ["next", "out", "output"] and dest_lower == "start":
                            has_control_flow = True
                        # Check if this is a data flow connection (Response/Output → Response Input)
                        elif source_lower in ["response", "output", "result"] and dest_lower == "response":
                            has_data_flow = True
            
            # REQUIRED CONNECTION 1: CONTROL FLOW - Previous Node Out/Next → Response Start
            if not has_control_flow:
                # Find Out/Next/Output pin on previous node (from next_pins collection)
                previous_next_pin = None
                pin_name_used = None
                for pin_name in ["Next", "Out", "Output"]:
                    previous_next_pin = self._find_pin_id_by_name(target_previous_node["pins"], pin_name, ["next_pins"])
                    if previous_next_pin:
                        pin_name_used = pin_name
                        break
                
                # If no Next/Out pin found, try to add one
                # RULE: Parameter nodes never have next_pins (out pins). Do NOT add or create out pins on Parameter.
                if not previous_next_pin and target_previous_node.get("nodeType") != "Parameter":
                    # Ensure next_pins collection exists
                    if "next_pins" not in target_previous_node["pins"]:
                        target_previous_node["pins"]["next_pins"] = []
                    
                    # Add a "Next" pin
                    previous_next_pin = str(uuid.uuid4())
                    new_next_pin = {
                        "id": previous_next_pin,
                        "name": "Next",
                        "editable": True
                    }
                    target_previous_node["pins"]["next_pins"].append(new_next_pin)
                    pin_name_used = "Next"
                    print(f"Auto-added Next pin to '{target_previous_node.get('label', 'Unknown')}' for Response connection")
                
                response_start_pin = self._find_pin_id_by_name(response_node["pins"], "Start", ["trigger_pins"])
                
                # If Response node has no Start pin, add one
                if not response_start_pin:
                    # Ensure trigger_pins collection exists
                    if "trigger_pins" not in response_node["pins"]:
                        response_node["pins"]["trigger_pins"] = []
                    
                    # Add a "Start" pin
                    response_start_pin = str(uuid.uuid4())
                    new_start_pin = {
                        "id": response_start_pin,
                        "name": "Start",
                        "editable": True
                    }
                    response_node["pins"]["trigger_pins"].append(new_start_pin)
                    print(f"Auto-added Start pin to Response '{response_node.get('label', 'Unknown')}'")
                
                if previous_next_pin and response_start_pin:
                    # Check if pins are already connected
                    if previous_next_pin not in connected_pins and response_start_pin not in connected_pins:
                        conn_key = (previous_node_id, previous_next_pin, response_node_id, response_start_pin)
                        if conn_key not in connection_set:
                            control_conn = {
                                "source_node": previous_node_id,
                                "source_pin": previous_next_pin,
                                "destination_node": response_node_id,
                                "destination_pin": response_start_pin
                            }
                            updated_connections.append(control_conn)
                            connection_set.add(conn_key)
                            connected_pins.add(previous_next_pin)
                            connected_pins.add(response_start_pin)
                            print(f"MANDATORY: Auto-connected '{target_previous_node.get('label', 'Unknown')}' {pin_name_used} → Response '{response_node.get('label', 'Unknown')}' Start (CONTROL FLOW)")
                    else:
                        print(f"WARNING: Cannot connect - pins already in use. Previous Next pin connected: {previous_next_pin in connected_pins}, Response Start pin connected: {response_start_pin in connected_pins}")
                else:
                    print(f"CRITICAL ERROR: Cannot create control flow connection - Previous Next pin: {previous_next_pin}, Response Start pin: {response_start_pin}")
            
            # REQUIRED CONNECTION 2: DATA FLOW - Previous Node Response/Output/Result → Response Response Input
            # Data source may differ from target_previous_node (control source); e.g. Switch triggers Response but Handler provides data.
            if not has_data_flow:
                data_source_node = target_previous_node
                data_source_node_id = previous_node_id  # default: same as control-flow previous
                prev_pins = data_source_node.get("pins", {})
                previous_response_pin = None
                pin_name_used = None
                for pin_name in ["Response", "Output", "Result"]:
                    previous_response_pin = self._find_pin_id_by_name(prev_pins, pin_name, ["output_pins"])
                    if previous_response_pin:
                        pin_name_used = pin_name
                        break
                
                # If control-flow previous has no data pin: try any other incoming connection source that has Response/Output/Result
                if not previous_response_pin:
                    for conn in updated_connections:
                        if conn.get("destination_node") != response_node_id:
                            continue
                        src_id = conn.get("source_node")
                        if src_id == previous_node_id:
                            continue
                        src_node = node_lookup.get(src_id)
                        if not src_node or src_node.get("nodeType") in {"Entry", "Parameter", "Switch", "Response", "GlobalData"}:
                            continue
                        sp = src_node.get("pins", {})
                        for pname in ["Response", "Output", "Result"]:
                            pid = self._find_pin_id_by_name(sp, pname, ["output_pins"])
                            if pid:
                                data_source_node = src_node
                                data_source_node_id = src_id
                                previous_response_pin = pid
                                pin_name_used = pname
                                break
                        if previous_response_pin:
                            break
                
                # If still not found: add "Response" output pin to processing nodes (exclude Entry, Parameter, Switch, Response, GlobalData)
                if not previous_response_pin and data_source_node.get("nodeType") not in {"Entry", "Parameter", "Switch", "Response", "GlobalData"}:
                    if "pins" not in data_source_node or data_source_node["pins"] is None:
                        data_source_node["pins"] = {}
                    pins = data_source_node["pins"]
                    if "output_pins" not in pins:
                        pins["output_pins"] = []
                    new_out = {"id": str(uuid.uuid4()), "name": "Response"}
                    pins["output_pins"].append(new_out)
                    previous_response_pin = new_out["id"]
                    pin_name_used = "Response"
                    data_source_node_id = data_source_node.get("id")
                    print(f"Auto-added Response output pin to '{data_source_node.get('label', 'Unknown')}' for Response node data flow")
                
                resp_pins = response_node.get("pins", {})
                response_response_pin = self._find_pin_id_by_name(resp_pins, "Response", ["input_pins"])
                
                # If Response node has no Response input pin, add it
                if not response_response_pin:
                    if "pins" not in response_node or response_node["pins"] is None:
                        response_node["pins"] = {}
                    rpins = response_node["pins"]
                    if "input_pins" not in rpins:
                        rpins["input_pins"] = []
                    new_in = {"id": str(uuid.uuid4()), "name": "Response"}
                    rpins["input_pins"].append(new_in)
                    response_response_pin = new_in["id"]
                    print(f"Auto-added Response input pin to Response node '{response_node.get('label', 'Unknown')}'")
                
                if previous_response_pin and response_response_pin:
                    if previous_response_pin not in connected_pins and response_response_pin not in connected_pins:
                        conn_key = (data_source_node_id, previous_response_pin, response_node_id, response_response_pin)
                        if conn_key not in connection_set:
                            data_conn = {
                                "source_node": data_source_node_id,
                                "source_pin": previous_response_pin,
                                "destination_node": response_node_id,
                                "destination_pin": response_response_pin
                            }
                            updated_connections.append(data_conn)
                            connection_set.add(conn_key)
                            connected_pins.add(previous_response_pin)
                            connected_pins.add(response_response_pin)
                            print(f"MANDATORY: Auto-connected '{data_source_node.get('label', 'Unknown')}' {pin_name_used} → Response '{response_node.get('label', 'Unknown')}' Response (DATA FLOW)")
                elif not previous_response_pin:
                    print(f"WARNING: No node with Response/Output/Result found for Response '{response_node.get('label', 'Unknown')}' (control from {target_previous_node.get('label', 'Unknown')}, nodeType={target_previous_node.get('nodeType')})")
            
            # OPTIONAL CONNECTION 3: Chat History - Previous Node Chat History → Response Chat History
            previous_chat_history_pin = self._find_pin_id_by_name(target_previous_node.get("pins", {}), "Chat History", ["output_pins"])
            response_chat_history_pin = self._find_pin_id_by_name(response_node.get("pins", {}), "Chat History", ["input_pins"])
            
            if previous_chat_history_pin and response_chat_history_pin:
                # Check if already connected
                already_connected = any(
                    c.get("source_node") == previous_node_id and 
                    c.get("destination_node") == response_node_id and
                    c.get("source_pin") == previous_chat_history_pin and
                    c.get("destination_pin") == response_chat_history_pin
                    for c in updated_connections
                )
                
                if not already_connected:
                    if previous_chat_history_pin not in connected_pins and response_chat_history_pin not in connected_pins:
                        conn_key = (previous_node_id, previous_chat_history_pin, response_node_id, response_chat_history_pin)
                        if conn_key not in connection_set:
                            chat_conn = {
                                "source_node": previous_node_id,
                                "source_pin": previous_chat_history_pin,
                                "destination_node": response_node_id,
                                "destination_pin": response_chat_history_pin
                            }
                            updated_connections.append(chat_conn)
                            connection_set.add(conn_key)
                            connected_pins.add(previous_chat_history_pin)
                            connected_pins.add(response_chat_history_pin)
                            print(f"Auto-connected '{target_previous_node.get('label', 'Unknown')}' Chat History → Response '{response_node.get('label', 'Unknown')}' Chat History")
        
        return updated_connections
    
    def _find_pin_id_by_name(self, pins_dict: Dict, pin_name: str, pin_collections: List[str]) -> Optional[str]:
        """Find pin ID by name in pin collections"""
        for collection in pin_collections:
            for pin in pins_dict.get(collection, []):
                if pin.get("name", "").lower() == pin_name.lower():
                    return pin.get("id")
        return None
    
    def _validate_and_repair_connections(self, nodes: List[Dict], connections: List[Dict]) -> List[Dict]:
        """
        Validate and repair connections to ensure workflow integrity.
        Based on template_generator.py logic.
        """
        print("Validating and repairing connections...")
        
        # Step 1: Remove invalid connections
        valid_connections = []
        node_dict = {node["id"]: node for node in nodes}
        
        control_pins = {"next", "start", "iterate", "default", "finished"}
        data_pins = {"response", "connection", "data", "output", "metadata", 
                    "chat history", "text", "json", "input", "value", "index", 
                    "responses", "filter", "key"}
        
        # STRICT RULE: Track ALL pins to enforce one-connection-per-pin
        connected_pins = set()  # {pin_id}
        entry_node_connections = []  # Track Entry node connections
        
        for conn in connections:
            source_node_id = conn.get("source_node")
            dest_node_id = conn.get("destination_node")
            source_pin_id = conn.get("source_pin")
            dest_pin_id = conn.get("destination_pin")
            
            # Validate nodes exist
            if source_node_id not in node_dict or dest_node_id not in node_dict:
                print(f"WARNING: Removing connection with invalid node references")
                continue
            
            source_node = node_dict[source_node_id]
            dest_node = node_dict[dest_node_id]
            
            # STRICT RULE: Response nodes have NO outgoing connections
            if source_node.get("nodeType") == "Response":
                print(f"WARNING: Removing connection from terminal Response node '{source_node.get('label', 'Unknown')}' - Response nodes cannot have outgoing connections")
                continue
            
            # Get pin names to validate connection type
            source_pin_name = self._get_pin_name_by_id(nodes, source_node_id, source_pin_id)
            dest_pin_name = self._get_pin_name_by_id(nodes, dest_node_id, dest_pin_id)
            
            if not source_pin_name or not dest_pin_name:
                print(f"WARNING: Removing connection with invalid pin references")
                continue
            
            # STRICT RULE: Check if source pin already has a connection
            if source_pin_id in connected_pins:
                print(f"WARNING: Removing duplicate connection - source pin '{source_pin_name}' on '{source_node.get('label', 'Unknown')}' already has a connection. Each pin can have ONLY ONE connection.")
                continue
            
            # STRICT RULE: Check if destination pin already has a connection
            if dest_pin_id in connected_pins:
                print(f"WARNING: Removing duplicate connection - destination pin '{dest_pin_name}' on '{dest_node.get('label', 'Unknown')}' already has a connection. Each pin can have ONLY ONE connection.")
                continue
            
            # STRICT RULE: Entry node can connect to ONLY ONE next node
            if source_node.get("nodeType") == "Entry":
                if len(entry_node_connections) > 0:
                    print(f"WARNING: Removing duplicate connection from Entry node '{source_node.get('label', 'Unknown')}' - Entry node can connect to ONLY ONE next node")
                    continue
                entry_node_connections.append(conn)
            
            # Validate connection type (control to control, data to data)
            source_is_control = source_pin_name.lower() in control_pins
            dest_is_control = dest_pin_name.lower() in control_pins
            
            if source_is_control != dest_is_control:
                print(f"WARNING: Removing invalid connection type - {source_pin_name} ({'control' if source_is_control else 'data'}) → {dest_pin_name} ({'control' if dest_is_control else 'data'})")
                continue
            
            # Validate pin types match (output to input for data, next to trigger for control)
            if source_is_control:
                # Control: next_pins → trigger_pins
                source_in_next = self._find_pin_id_by_name(source_node["pins"], source_pin_name, ["next_pins"]) == source_pin_id
                dest_in_trigger = self._find_pin_id_by_name(dest_node["pins"], dest_pin_name, ["trigger_pins"]) == dest_pin_id
                if not (source_in_next and dest_in_trigger):
                    print(f"WARNING: Removing invalid control connection - pin types don't match")
                    continue
            else:
                # Data: output_pins → input_pins
                source_in_output = self._find_pin_id_by_name(source_node["pins"], source_pin_name, ["output_pins"]) == source_pin_id
                dest_in_input = self._find_pin_id_by_name(dest_node["pins"], dest_pin_name, ["input_pins"]) == dest_pin_id
                if not (source_in_output and dest_in_input):
                    print(f"WARNING: Removing invalid data connection - pin types don't match")
                    continue
            
            # Track pins as connected
            connected_pins.add(source_pin_id)
            connected_pins.add(dest_pin_id)
            
            valid_connections.append(conn)
        
        print(f"After validation: {len(valid_connections)} valid connections (removed {len(connections) - len(valid_connections)} invalid)")
        
        # Step 2: Check for missing control flow connections and add them
        existing_control_conns = {
            (c.get("source_node"), c.get("destination_node"))
            for c in valid_connections
            if self._get_pin_name_by_id(nodes, c.get("source_node"), c.get("source_pin")).lower() in control_pins
        }
        
        # Build ordered node list
        entry_node = next((n for n in nodes if n.get("nodeType") == "Entry"), None)
        response_node = next((n for n in nodes if n.get("nodeType") == "Response"), None)
        processing_nodes = [n for n in nodes if n.get("nodeType") not in ["Entry", "Response"]]
        
        ordered_nodes = []
        if entry_node:
            ordered_nodes.append(entry_node)
        ordered_nodes.extend(processing_nodes)
        if response_node:
            ordered_nodes.append(response_node)
        
        if len(ordered_nodes) > 1:
            # Add missing control flow connections
            for i in range(len(ordered_nodes) - 1):
                current = ordered_nodes[i]
                next_node = ordered_nodes[i + 1]
                
                # STRICT RULE: Response nodes have NO outgoing connections
                if current.get("nodeType") == "Response":
                    print(f"Skipping repair: Response node '{current.get('label', 'Unknown')}' cannot have outgoing connections")
                    continue
                
                # STRICT RULE: Entry node can connect to ONLY ONE next node
                if current.get("nodeType") == "Entry":
                    entry_has_conn = any(
                        c.get("source_node") == current["id"]
                        for c in valid_connections
                    )
                    if entry_has_conn:
                        print(f"Skipping repair: Entry node '{current.get('label', 'Unknown')}' already has a connection. Entry node can connect to ONLY ONE next node.")
                        continue
                
                conn_key = (current["id"], next_node["id"])
                if conn_key not in existing_control_conns:
                    current_next_pin = self._find_pin_id_by_name(current["pins"], "Next", ["next_pins"])
                    next_start_pin = self._find_pin_id_by_name(next_node["pins"], "Start", ["trigger_pins"])
                    
                    if current_next_pin and next_start_pin:
                        # STRICT RULE: Check if source pin already has a connection
                        if current_next_pin in connected_pins:
                            print(f"Skipping repair: Source pin 'Next' on '{current.get('label', 'Unknown')}' already has a connection")
                            continue
                        
                        # STRICT RULE: Check if destination pin already has a connection
                        if next_start_pin in connected_pins:
                            print(f"Skipping repair: Destination pin 'Start' on '{next_node.get('label', 'Unknown')}' already has a connection")
                            continue
                        
                        # Check if this exact connection already exists
                        existing_exact = any(
                            c.get("source_node") == current["id"] and
                            c.get("destination_node") == next_node["id"] and
                            c.get("source_pin") == current_next_pin and
                            c.get("destination_pin") == next_start_pin
                            for c in valid_connections
                        )
                        
                        if not existing_exact:
                            valid_connections.append({
                                "source_node": current["id"],
                                "source_pin": current_next_pin,
                                "destination_node": next_node["id"],
                                "destination_pin": next_start_pin
                            })
                            connected_pins.add(current_next_pin)
                            connected_pins.add(next_start_pin)
                            print(f"Repaired: Added missing control flow connection {current.get('label', current.get('nodeType'))} → {next_node.get('label', next_node.get('nodeType'))}")
        
        # Step 3: Add missing data flow connections where logical
        # NOTE: Skip Global Data nodes - they manage history automatically and don't have input pins
        # NOTE: Skip ToJson nodes - they have fixed input pins and should not get additional ones auto-added
        # RULE: Skip Parameter Nodes as destinations - they shouldn't receive connections
        if ordered_nodes and len(ordered_nodes) > 1:
            existing_data_conns = {
                (c.get("source_node"), c.get("destination_node"), c.get("source_pin"), c.get("destination_pin"))
                for c in valid_connections
                if self._get_pin_name_by_id(nodes, c.get("source_node"), c.get("source_pin")).lower() not in control_pins
            }
            
            # Track which input pins are already connected
            connected_input_pins = set()  # {(dest_node_id, input_pin_id)}
            # Track which Parameter Nodes already have connections (each Parameter Node can only connect once)
            connected_parameter_nodes = set()  # {parameter_node_id}
            
            for conn in valid_connections:
                dest_node_id = conn.get("destination_node")
                dest_pin_id = conn.get("destination_pin")
                source_node_id = conn.get("source_node")
                
                if dest_node_id and dest_pin_id:
                    dest_node = node_dict.get(dest_node_id)
                    if dest_node:
                        for pin in dest_node.get("pins", {}).get("input_pins", []):
                            if pin.get("id") == dest_pin_id:
                                connected_input_pins.add((dest_node_id, dest_pin_id))
                                break
                
                # Track Parameter Nodes that already have connections
                if source_node_id:
                    source_node = node_dict.get(source_node_id)
                    if source_node and source_node.get("nodeType") == "Parameter":
                        connected_parameter_nodes.add(source_node_id)
            
            # Add data flow connections in sequence
            for i in range(len(ordered_nodes) - 1):
                current = ordered_nodes[i]
                next_node = ordered_nodes[i + 1]
                
                # Skip if destination is Global Data node (no input pins, manages history automatically)
                if next_node.get("nodeType") == "GlobalData":
                    continue
                
                # RULE: Skip Parameter Nodes as destinations - they shouldn't receive connections
                if next_node.get("nodeType") == "Parameter":
                    continue
                
                # RULE: Skip if source is Parameter Node and destination is also Parameter Node
                # Parameter Nodes should not connect to other Parameter Nodes
                if current.get("nodeType") == "Parameter" and next_node.get("nodeType") == "Parameter":
                    continue
                
                # RULE: If source is a Parameter Node and it already has a connection, skip it
                # Each Parameter Node can only connect to ONE input pin
                if current.get("nodeType") == "Parameter":
                    if current.get("id") in connected_parameter_nodes:
                        continue  # This Parameter Node already has a connection, skip it
                
                # Get output pins from current node
                current_output_pins = current.get("pins", {}).get("output_pins", [])
                next_input_pins = next_node.get("pins", {}).get("input_pins", [])
                
                # Check if destination is ToJson - allow connections to existing pins but don't add new ones
                is_tojson = next_node.get("nodeType") == "ToJson"
                is_parameter_source = current.get("nodeType") == "Parameter"
                
                for output_pin in current_output_pins:
                    output_pin_name = output_pin.get("name", "").lower()
                    output_pin_id = output_pin.get("id")
                    
                    # For Parameter Nodes, determine the input pin name from parameter key
                    if is_parameter_source:
                        param_config = current.get("configuration", {})
                        param_key = param_config.get("Parameter Key") or param_config.get("Key") or param_config.get("parameter_key")
                        if param_key:
                            desired_input_pin_name = param_key
                        else:
                            source_label = current.get("label", "")
                            if "Parameter" in source_label:
                                desired_input_pin_name = source_label.split("(")[0].strip().lower().replace(" ", "_")
                            else:
                                desired_input_pin_name = source_label.lower().replace(" ", "_") if source_label else output_pin.get("name", "")
                    else:
                        desired_input_pin_name = None
                    
                    # Try to match with input pins
                    matched = False
                    for input_pin in next_input_pins:
                        input_pin_name = input_pin.get("name", "").lower()
                        input_pin_id = input_pin.get("id")
                        
                        # RULE: Never connect to Chat History pins
                        if "chat history" in input_pin_name:
                            continue  # Skip Chat History pins
                        
                        # RULE: Check if input pin is already connected
                        if (next_node["id"], input_pin_id) in connected_input_pins:
                            continue  # Skip already connected input pins
                        
                        # For Parameter Nodes, check if this matches the desired input pin name
                        if is_parameter_source and desired_input_pin_name:
                            if input_pin_name != desired_input_pin_name.lower():
                                continue  # Parameter Node needs specific input pin name
                        
                        # Check if this connection should exist
                        should_connect = False
                        if is_parameter_source and desired_input_pin_name:
                            # Parameter Node: exact match with desired name
                            should_connect = input_pin_name == desired_input_pin_name.lower()
                        else:
                            # Non-Parameter Node: use common matching patterns
                            should_connect = (
                                (output_pin_name == input_pin_name) or
                                (output_pin_name == "response" and input_pin_name in ["data", "response"]) or
                                (output_pin_name == "connection" and input_pin_name == "connection") or
                                (output_pin_name in ["data", "output", "text", "json"] and input_pin_name == "data")
                            )
                        
                        if should_connect:
                            # RULE: For Parameter Nodes, check if this Parameter Node already has a connection
                            if is_parameter_source and current.get("id") in connected_parameter_nodes:
                                continue  # This Parameter Node already has a connection, skip
                            
                            conn_key = (current["id"], next_node["id"], output_pin_id, input_pin_id)
                            if conn_key not in existing_data_conns:
                                valid_connections.append({
                                    "source_node": current["id"],
                                    "source_pin": output_pin_id,
                                    "destination_node": next_node["id"],
                                    "destination_pin": input_pin_id
                                })
                                print(f"Repaired: Added missing data flow connection {current.get('label', current.get('nodeType'))} '{output_pin.get('name')}' → {next_node.get('label', next_node.get('nodeType'))} '{input_pin.get('name')}'")
                                existing_data_conns.add(conn_key)
                                connected_input_pins.add((next_node["id"], input_pin_id))
                                
                                # Track that this Parameter Node now has a connection
                                if is_parameter_source:
                                    connected_parameter_nodes.add(current.get("id"))
                                
                                matched = True
                                break  # Only connect one output pin per input pin
                    
                    # If no matching input pin found, create one (but not for Global Data or ToJson nodes)
                    if not matched:
                        # RULE: For Parameter Nodes, if already connected, skip creating new connection
                        if is_parameter_source and current.get("id") in connected_parameter_nodes:
                            continue  # This Parameter Node already has a connection, skip
                        
                        # Skip ToJson nodes - they have fixed input pins and should not get additional ones auto-added
                        if is_tojson:
                            continue
                        # RULE: Parameter nodes never have input pins. Do not add input pins to Parameter.
                        if next_node.get("nodeType") == "Parameter":
                            continue
                        
                        # Determine input pin name based on output pin name or parameter key
                        if is_parameter_source:
                            # For Parameter Nodes: use parameter key as input pin name
                            param_config = current.get("configuration", {})
                            param_key = param_config.get("Parameter Key") or param_config.get("Key") or param_config.get("parameter_key")
                            if param_key:
                                input_pin_name = param_key
                            else:
                                source_label = current.get("label", "")
                                if "Parameter" in source_label:
                                    input_pin_name = source_label.split("(")[0].strip().lower().replace(" ", "_")
                                else:
                                    input_pin_name = source_label.lower().replace(" ", "_") if source_label else output_pin.get("name", "")
                        else:
                            # For non-Parameter nodes: use source pin name or common pattern
                            input_pin_name = output_pin.get("name", "")
                            if output_pin_name == "response":
                                # Check if node already has "Response" input, otherwise use "Data"
                                has_response_input = any(
                                    pin.get("name", "").lower() == "response" 
                                    for pin in next_node.get("pins", {}).get("input_pins", [])
                                )
                                input_pin_name = "Response" if has_response_input else "Data"
                            elif output_pin_name in ["output", "text", "json"]:
                                input_pin_name = "Data"
                        
                        # Check if this input pin already exists
                        existing_input = next(
                            (pin for pin in next_node.get("pins", {}).get("input_pins", [])
                             if pin.get("name", "").lower() == input_pin_name.lower()),
                            None
                        )
                        
                        if existing_input:
                            # Check if existing input pin is already connected
                            existing_input_id = existing_input.get("id")
                            if (next_node["id"], existing_input_id) in connected_input_pins:
                                # Input pin is already connected - create a new one
                                # For Parameter Nodes, always create unique input pins
                                if is_parameter_source:
                                    new_input_pin = {
                                        "id": str(uuid.uuid4()),
                                        "name": input_pin_name,
                                        "editable": True
                                    }
                                    next_node["pins"]["input_pins"].append(new_input_pin)
                                    input_pin_id = new_input_pin["id"]
                                    print(f"Repaired: Auto-added unique input pin '{input_pin_name}' to node {next_node.get('label', next_node.get('nodeType'))} (existing pin was already connected)")
                                else:
                                    # For non-Parameter nodes, skip if pin is connected
                                    continue
                            else:
                                # Use existing pin (not connected yet)
                                input_pin_id = existing_input_id
                        else:
                            # Create new input pin
                            new_input_pin = {
                                "id": str(uuid.uuid4()),
                                "name": input_pin_name,
                                "editable": True  # Mark as editable since it was auto-added
                            }
                            # RULE: Never create Chat History pins
                            if "chat history" in input_pin_name.lower():
                                continue  # Skip creating Chat History pins
                            
                            next_node["pins"]["input_pins"].append(new_input_pin)
                            
                            # Add input pin to node configuration
                            if "configuration" not in next_node:
                                next_node["configuration"] = {}
                            config_key = f"InputPin_{input_pin_name}" or input_pin_name
                            if config_key not in next_node["configuration"]:
                                next_node["configuration"][config_key] = ""
                            
                            input_pin_id = new_input_pin["id"]
                            print(f"Repaired: Auto-added input pin '{input_pin_name}' to node {next_node.get('label', next_node.get('nodeType'))} and added to configuration")
                        
                        # Create connection
                        conn_key = (current["id"], next_node["id"], output_pin_id, input_pin_id)
                        if conn_key not in existing_data_conns:
                            # RULE: For Parameter Nodes, check if already connected before creating new connection
                            if is_parameter_source and current.get("id") in connected_parameter_nodes:
                                continue  # This Parameter Node already has a connection, skip
                            
                            valid_connections.append({
                                "source_node": current["id"],
                                "source_pin": output_pin_id,
                                "destination_node": next_node["id"],
                                "destination_pin": input_pin_id
                            })
                            print(f"Repaired: Added missing data flow connection {current.get('label', current.get('nodeType'))} '{output_pin.get('name')}' → {next_node.get('label', next_node.get('nodeType'))} '{input_pin_name}'")
                            existing_data_conns.add(conn_key)
                            connected_input_pins.add((next_node["id"], input_pin_id))
                            
                            # Track that this Parameter Node now has a connection
                            if is_parameter_source:
                                connected_parameter_nodes.add(current.get("id"))
        
        print(f"Final repaired workflow: {len(valid_connections)} connections")
        return valid_connections
    
    def _get_pin_name_by_id(self, nodes: List[Dict], node_id: str, pin_id: str) -> Optional[str]:
        """Get pin name by pin ID"""
        node = next((n for n in nodes if n["id"] == node_id), None)
        if not node:
            return None
        
        for pin_collection in ["trigger_pins", "input_pins", "output_pins", "next_pins"]:
            for pin in node.get("pins", {}).get(pin_collection, []):
                if pin.get("id") == pin_id:
                    return pin.get("name")
        return None

    def _branch_keyword(self, label: Any) -> str:
        """Extract branch identifier for Handler-Response matching: 'Option A'/'Option B'/'Default' or first word."""
        s = (label or "").strip() if isinstance(label, str) else ""
        if not s:
            return ""
        lower = s.lower()
        # "Response for Option A" / "Option A Handler" -> "Option A"; "Default Response" -> "Default"
        m = re.search(r"option\s+(\w+)", lower)
        if m:
            return "Option " + m.group(1).capitalize()
        if "default" in lower:
            return "Default"
        first = s.split()[0].strip("()")
        return first if first and first.lower() not in ("the", "and") else ""

    def _is_next_used_for_other_response(self, connections: List[Dict], source_node_id: str, next_pin: Optional[str], response_node_id: str) -> bool:
        """True if source's Next pin is connected to a node that is NOT this Response (so we must skip this node)."""
        if not next_pin:
            return False
        return any(
            c.get("source_node") == source_node_id and c.get("source_pin") == next_pin and c.get("destination_node") != response_node_id
            for c in connections
        )

    def _validate_minimal_connections(self, nodes: List[Dict], connections: List[Dict]) -> tuple[bool, str, List[Dict]]:
        """
        Validate and enforce minimal & intentional connections rules:
        - Branch isolation for Switch nodes
        - One-to-one LLM → Response mapping
        - No redundant or cross-branch connections
        - Terminal nodes stop propagation
        
        Returns:
            (is_valid, error_message, filtered_connections)
        """
        node_lookup = {node["id"]: node for node in nodes}
        filtered_connections = []
        
        # Build execution branches from Switch nodes
        switch_branches = {}  # {switch_node_id: {out_pin_id: [node_ids_in_branch]}}
        node_to_branch = {}  # {node_id: (switch_node_id, out_pin_id)}
        
        # Find all Switch nodes and their branches
        for node in nodes:
            if node.get("nodeType") == "Switch":
                switch_id = node.get("id")
                switch_branches[switch_id] = {}
                
                # For each out pin (next_pin), track which nodes are in that branch
                for out_pin in node.get("pins", {}).get("next_pins", []):
                    out_pin_id = out_pin.get("id")
                    switch_branches[switch_id][out_pin_id] = []
        
        # Build branch membership by following connections from Switch out pins
        for conn in connections:
            source_node_id = conn.get("source_node")
            source_pin_id = conn.get("source_pin")
            dest_node_id = conn.get("destination_node")
            
            source_node = node_lookup.get(source_node_id)
            if not source_node:
                continue
            
            # Check if source is a Switch node's out pin
            if source_node.get("nodeType") == "Switch":
                for out_pin in source_node.get("pins", {}).get("next_pins", []):
                    if out_pin.get("id") == source_pin_id:
                        # This connection starts a branch
                        switch_id = source_node_id
                        out_pin_id = source_pin_id
                        
                        # Mark destination node as being in this branch
                        if switch_id in switch_branches:
                            if out_pin_id in switch_branches[switch_id]:
                                if dest_node_id not in switch_branches[switch_id][out_pin_id]:
                                    switch_branches[switch_id][out_pin_id].append(dest_node_id)
                                    node_to_branch[dest_node_id] = (switch_id, out_pin_id)
                                    
                                    # Recursively mark all downstream nodes in this branch
                                    self._mark_branch_nodes(dest_node_id, switch_id, out_pin_id, 
                                                           node_to_branch, connections, node_lookup)
        
        # Validate connections for branch isolation
        for conn in connections:
            source_node_id = conn.get("source_node")
            dest_node_id = conn.get("destination_node")
            
            source_node = node_lookup.get(source_node_id)
            dest_node = node_lookup.get(dest_node_id)
            
            if not source_node or not dest_node:
                continue
            
            # CRITICAL RULE: Prevent LLM nodes from connecting to other LLM nodes
            # LLM nodes should connect to Response nodes, not to other LLM nodes
            if source_node.get("nodeType") == "LLM" and dest_node.get("nodeType") == "LLM":
                print(f"REMOVED LLM → LLM connection: {source_node.get('label', 'Unknown')} → {dest_node.get('label', 'Unknown')}. LLM nodes should connect to Response nodes, not to other LLM nodes.")
                continue
            
            # Check if nodes are in different branches
            source_branch = node_to_branch.get(source_node_id)
            dest_branch = node_to_branch.get(dest_node_id)
            
            # If both nodes are in branches, they must be in the same branch
            if source_branch and dest_branch:
                if source_branch != dest_branch:
                    # Cross-branch connection detected - skip it
                    print(f"REMOVED cross-branch connection: {source_node.get('label', 'Unknown')} → {dest_node.get('label', 'Unknown')}")
                    continue
            
            # Validate LLM → Response one-to-one mapping (within same branch)
            if source_node.get("nodeType") == "LLM" and dest_node.get("nodeType") == "Response":
                # Check if this LLM already connects to another Response in the same branch
                existing_llm_to_response = [
                    c for c in filtered_connections
                    if c.get("source_node") == source_node_id and 
                       node_lookup.get(c.get("destination_node"), {}).get("nodeType") == "Response"
                ]
                if existing_llm_to_response:
                    # Check if existing connection is in same branch
                    existing_dest_id = existing_llm_to_response[0].get("destination_node")
                    existing_dest_branch = node_to_branch.get(existing_dest_id)
                    current_dest_branch = node_to_branch.get(dest_node_id)
                    
                    # If both are in branches and same branch, skip duplicate
                    if existing_dest_branch and current_dest_branch and existing_dest_branch == current_dest_branch:
                        print(f"REMOVED duplicate LLM → Response connection in same branch: {source_node.get('label', 'Unknown')} → {dest_node.get('label', 'Unknown')}")
                        continue
                
                # Check if this Response already connects from another LLM in the same branch
                existing_response_from_llm = [
                    c for c in filtered_connections
                    if c.get("destination_node") == dest_node_id and 
                       node_lookup.get(c.get("source_node"), {}).get("nodeType") == "LLM"
                ]
                if existing_response_from_llm:
                    # Check if existing connection is in same branch
                    existing_source_id = existing_response_from_llm[0].get("source_node")
                    existing_source_branch = node_to_branch.get(existing_source_id)
                    current_source_branch = node_to_branch.get(source_node_id)
                    
                    # If both are in branches and same branch, skip duplicate
                    if existing_source_branch and current_source_branch and existing_source_branch == current_source_branch:
                        print(f"REMOVED duplicate LLM → Response connection in same branch: {source_node.get('label', 'Unknown')} → {dest_node.get('label', 'Unknown')}")
                        continue
            
            # Check for terminal nodes (Response) - no connections after them
            if source_node.get("nodeType") == "Response":
                # Response nodes are terminal - no outgoing connections allowed
                print(f"REMOVED connection from terminal Response node: {source_node.get('label', 'Unknown')} → {dest_node.get('label', 'Unknown')}")
                continue
            
            # Check for duplicate connections
            conn_key = (source_node_id, conn.get("source_pin"), dest_node_id, conn.get("destination_pin"))
            existing_conn_keys = {
                (c.get("source_node"), c.get("source_pin"), c.get("destination_node"), c.get("destination_pin"))
                for c in filtered_connections
            }
            if conn_key in existing_conn_keys:
                print(f"REMOVED duplicate connection: {source_node.get('label', 'Unknown')} → {dest_node.get('label', 'Unknown')}")
                continue
            
            filtered_connections.append(conn)
        
        return True, "", filtered_connections
    
    def _mark_branch_nodes(self, node_id: str, switch_id: str, out_pin_id: str, 
                          node_to_branch: Dict, connections: List[Dict], node_lookup: Dict):
        """Recursively mark all downstream nodes as being in the same branch"""
        node = node_lookup.get(node_id)
        if not node:
            return
        
        # CRITICAL: Include Response nodes in branches (they are terminal but still part of the branch)
        # Mark Response node as being in this branch before stopping
        if node.get("nodeType") == "Response":
            # Mark Response node in branch before stopping recursion
            if node_id not in node_to_branch:
                node_to_branch[node_id] = (switch_id, out_pin_id)
            return
        
        # Find all nodes connected from this node
        for conn in connections:
            if conn.get("source_node") == node_id:
                dest_node_id = conn.get("destination_node")
                dest_node = node_lookup.get(dest_node_id)
                
                # Skip if already in a different branch
                existing_branch = node_to_branch.get(dest_node_id)
                if existing_branch and existing_branch != (switch_id, out_pin_id):
                    continue  # Already in a different branch
                
                # Mark as being in this branch
                if dest_node_id not in node_to_branch:
                    node_to_branch[dest_node_id] = (switch_id, out_pin_id)
                    
                    # If destination is a Response node, mark it but don't recurse further
                    if dest_node and dest_node.get("nodeType") == "Response":
                        # Response node is terminal - mark it in branch but stop recursion
                        continue
                    
                    # Recursively mark downstream nodes
                    self._mark_branch_nodes(dest_node_id, switch_id, out_pin_id, 
                                          node_to_branch, connections, node_lookup)
    
    def _remove_redundant_connections(self, nodes: List[Dict], connections: List[Dict]) -> List[Dict]:
        """
        Remove redundant connections based on minimal connection rules:
        - Remove duplicate connections
        - Remove connections after terminal nodes
        - Remove excessive fan-out/fan-in within same branch (unless explicitly required)
        """
        node_lookup = {node["id"]: node for node in nodes}
        filtered_connections = []
        seen_connections = set()
        
        # Track connections per node (for detecting duplicates)
        source_connections = {}  # {source_node_id: [connections]}
        dest_connections = {}     # {dest_node_id: [connections]}
        
        for conn in connections:
            source_node_id = conn.get("source_node")
            dest_node_id = conn.get("destination_node")
            conn_key = (source_node_id, conn.get("source_pin"), dest_node_id, conn.get("destination_pin"))
            
            # Skip duplicates
            if conn_key in seen_connections:
                continue
            seen_connections.add(conn_key)
            
            source_node = node_lookup.get(source_node_id)
            dest_node = node_lookup.get(dest_node_id)
            
            if not source_node or not dest_node:
                continue
            
            # Rule: Terminal nodes (Response) stop propagation
            if source_node.get("nodeType") == "Response":
                continue  # No connections from Response nodes
            
            # Track connections
            if source_node_id not in source_connections:
                source_connections[source_node_id] = []
            if dest_node_id not in dest_connections:
                dest_connections[dest_node_id] = []
            
            source_connections[source_node_id].append(conn)
            dest_connections[dest_node_id].append(conn)
            
            filtered_connections.append(conn)
        
        # Post-process: Remove excessive fan-out/fan-in within same execution path
        # This is handled by _validate_minimal_connections which checks branch isolation
        # Here we just ensure no duplicates and no terminal node violations
        
        return filtered_connections


# ============================================
# SWITCH NODE - VALIDATION & REFERENCE
# ============================================
# Correct pattern: Parameter "Data" → Switch "Input"; Switch.[ConditionLabel] → Handler "Start";
# Default → fallback only. Never use Default for defined conditions.
#
# Example Switch config and connections (conceptual; real connections use source_pin=pin ID):
#   configuration.conditions: [{"label":"Simple","operator":"contains","value":"simple"},
#                              {"label":"Complex","operator":"contains","value":"complex"}]
#   next_pins: Simple, Complex, Default
#   Switch.Simple → Simple Handler.Start, Switch.Complex → Complex Handler.Start


def validate_switch_connections(workflow: Dict) -> List[str]:
    """
    Validate switch node connections in a workflow.
    Returns list of errors found.
    Rules: Each condition must use its matching out pin; never use Default for defined conditions.
    """
    errors = []
    node_lookup = {n["id"]: n for n in workflow.get("nodes", [])}
    connections = workflow.get("connections", [])

    for node in workflow.get("nodes", []):
        if node.get("nodeType") != "Switch":
            continue
        switch_id = node["id"]
        conditions = (node.get("configuration") or {}).get("conditions", [])
        condition_labels = [str(c.get("label") or c.get("value", "")).strip() for c in conditions if isinstance(c, dict) and (c.get("label") or c.get("value"))]
        next_pins = {p.get("id"): p.get("name", "") for p in node.get("pins", {}).get("next_pins", [])}

        for c in connections:
            if c.get("source_node") != switch_id:
                continue
            source_pin_id = c.get("source_pin")
            from_pin = next_pins.get(source_pin_id) or (source_pin_id if not _is_uuid(source_pin_id) else None)
            if not from_pin:
                continue
            to_node = node_lookup.get(c.get("destination_node") or "")
            to_name = (to_node or {}).get("label") or (to_node or {}).get("name") or "Unknown"

            if from_pin == "Default" and condition_labels:
                for label in condition_labels:
                    if label and str(label).lower() in str(to_name).lower():
                        errors.append(
                            f"Switch '{node.get('label', node.get('name', 'Unknown'))}' uses 'Default' pin "
                            f"to connect to '{to_name}', but should use '{label}' pin"
                        )
                        break
            if from_pin not in condition_labels and from_pin != "Default":
                available = list(condition_labels) + ["Default"]
                if from_pin not in available:
                    errors.append(
                        f"Switch '{node.get('label', node.get('name', 'Unknown'))}' uses undefined pin '{from_pin}'. "
                        f"Available: {available}"
                    )
    return errors


def _is_uuid(s: Any) -> bool:
    if not s or not isinstance(s, str):
        return False
    return len(s) == 36 and s.count("-") == 4 and all(c in "0123456789abcdefABCDEF-" for c in s)

