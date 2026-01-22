import os
import json
import uuid
import re
from typing import Dict, List, Any, Optional
from app.infra.ai.openai_client import openai_client_service
from app.modules.nodes.registry import node_registry
from app.modules.nodes.base import NodeMetadata
from app.core.config import get_settings
# Ensure nodes are auto-discovered
import app.modules.nodes  # noqa: F401

settings = get_settings()


class AIWorkflowGenerator:
    """Service for AI-powered workflow generation"""
    
    def __init__(self):
        """Initialize the AI client and load node types"""
        # Use model from config or environment variable
        self.model = os.getenv('OPENAI_MODEL') or settings.DEFAULT_LLM_MODEL
        
        # Load node types from registry
        node_registry.auto_discover()
        self.node_types = self._get_node_types_info()
    
    def _get_node_types_info(self) -> List[Dict[str, Any]]:
        """
        Get node type information from registry and format for AI prompt
        
        Returns:
            List of node type definitions formatted for AI
        """
        nodes = node_registry.list_all()
        node_info = []
        
        for node_metadata in nodes:
            # Convert NodeMetadata to dict format expected by AI
            node_dict = {
                "id": node_metadata.id,
                "name": node_metadata.name,
                "description": node_metadata.description or "",
                "category": node_metadata.category,
                "pins": {
                    "trigger_pins": [{"name": pin.name, "id": pin.id} for pin in node_metadata.trigger_pins],
                    "input_pins": [{"name": pin.name, "id": pin.id} for pin in node_metadata.inputs],
                    "output_pins": [{"name": pin.name, "id": pin.id} for pin in node_metadata.outputs],
                    "next_pins": [{"name": pin.name, "id": pin.id} for pin in node_metadata.next_pins]
                },
                "config_schema": node_metadata.config_schema
            }
            node_info.append(node_dict)
        
        return node_info
    
    def _build_system_prompt(self) -> str:
        """
        Build comprehensive system prompt for AI workflow generation
        
        Returns:
            System prompt string
        """
        node_types_info = self._format_node_types_for_prompt()
        
        prompt = f"""You are an expert workflow designer. Your task is to generate complete, executable workflows from natural language descriptions.

AVAILABLE NODE TYPES:
{node_types_info}

WORKFLOW GENERATION RULES:

1. **Node Selection**:
   - Select appropriate node types based on the user's requirements
   - Use Entry node only for workflows that start without user input
   - Use Parameter node when user needs to provide input data
   - Use Trigger nodes (Entry, Webhook, etc.) only as workflow start points
   - Only ONE start node (Entry/Trigger/Webhook) per workflow

2. **Pin Connections**:
   - Control Flow: Connect next_pins → trigger_pins (defines execution order)
   - Data Flow: Connect output_pins → input_pins (defines data passing)
   - Connect ALL matching pins, not just the first one
   - Create missing pins dynamically when needed

3. **Special Rules**:
   - **LLM JSON Output**: If LLM outputs JSON format, automatically add ToJson node
     Connection: LLM "Response" → ToJson "Text" → ToJson "JSON"
   - **Entry Node Correction**: If Entry node has data connections, replace with Parameter node
   - **Multiple Start Nodes**: Ensure only one start node per workflow

4. **Template Syntax**:
   - Inject Jinja2 template syntax ({{{{...}}}}) into code/configuration fields
   - Convert single curly braces to double braces for proper templating
   - Support object property access: {{{{Data.keyName}}}}

5. **Workflow Structure**:
   - Generate descriptive workflow names based on functionality
   - Create comprehensive descriptions (150+ words) explaining workflow operation
   - Include step-by-step explanations, inputs, outputs, and use cases

6. **Node Positioning**:
   - Position nodes with proper spacing (x: 200 * index, y: 300)
   - Ensure nodes don't overlap

OUTPUT FORMAT:
Return a valid JSON object with this structure:
{{
    "workflow_name": "Descriptive Workflow Name",
    "workflow_description": "Comprehensive description (150+ words)...",
    "nodes": [
        {{
            "id": "node_unique_id",
            "type": "node",
            "label": "Node Label",
            "nodeType": "node_type_id",
            "pins": {{
                "trigger_pins": [{{"id": "pin_id", "name": "Start"}}],
                "input_pins": [{{"id": "pin_id", "name": "Data"}}],
                "output_pins": [{{"id": "pin_id", "name": "Output"}}],
                "next_pins": [{{"id": "pin_id", "name": "Next"}}]
            }},
            "configuration": {{}},
            "nodeData": {{"x": 200, "y": 300}}
        }}
    ],
    "connections": [
        {{
            "source_node": "node_id",
            "source_pin": "pin_id",
            "destination_node": "node_id",
            "destination_pin": "pin_id"
        }}
    ]
}}

IMPORTANT:
- Generate complete workflows with all necessary nodes and connections
- Ensure all data flows are properly connected
- Add missing pins when nodes need to receive/send data
- Apply special rules automatically
- Return ONLY valid JSON, no markdown or code blocks"""
        
        return prompt
    
    def _format_node_types_for_prompt(self) -> str:
        """Format node types information for inclusion in system prompt"""
        formatted = []
        for node in self.node_types:
            pins_info = []
            if node["pins"]["trigger_pins"]:
                pins_info.append(f"Trigger: {', '.join([p['name'] for p in node['pins']['trigger_pins']])}")
            if node["pins"]["input_pins"]:
                pins_info.append(f"Input: {', '.join([p['name'] for p in node['pins']['input_pins']])}")
            if node["pins"]["output_pins"]:
                pins_info.append(f"Output: {', '.join([p['name'] for p in node['pins']['output_pins']])}")
            if node["pins"]["next_pins"]:
                pins_info.append(f"Next: {', '.join([p['name'] for p in node['pins']['next_pins']])}")
            
            pins_str = " | ".join(pins_info) if pins_info else "No pins"
            
            formatted.append(
                f"- {node['id']} ({node['name']}): {node['description']}\n"
                f"  Pins: {pins_str}\n"
                f"  Category: {node['category']}"
            )
        
        return "\n\n".join(formatted)
    
    def generate_workflow(self, prompt: str) -> Dict[str, Any]:
        """
        Generate a workflow from a natural language prompt
        
        Args:
            prompt: Natural language description of the workflow
            
        Returns:
            Dictionary containing workflow_name, workflow_description, nodes, and connections
        """
        # Build system prompt
        system_prompt = self._build_system_prompt()
        
        # Call OpenAI API
        body = {
            "input": [
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            "instructions": system_prompt,
            "temperature": 0.7,
            "max_tokens": 4000
        }
        
        response = openai_client_service.query_with_workflows(body=body)
        
        if response.get("error"):
            raise Exception(f"OpenAI API error: {response.get('error')}")
        
        if not response.get("responses") or not response["responses"]:
            raise Exception("No response from OpenAI API")
        
        # Extract JSON from response
        response_text = response["responses"][0].get("content", "")
        
        # Try to extract JSON from markdown code blocks if present
        json_match = re.search(r'```(?:json)?\s*(\{.*\})\s*```', response_text, re.DOTALL)
        if json_match:
            response_text = json_match.group(1)
        else:
            # Try to find JSON object directly
            json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
            if json_match:
                response_text = json_match.group(0)
        
        try:
            workflow_data = json.loads(response_text)
        except json.JSONDecodeError as e:
            raise Exception(f"Failed to parse AI response as JSON: {str(e)}\nResponse: {response_text[:500]}")
        
        # Process and validate the generated workflow
        processed_workflow = self._process_generated_workflow(workflow_data)
        
        return processed_workflow
    
    def _process_generated_workflow(self, workflow_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Process and validate the AI-generated workflow
        
        Args:
            workflow_data: Raw workflow data from AI
            
        Returns:
            Processed workflow with validated nodes and connections
        """
        nodes = workflow_data.get("nodes", [])
        connections = workflow_data.get("connections", [])
        
        # Create node ID mapping for validation
        node_ids = {node["id"] for node in nodes}
        
        # Validate and repair connections
        valid_connections = self._validate_and_repair_connections(nodes, connections)
        
        # Apply special rules
        nodes, valid_connections = self._apply_special_rules(nodes, valid_connections)
        
        # Add missing pins
        nodes = self._add_missing_pins(nodes, valid_connections)
        
        # Inject template syntax
        nodes = self._inject_template_syntax(nodes, valid_connections)
        
        # Auto-generate missing connections
        valid_connections = self._auto_generate_connections(nodes, valid_connections)
        
        # Generate workflow metadata if missing
        workflow_name = workflow_data.get("workflow_name") or self._generate_workflow_name_from_structure(nodes)
        workflow_description = workflow_data.get("workflow_description") or self._generate_workflow_description_from_structure(nodes)
        
        return {
            "workflow_name": workflow_name,
            "workflow_description": workflow_description,
            "nodes": nodes,
            "connections": valid_connections
        }
    
    def _validate_and_repair_connections(self, nodes: List[Dict], connections: List[Dict]) -> List[Dict]:
        """Validate and repair connections between nodes"""
        node_dict = {node["id"]: node for node in nodes}
        valid_connections = []
        
        for conn in connections:
            source_node_id = conn.get("source_node")
            dest_node_id = conn.get("destination_node")
            
            if source_node_id not in node_dict or dest_node_id not in node_dict:
                continue
            
            source_node = node_dict[source_node_id]
            dest_node = node_dict[dest_node_id]
            
            source_pin_id = conn.get("source_pin")
            dest_pin_id = conn.get("destination_pin")
            
            # Validate pins exist or can be created
            if self._can_connect_pins(source_node, dest_node, source_pin_id, dest_pin_id):
                valid_connections.append(conn)
        
        return valid_connections
    
    def _can_connect_pins(self, source_node: Dict, dest_node: Dict, source_pin_id: str, dest_pin_id: str) -> bool:
        """Check if pins can be connected"""
        # Check if source pin exists in source node's outputs or next_pins
        source_pins = source_node.get("pins", {})
        source_outputs = [p.get("id") for p in source_pins.get("output_pins", [])]
        source_nexts = [p.get("id") for p in source_pins.get("next_pins", [])]
        
        # Check if dest pin exists in dest node's inputs or trigger_pins
        dest_pins = dest_node.get("pins", {})
        dest_inputs = [p.get("id") for p in dest_pins.get("input_pins", [])]
        dest_triggers = [p.get("id") for p in dest_pins.get("trigger_pins", [])]
        
        # Control flow: next_pins → trigger_pins
        if source_pin_id in source_nexts and dest_pin_id in dest_triggers:
            return True
        
        # Data flow: output_pins → input_pins
        if source_pin_id in source_outputs and dest_pin_id in dest_inputs:
            return True
        
        # Pins can be created dynamically
        return True
    
    def _apply_special_rules(self, nodes: List[Dict], connections: List[Dict]) -> tuple:
        """Apply special rules like LLM → ToJson, Entry → Parameter"""
        # Rule 1: LLM JSON Output - Add ToJson node if LLM outputs JSON
        llm_nodes = [n for n in nodes if n.get("nodeType") == "llm"]
        for llm_node in llm_nodes:
            # Check if LLM has connections to nodes that expect JSON
            llm_connections = [c for c in connections if c.get("source_node") == llm_node["id"]]
            # If LLM response might be JSON, add ToJson node
            # This is a simplified check - in production, you'd analyze the prompt/context
            has_to_json = any(n.get("nodeType") == "ToJson" for n in nodes)
            if not has_to_json and any("json" in str(c).lower() for c in llm_connections):
                to_json_node = self._create_to_json_node(len(nodes))
                nodes.append(to_json_node)
                # Update connections: LLM Response → ToJson Text
                for conn in llm_connections[:]:
                    if conn.get("source_pin") == "response" or "response" in str(conn.get("source_pin", "")).lower():
                        # Remove old connection
                        connections.remove(conn)
                        # Add new connections: LLM → ToJson → original destination
                        connections.append({
                            "source_node": llm_node["id"],
                            "source_pin": conn.get("source_pin"),
                            "destination_node": to_json_node["id"],
                            "destination_pin": "text"
                        })
                        connections.append({
                            "source_node": to_json_node["id"],
                            "source_pin": "json",
                            "destination_node": conn.get("destination_node"),
                            "destination_pin": conn.get("destination_pin")
                        })
        
        # Rule 2: Entry Node Correction - Replace Entry with Parameter if data connections exist
        entry_nodes = [n for n in nodes if n.get("nodeType") == "entry"]
        for entry_node in entry_nodes:
            entry_connections = [c for c in connections if c.get("source_node") == entry_node["id"]]
            # Check if Entry has data (output) connections
            has_data_connections = any(
                c.get("source_pin") in [p.get("id") for p in entry_node.get("pins", {}).get("output_pins", [])]
                for c in entry_connections
            )
            if has_data_connections:
                # Replace Entry with Parameter
                entry_node["nodeType"] = "parameter"
                entry_node["label"] = entry_node["label"].replace("Entry", "Parameter")
                # Add output pin if missing
                if not entry_node.get("pins", {}).get("output_pins"):
                    entry_node.setdefault("pins", {})["output_pins"] = [{"id": f"pin_{uuid.uuid4().hex[:8]}", "name": "Value"}]
        
        # Rule 3: Multiple Start Nodes - Keep only one
        start_node_types = ["entry", "trigger", "webhook"]
        start_nodes = [n for n in nodes if n.get("nodeType").lower() in start_node_types]
        if len(start_nodes) > 1:
            # Keep the first one, remove others
            for start_node in start_nodes[1:]:
                nodes.remove(start_node)
                # Remove connections from removed nodes
                connections[:] = [c for c in connections if c.get("source_node") != start_node["id"]]
        
        return nodes, connections
    
    def _create_to_json_node(self, index: int) -> Dict:
        """Create a ToJson node"""
        node_id = f"node_{uuid.uuid4().hex[:12]}"
        return {
            "id": node_id,
            "type": "node",
            "label": "To JSON",
            "nodeType": "ToJson",
            "pins": {
                "trigger_pins": [{"id": f"pin_{uuid.uuid4().hex[:8]}", "name": "Start"}],
                "input_pins": [{"id": f"pin_{uuid.uuid4().hex[:8]}", "name": "Text"}],
                "output_pins": [{"id": f"pin_{uuid.uuid4().hex[:8]}", "name": "JSON"}],
                "next_pins": [{"id": f"pin_{uuid.uuid4().hex[:8]}", "name": "Next"}]
            },
            "configuration": {},
            "nodeData": {"x": 200 * (index + 1), "y": 300}
        }
    
    def _add_missing_pins(self, nodes: List[Dict], connections: List[Dict]) -> List[Dict]:
        """Add missing pins to nodes based on connections"""
        node_dict = {node["id"]: node for node in nodes}
        
        for conn in connections:
            source_node = node_dict.get(conn.get("source_node"))
            dest_node = node_dict.get(conn.get("destination_node"))
            
            if not source_node or not dest_node:
                continue
            
            source_pin_id = conn.get("source_pin")
            dest_pin_id = conn.get("destination_pin")
            
            # Add missing output/next pin to source node
            # RULE: Parameter nodes never get next_pins (out pins) or extra output_pins. Do NOT create or add any pins on Parameter.
            if source_node.get("nodeType") == "Parameter":
                pass  # Skip - Parameter has exactly one output_pin (Data) and no next_pins; never add
            else:
                source_pins = source_node.setdefault("pins", {})
                if source_pin_id not in [p.get("id") for p in source_pins.get("output_pins", []) + source_pins.get("next_pins", [])]:
                    # Determine if it's a data or control pin based on destination
                    dest_pins = dest_node.get("pins", {})
                    if dest_pin_id in [p.get("id") for p in dest_pins.get("trigger_pins", [])]:
                        # Control flow - add to next_pins
                        if "next_pins" not in source_pins:
                            source_pins["next_pins"] = []
                        source_pins["next_pins"].append({"id": source_pin_id, "name": "Next"})
                    else:
                        # Data flow - add to output_pins
                        if "output_pins" not in source_pins:
                            source_pins["output_pins"] = []
                        source_pins["output_pins"].append({"id": source_pin_id, "name": "Output"})
            
            # Add missing input/trigger pin to dest node
            # RULE: Parameter nodes never have input_pins or trigger_pins. Do NOT add to Parameter.
            dest_pins = dest_node.get("pins", {})
            if dest_node.get("nodeType") != "Parameter" and dest_pin_id not in [p.get("id") for p in dest_pins.get("input_pins", []) + dest_pins.get("trigger_pins", [])]:
                if dest_pin_id in [p.get("id") for p in dest_pins.get("trigger_pins", [])]:
                    # Control flow - add to trigger_pins
                    if "trigger_pins" not in dest_pins:
                        dest_pins["trigger_pins"] = []
                    dest_pins["trigger_pins"].append({"id": dest_pin_id, "name": "Start"})
                else:
                    # Data flow - add to input_pins
                    if "input_pins" not in dest_pins:
                        dest_pins["input_pins"] = []
                    dest_pins["input_pins"].append({"id": dest_pin_id, "name": "Data"})
        
        return nodes
    
    def _inject_template_syntax(self, nodes: List[Dict], connections: List[Dict]) -> List[Dict]:
        """Inject Jinja2 template syntax into code/configuration fields"""
        # Find nodes that have data input connections
        nodes_with_data_inputs = set()
        for conn in connections:
            dest_node_id = conn.get("destination_node")
            dest_node = next((n for n in nodes if n["id"] == dest_node_id), None)
            if dest_node:
                dest_pins = dest_node.get("pins", {})
                dest_pin_id = conn.get("destination_pin")
                if dest_pin_id in [p.get("id") for p in dest_pins.get("input_pins", [])]:
                    nodes_with_data_inputs.add(dest_node_id)
        
        # Inject template syntax in configuration fields
        for node in nodes:
            if node["id"] in nodes_with_data_inputs:
                config = node.get("configuration", {})
                for key, value in config.items():
                    if isinstance(value, str):
                        # Convert single braces to double braces for Jinja2
                        # Pattern: {variable} -> {{variable}}
                        # But avoid double braces that are already there
                        if "{" in value and "{{" not in value:
                            # Simple pattern: replace { with {{ and } with }}
                            value = value.replace("{", "{{").replace("}", "}}")
                            config[key] = value
        
        return nodes
    
    def _auto_generate_connections(self, nodes: List[Dict], existing_connections: List[Dict]) -> List[Dict]:
        """Auto-generate missing connections based on node order and pin types"""
        connections = existing_connections.copy()
        connection_set = {(c["source_node"], c["source_pin"], c["destination_node"], c["destination_pin"]) for c in connections}
        
        # Sort nodes by position (x coordinate)
        sorted_nodes = sorted(nodes, key=lambda n: n.get("nodeData", {}).get("x", 0))
        
        for i in range(len(sorted_nodes) - 1):
            source_node = sorted_nodes[i]
            dest_node = sorted_nodes[i + 1]
            
            # Auto-connect control flow: next_pins → trigger_pins
            source_nexts = source_node.get("pins", {}).get("next_pins", [])
            dest_triggers = dest_node.get("pins", {}).get("trigger_pins", [])
            
            if source_nexts and dest_triggers:
                source_pin_id = source_nexts[0].get("id")
                dest_pin_id = dest_triggers[0].get("id")
                conn_key = (source_node["id"], source_pin_id, dest_node["id"], dest_pin_id)
                if conn_key not in connection_set:
                    connections.append({
                        "source_node": source_node["id"],
                        "source_pin": source_pin_id,
                        "destination_node": dest_node["id"],
                        "destination_pin": dest_pin_id
                    })
                    connection_set.add(conn_key)
            
            # Auto-connect data flow: output_pins → input_pins
            source_outputs = source_node.get("pins", {}).get("output_pins", [])
            dest_inputs = dest_node.get("pins", {}).get("input_pins", [])
            
            if source_outputs and dest_inputs:
                source_pin_id = source_outputs[0].get("id")
                dest_pin_id = dest_inputs[0].get("id")
                conn_key = (source_node["id"], source_pin_id, dest_node["id"], dest_pin_id)
                if conn_key not in connection_set:
                    connections.append({
                        "source_node": source_node["id"],
                        "source_pin": source_pin_id,
                        "destination_node": dest_node["id"],
                        "destination_pin": dest_pin_id
                    })
                    connection_set.add(conn_key)
        
        return connections
    
    def _generate_workflow_name_from_structure(self, nodes: List[Dict]) -> str:
        """Generate workflow name from node structure"""
        node_types = [n.get("nodeType", "").lower() for n in nodes]
        
        if "llm" in node_types:
            return "AI-Powered Workflow"
        elif "api" in node_types:
            return "API Integration Workflow"
        elif "parameter" in node_types:
            return "User Input Workflow"
        else:
            return "Generated Workflow"
    
    def _generate_workflow_description_from_structure(self, nodes: List[Dict]) -> str:
        """Generate workflow description from node structure"""
        node_descriptions = []
        for i, node in enumerate(nodes, 1):
            node_type = node.get("nodeType", "Unknown")
            node_label = node.get("label", node_type)
            node_descriptions.append(f"Step {i}: {node_label} ({node_type})")
        
        description = f"This workflow consists of {len(nodes)} nodes that work together to accomplish the specified task. "
        description += "The workflow processes data through the following steps: " + ", ".join(node_descriptions) + ". "
        description += "Each node is connected to ensure proper data flow and execution order. "
        description += "The workflow can be customized and extended based on specific requirements."
        
        return description


# Create singleton instance
ai_workflow_generator = AIWorkflowGenerator()

