import time
import hmac
import hashlib

from twilio.request_validator import RequestValidator
from cosmos_interface import database, cosmos_getbyid
from azure.cosmos import exceptions

def verify_twilio_request(
    auth_token: str,
    url: str,
    params: dict,
    signature: str
) -> bool:
    validator = RequestValidator(auth_token)
    
    # # Debug information
    # print("=" * 50)
    # print("TWILIO SIGNATURE VERIFICATION DEBUG")
    # print("=" * 50)
    # print(f"URL: {url}")
    # print(f"Params count: {len(params) if params else 0}")
    # print(f"Params keys: {list(params.keys())[:10] if params else 'None'}")  # First 10 keys
    # print(f"Signature: {signature}")
    # print(f"Auth token (first 10 chars): {auth_token[:10]}...")
    
    # Try validation with the provided URL
    is_valid = validator.validate(url, params, signature)
    # print(f"Validation result (original URL): {is_valid}")
    
    # # If validation fails, try alternative URL formats
    # if not is_valid:
    #     from urllib.parse import urlparse, urlunparse
        
    #     parsed = urlparse(url)
        
    #     # Try 1: URL without query parameters (query params should be in params dict)
    #     base_url = urlunparse((parsed.scheme, parsed.netloc, parsed.path, parsed.params, '', parsed.fragment))
    #     # print(f"Trying URL without query: {base_url}")
    #     is_valid = validator.validate(base_url, params, signature)
    #     # print(f"Validation result (no query): {is_valid}")
        
    #     # Try 2: Force HTTPS if HTTP
    #     if not is_valid and parsed.scheme == 'http':
    #         https_url = url.replace('http://', 'https://')
    #         # print(f"Trying HTTPS URL: {https_url}")
    #         is_valid = validator.validate(https_url, params, signature)
    #         # print(f"Validation result (HTTPS): {is_valid}")
        
    #     # Try 3: Remove port if present
    #     if not is_valid and ':' in parsed.netloc and parsed.port:
    #         no_port_url = url.replace(f':{parsed.port}', '')
    #         # print(f"Trying URL without port: {no_port_url}")
    #         is_valid = validator.validate(no_port_url, params, signature)
    #         # print(f"Validation result (no port): {is_valid}")
    
    # print("=" * 50)
    return is_valid


def normalize_twilio_event(event_type: str, form: dict) -> dict:
    """
    Normalize Twilio SMS & Call payloads into ONE structure
    """

    base = {
        "type": None,  # message | call
        "from": form.get("From"),
        "to": form.get("To"),
        "timestamp": int(time.time()),
        "message": None,
        "call": None,
    }

    # -------------------------
    # SMS / MMS
    # -------------------------
    if event_type == "twilio-sms":
        media = []
        media_count = int(form.get("NumMedia", 0))

        for i in range(media_count):
            media.append({
                "url": form.get(f"MediaUrl{i}"),
                "content_type": form.get(f"MediaContentType{i}")
            })

        base["type"] = "message"
        base["message"] = {
            "body": form.get("Body"),
            "message_sid": form.get("MessageSid"),
            "account_sid": form.get("AccountSid"),
            "media": media
        }

    # -------------------------
    # VOICE CALL
    # -------------------------
    elif event_type == "twilio-calls":
        base["type"] = "call"
        base["call"] = {
            "call_sid": form.get("CallSid"),
            "status": form.get("CallStatus"),
            "direction": form.get("Direction"),
            "duration": form.get("CallDuration"),
            "account_sid": form.get("AccountSid"),
        }

    return base

# Constants
APP_ID = "2584967868541602"
APP_SECRET = "c4d165f21a0198f3e3c91bc5c5d75fe6"
GRAPH_API_VERSION = "v24.0"
GRAPH_API_BASE_URL = f"https://graph.facebook.com/{GRAPH_API_VERSION}"
ACCESS_TOKEN = "EAAkvA7uPaqIBQZAEMmkFFnxSNlGfgdovCfeM0PjfR7cLZBpJ0Km8CABZBmoFBYBQfCIGbLv92MfQU2TniiG4Pu40QhRx9ZC2maHZCIseaaVp6t9yHzOXnxhHbBDZCpYgsehM1gA6xDj5XMrQitZAED0B95wqJXC0XN04ojyfzcOT1yS99ISyBJpUZBclh7me98e21jII7CkCbDXeB29Gin2HcNSubl3ZCeKHOZBzrLregosMlVGkUZCsO3RnLZBEs14Tso4kASv1EmT0Xenv4zZColDeS"



def verify_signature(payload: bytes, signature: str, app_secret: str):
    """
    Verify WhatsApp webhook signature using HMAC SHA256.
    
    Args:
        payload: Raw request payload as bytes
        signature: Signature from X-Hub-Signature-256 header (format: sha256=<hash>)
        app_secret: WhatsApp app secret key
        
    Returns:
        bool: True if signature is valid, False otherwise
    """
    if not signature:
        return False

    expected = hmac.new(
        app_secret.encode(),
        payload,
        hashlib.sha256
    ).hexdigest()

    return hmac.compare_digest(f"sha256={expected}", signature)


def get_whatsapp_account(account_id: str):
    """
    Get WhatsApp account from database by account_id.
    Searches for accounts where id=account_id or account_id field matches.
    
    Args:
        account_id: The account ID to look up (from entry[0].id in webhook payload)
        
    Returns:
        dict: Account data with secret_key, or None if not found
    """
    try:
        # Try to get from Account container if it exists
        try:
            account_container = database.get_container_client("Account")
            # Search by id field or account_id field
            query = f"SELECT * FROM c WHERE (c.type='whatsapp_account' OR c.type='account') AND (c.id='{account_id}' OR c.account_id='{account_id}')"
            items = account_container.query_items(
                query=query,
                enable_cross_partition_query=True
            )
            accounts = list(items)
            if accounts:
                return accounts[0]
        except Exception as e:
            print(f"Error querying Account container: {e}")
        
        # Fallback: Try Agent container
        try:
            from cosmos_interface import agent_container
            query = f"SELECT * FROM c WHERE (c.type='whatsapp_account' OR c.type='account') AND (c.id='{account_id}' OR c.account_id='{account_id}')"
            items = agent_container.query_items(
                query=query,
                enable_cross_partition_query=True
            )
            accounts = list(items)
            if accounts:
                return accounts[0]
        except Exception as e:
            print(f"Error querying Agent container: {e}")
            
    except Exception as e:
        print(f"Error getting WhatsApp account: {e}")
    
    return None


def parse_whatsapp_message(payload: dict):
    entry = payload["entry"][0]
    change = entry["changes"][0]
    value = change["value"]

    messages = value.get("messages")
    if not messages:
        return None

    msg = messages[0]

    return {
        "platform": "whatsapp",
        "from": msg["from"],
        "message_id": msg["id"],
        "timestamp": msg["timestamp"],
        "type": msg["type"],
        "text": msg.get("text", {}).get("body"),
        "raw": payload
    }
