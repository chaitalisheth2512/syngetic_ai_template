from workflow.workflow_datatypes import NodeConfig, FieldType
from workflow.workflow_executor import Node
import workflow.workflow_service as workflow_service


class agent_execute_node:
    """
    Execute another agent.
    - If workflow_id is provided → execute that workflow of target agent
    - If workflow_id is empty → delegate task to agent LLM
    """

    default_setup: NodeConfig = {
        "id": "AgentExecute",
        "name": "Agent Execute",
        "description": "Execute another agent or its workflow",
        "pins": {
            "trigger_pins": [{"name": "Start"}],
            "input_pins": [{"name": "Input"}],
            "output_pins": [
                {"name": "Response"},
                {"name": "Metadata"}
            ],
            "next_pins": [{"name": "Next"}]
        },
        "fields": [
            {
                "id": "target_agent_id",
                "label": "Target Agent",
                "type": FieldType.SINGLE_SELECT,
                "options": []
            },
            {
                "id": "target_workflow_id",
                "label": "Target Workflow (Optional)",
                "type": FieldType.SINGLE_SELECT,
                "options": []
            },
            {
                "id": "execution_mode",
                "label": "Execution Mode",
                "type": FieldType.SINGLE_SELECT,
                "options": [
                    "Wait for response",
                    "Continue immediately"
                ]
            }
        ]
    }

    def __init__(self, node: Node):
        self.node = node

    def Run(self, connection, data):
        config = self.node.data.get("configuration", {})
        print(config,"config-------------------")

        target_agent_id = config.get("target_agent_id")
        # target_agent_id = "1d715c5a-7f9c-44dc-896a-4502a84e1076"
        target_workflow_id = config.get("target_workflow_id")
        # target_workflow_id = "4fcc2730-6d7c-4652-a91d-8779f55af107"
        execution_mode = config.get("execution_mode", "Wait for response")

        input_payload = data["Input"]
        print(input_payload,"input_payload-------------------")
        parent_agent_id = self.node.workflow.agent_id
        trace_id = self.node.workflow.log.get("id")
        # parent_log = self.node.workflow.log

        if not target_agent_id:
            raise Exception("Target agent is required")

        # ======================================================
        # CASE A: Execute workflow of another agent
        # ======================================================
        if target_workflow_id:
            print(target_workflow_id,"target_workflow_id-------------------")
            if execution_mode == "Wait for response":
                try:
                    # Ensure parameters is a dict - if input_payload is not a dict, wrap it
                    if isinstance(input_payload, dict):
                        parameters = input_payload
                    elif input_payload is not None:
                        # If input_payload is a string or other type, wrap it in a dict
                        parameters = {"input": input_payload}
                    else:
                        parameters = {}
                    
                    # Create a proper log for the target workflow (not the parent workflow's log)
                    target_log = workflow_service.workflow_log_create(
                        agent_id=target_agent_id,
                        workflow_id=target_workflow_id,
                        conversation_id=None
                    )
                    
                    result = workflow_service.workflow_execute(
                        agent_id=target_agent_id,
                        workflow_id=target_workflow_id,
                        parameters=parameters,
                        globals={
                            "called_from_agent": parent_agent_id,
                            "trace_id": trace_id
                        },
                        log=target_log
                    )
                    print(result,"result-1---------------")
                    
                    self.node.SetTargetPinData("Response", result.get("responses"))
                    self.node.SetTargetPinData("Metadata", {
                        "mode": "sync",
                        "target_agent": target_agent_id,
                        "workflow_id": target_workflow_id
                    })
                except Exception as e:
                    print(f"Error executing workflow: {e}")
                    # Set error response instead of crashing
                    self.node.SetTargetPinData("Response", None)
                    self.node.SetTargetPinData("Metadata", {
                        "mode": "sync",
                        "target_agent": target_agent_id,
                        "workflow_id": target_workflow_id,
                        "error": str(e)
                    })

            else:
                # Ensure parameters is a dict for async execution too
                if isinstance(input_payload, dict):
                    parameters = input_payload
                elif input_payload is not None:
                    parameters = {"input": input_payload}
                else:
                    parameters = {}
                
                # Create a proper log for the target workflow (not the parent workflow's log)
                target_log = workflow_service.workflow_log_create(
                    agent_id=target_agent_id,
                    workflow_id=target_workflow_id,
                    conversation_id=None
                )
                
                workflow_service.workflow_execute_async(
                    agent_id=target_agent_id,
                    workflow_id=target_workflow_id,
                    parameters=parameters,
                    globals={
                        "called_from_agent": parent_agent_id,
                        "trace_id": trace_id
                    },
                    log=target_log
                )

                self.node.SetTargetPinData("Metadata", {
                    "mode": "async",
                    "target_agent": target_agent_id,
                    "workflow_id": target_workflow_id,
                    "status": "dispatched"
                })

        # ======================================================
        # CASE B: Delegate to agent LLM (no workflow selected)
        # ======================================================
        else:
            if execution_mode == "Wait for response":
                result = workflow_service.agent_delegate(
                    from_agent=parent_agent_id,
                    to_agent=target_agent_id,
                    input_payload=input_payload,
                    trace_id=trace_id
                )

                print(result,"result----------------")

                self.node.SetTargetPinData("Response", result.get("response"))
                self.node.SetTargetPinData("Metadata", result.get("metadata"))

            else:
                workflow_service.agent_delegate_async(
                    from_agent=parent_agent_id,
                    to_agent=target_agent_id,
                    input_payload=input_payload,
                    trace_id=trace_id
                )

                self.node.SetTargetPinData("Metadata", {
                    "mode": "async",
                    "target_agent": target_agent_id,
                    "status": "delegated"
                })

        return self.node.Trigger(["Next"])
