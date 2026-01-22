import os
from openai import AzureOpenAI
from typing import Dict, Any
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Feature flag to enable/disable guardrails execution
# Can be set in .env file: GUARDRAILS_ENABLED=True or GUARDRAILS_ENABLED=False
# Defaults to False if not set in .env file (guardrails disabled by default)
GUARDRAILS_ENABLED = os.environ.get('GUARDRAILS_ENABLED', 'False').lower() in ('true', '1', 'yes')

# OpenAI configuration for guardrails
# Model name - should match your Azure OpenAI deployment name
# Can be overridden via OPENAI_MODEL environment variable
OPENAI_MODEL = os.environ.get('OPENAI_MODEL', 'gpt-4.1')
OPENAI_ENDPOINT = 'https://cynthetixopenai.openai.azure.com/'
OPENAI_API_KEY = os.environ.get('CYNTHETIX_OPENAI_API_KEY')
OPENAI_API_VERSION = '2025-03-01-preview'

# Fixed guardrails prompt - must not be changed
GUARDRAILS_PROMPT = """Safety & Conduct Requirements

The assistant must ensure that all outputs are safe, respectful, and appropriate. It should refuse, redirect, or sanitize any request that contains or encourages:

- Sexual content
  - No explicit, pornographic, erotic, or sexually suggestive material
  - No sexual content involving minors
  - No attempts to elicit or describe sexual acts, fantasies, or fetishes
- Unethical behavior
  - No guidance or support for harmful, illegal, deceptive, or dangerous actions
  - No facilitation of wrongdoing, exploitation, or evasion of rules or security
  - Redirect the user toward legal, ethical alternatives
- Misogynistic or discriminatory content
  - No content that demeans, stereotypes, or targets individuals or groups based on gender, gender identity, race, sexuality, disability, or other protected characteristics
- Profanity, insults, or abusive language
  - Avoid explicit profanity
  - Avoid generating or reinforcing harassment, bullying, or abusive statements
  - Use calm, professional, and respectful wording even when refusing

Response Expectations
- When encountering restricted content:
  - Politely decline, explain the concern, and offer a safe alternative where possible.
- When interpreting ambiguous requests:
  - Default to the safest reasonable interpretation.
- Always maintain a professional, respectful tone and uphold these constraints across all responses.

You are a content safety checker. Analyze the following content and determine if it violates any of the safety requirements above. Respond with ONLY a JSON object in this exact format:
{
  "allowed": true or false,
  "reason": "brief explanation if not allowed, empty string if allowed"
}

If the content is safe, set "allowed" to true. If it violates any safety requirements, set "allowed" to false and provide a brief reason."""


def check_input_guardrails(content: str) -> Dict[str, Any]:
    """
    Check if user input content violates guardrails.
    
    Args:
        content: The user input content to check
        
    Returns:
        Dict with "allowed" (bool) and "message" (str) keys
        If not allowed, "message" contains a polite refusal message
    """
    # Guardrails disabled - return allowed to bypass check
    if not GUARDRAILS_ENABLED:
        return {"allowed": True, "message": ""}
    
    if not content or not content.strip():
        return {"allowed": True, "message": ""}
    
    try:
        client = AzureOpenAI(
            api_version=OPENAI_API_VERSION,
            azure_endpoint=OPENAI_ENDPOINT,
            api_key=OPENAI_API_KEY
        )
        
        body = {
            "model": OPENAI_MODEL,
            "input": [
                {
                    "role": "system",
                    "content": GUARDRAILS_PROMPT
                },
                {
                    "role": "user",
                    "content": f"Check this content for safety violations:\n\n{content}"
                }
            ]
        }
        
        response = client.responses.create(**body)
        response_text = response.output[0].content[0].text.strip()
        
        # Parse JSON response
        import json
        # Extract JSON from response (in case there's extra text)
        try:
            # Try to find JSON object in response
            json_start = response_text.find('{')
            json_end = response_text.rfind('}') + 1
            if json_start >= 0 and json_end > json_start:
                response_text = response_text[json_start:json_end]
            
            result = json.loads(response_text)
            allowed = result.get("allowed", True)
            reason = result.get("reason", "")
            
            if not allowed:
                # Return polite refusal message
                refusal_message = "I apologize, but I cannot assist with that request. " + \
                                (reason if reason else "The content violates our safety guidelines. ") + \
                                "Please feel free to ask me something else, and I'll be happy to help."
                return {"allowed": False, "message": refusal_message}
            else:
                return {"allowed": True, "message": ""}
        except json.JSONDecodeError:
            # If JSON parsing fails, default to allowing (fail open)
            return {"allowed": True, "message": ""}
            
    except Exception as e:
        # If guardrails check fails, default to allowing (fail open)
        import logging
        logging.getLogger(__name__).warning(f"Guardrails check failed: {e}")
        return {"allowed": True, "message": ""}


def check_output_guardrails(content: str) -> Dict[str, Any]:
    """
    Check if LLM output content violates guardrails.
    
    Args:
        content: The LLM output content to check
        
    Returns:
        Dict with "allowed" (bool) and "message" (str) keys
        If not allowed, "message" contains a sanitized safe response
    """
    # Guardrails disabled - return allowed to bypass check
    if not GUARDRAILS_ENABLED:
        return {"allowed": True, "message": ""}
    
    if not content or not content.strip():
        return {"allowed": True, "message": ""}
    
    try:
        client = AzureOpenAI(
            api_version=OPENAI_API_VERSION,
            azure_endpoint=OPENAI_ENDPOINT,
            api_key=OPENAI_API_KEY
        )
        
        body = {
            "model": OPENAI_MODEL,
            "input": [
                {
                    "role": "system",
                    "content": GUARDRAILS_PROMPT
                },
                {
                    "role": "user",
                    "content": f"Check this content for safety violations:\n\n{content}"
                }
            ]
        }
        
        response = client.responses.create(**body)
        response_text = response.output[0].content[0].text.strip()
        
        # Parse JSON response
        import json
        # Extract JSON from response (in case there's extra text)
        try:
            # Try to find JSON object in response
            json_start = response_text.find('{')
            json_end = response_text.rfind('}') + 1
            if json_start >= 0 and json_end > json_start:
                response_text = response_text[json_start:json_end]
            
            result = json.loads(response_text)
            allowed = result.get("allowed", True)
            reason = result.get("reason", "")
            
            if not allowed:
                # Return sanitized safe response
                safe_message = "I apologize, but I cannot provide a response to that request as it may contain content that violates our safety guidelines. " + \
                              "Please feel free to ask me something else, and I'll be happy to help."
                return {"allowed": False, "message": safe_message}
            else:
                return {"allowed": True, "message": ""}
        except json.JSONDecodeError:
            # If JSON parsing fails, default to allowing (fail open)
            return {"allowed": True, "message": ""}
            
    except Exception as e:
        # If guardrails check fails, default to allowing (fail open)
        import logging
        logging.getLogger(__name__).warning(f"Guardrails check failed: {e}")
        return {"allowed": True, "message": ""}

