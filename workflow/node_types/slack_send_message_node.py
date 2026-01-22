# workflow/node_types/slack_send_message_node.py

from workflow.workflow_datatypes import Pin, NodeConfig, FieldType
from workflow.workflow_executor import Node
import requests
import json
import traceback
from jinja2 import Template, TemplateSyntaxError

class slack_send_message_node:

    default_setup: NodeConfig = {
        "id": "SlackSendMessage",
        "name": "Send Slack Message",
        "description": "Send a message to a Slack channel or user (as bot or user)",
        "pins": {
            "trigger_pins": [{"name": "Start"}],
            "input_pins": [{"name": "Message"}],
            "output_pins": [{"name": "Response"}],
            "next_pins": [{"name": "Next"}],
        },
        "fields": [
            # ============================================
            # CONNECTION METHOD
            # ============================================
            {
                "id": "ConnectionMethod",
                "label": "Connect using",
                "type": FieldType.SINGLE_SELECT,
                "width": "100%",
                "options": ["OAuth2 (recommended)", "Access Token"]
            },
            
            # ============================================
            # OAUTH2 FIELDS (for OAuth flow)
            # ============================================
            {
                "id": "OAuthClientId",
                "label": "OAuth Client ID",
                "type": FieldType.SINGLE_LINE,
                "width": "50%"
            },
            {
                "id": "OAuthClientSecret",
                "label": "OAuth Client Secret",
                "type": FieldType.SINGLE_LINE,
                "width": "50%"
            },
            {
                "id": "OAuthRedirectURI",
                "label": "OAuth Redirect URI",
                "type": FieldType.SINGLE_LINE,
                "width": "100%"
            },
            {
                "id": "OAuthAccessToken",
                "label": "OAuth Bot Token (from OAuth flow - for sending as bot)",
                "type": FieldType.SINGLE_LINE,
                "width": "100%"
            },
            {
                "id": "OAuthUserToken",
                "label": "OAuth User Token (from OAuth flow - for sending as user)",
                "type": FieldType.SINGLE_LINE,
                "width": "100%"
            },
            {
                "id": "OAuthRefreshToken",
                "label": "OAuth Refresh Token (optional)",
                "type": FieldType.SINGLE_LINE,
                "width": "100%"
            },
            
            # ============================================
            # ACCESS TOKEN FIELD (for direct token)
            # ============================================
            {
                "id": "AccessToken",
                "label": "Slack Bot Token (if using Access Token method - for sending as bot)",
                "type": FieldType.SINGLE_LINE,
                "width": "100%"
            },
            {
                "id": "UserToken",
                "label": "Slack User Token (if using Access Token method - for sending as user)",
                "type": FieldType.SINGLE_LINE,
                "width": "100%"
            },
            
            # ============================================
            # SEND AS CONFIGURATION
            # ============================================
            {
                "id": "SendAs",
                "label": "Send as",
                "type": FieldType.SINGLE_SELECT,
                "width": "100%",
                "options": ["Bot", "User"]
            },
            
            # ============================================
            # MESSAGE CONFIGURATION
            # ============================================
            # {
            #     "id": "Resource",
            #     "label": "Resource",
            #     "type": FieldType.SINGLE_SELECT,
            #     "width": "50%",
            #     "options": ["Message", "Channel", "User"]
            # },
            {
                "id": "SendMessageTo",
                "label": "Send Message To",
                "type": FieldType.SINGLE_SELECT,
                "width": "50%",
                "options": ["Channel", "Direct Message"]
            },
            {
                "id": "Channel",
                "label": "Channel (name or ID, e.g., #general or C123456)",
                "type": FieldType.SINGLE_LINE,
                "width": "50%"
            },
            {
                "id": "User",
                "label": "User ID or Email (e.g., U123456 or user@example.com)",
                "type": FieldType.SINGLE_LINE,
                "width": "50%"
            },
            {
                "id": "Message",
                "label": "Message",
                "type": FieldType.TEXT,
                "width": "100%"
            },
            {
                "id": "ThreadTS",
                "label": "Thread Timestamp (optional - for replies)",
                "type": FieldType.SINGLE_LINE,
                "width": "100%"
            }
        ],
    }

    def __init__(self, node: Node):
        self.node = node
        cfg = node.data.get("configuration") or {}
        
        # Connection method
        self.connection_method = cfg.get("ConnectionMethod", "Access Token")
        
        # OAuth fields
        self.oauth_client_id = cfg.get("OAuthClientId", "")
        self.oauth_client_secret = cfg.get("OAuthClientSecret", "")
        self.oauth_redirect_uri = cfg.get("OAuthRedirectURI", "")
        self.oauth_access_token = cfg.get("OAuthAccessToken", "")  # Bot token
        self.oauth_user_token = cfg.get("OAuthUserToken", "")       # User token
        self.oauth_refresh_token = cfg.get("OAuthRefreshToken", "")
        
        # Access Token (direct method)
        self.access_token = cfg.get("AccessToken", "")  # Bot token
        self.user_token = cfg.get("UserToken", "")      # User token
        
        # Send as configuration
        self.send_as = cfg.get("SendAs", "Bot")  # "Bot" or "User"
        
        # Message configuration
        # self.resource = cfg.get("Resource", "Message")
        self.send_message_to = cfg.get("SendMessageTo", "Channel")
        self.channel = cfg.get("Channel", "")
        self.user = cfg.get("User", "")
        self.message = cfg.get("Message", "")
        self.thread_ts = cfg.get("ThreadTS", "")

    def _get_active_token(self):
        """
        Get the active token based on connection method and send_as setting.
        Returns Bot Token if Send As = "Bot", User Token if Send As = "User"
        """
        # If sending as User, prefer User Token
        if self.send_as == "User":
            if self.connection_method == "OAuth2 (recommended)":
                if self.oauth_user_token:
                    return self.oauth_user_token
                elif self.user_token:
                    return self.user_token
                else:
                    # Fallback to bot token with warning
                    self.node.LogEvent("Warning", data={
                        "message": "User Token not provided, falling back to Bot Token. Message will be sent as bot."
                    })
                    return self.oauth_access_token or self.access_token
            else:
                if self.user_token:
                    return self.user_token
                else:
                    # Fallback to bot token with warning
                    self.node.LogEvent("Warning", data={
                        "message": "User Token not provided, falling back to Bot Token. Message will be sent as bot."
                    })
                    return self.access_token
        
        # If sending as Bot, use Bot Token
        else:  # send_as == "Bot"
            if self.connection_method == "OAuth2 (recommended)":
                return self.oauth_access_token or self.access_token
            else:
                return self.access_token

    def _get_channel_id(self, channel_name: str, access_token: str) -> str:
        """Convert channel name to channel ID"""
        if not channel_name:
            return None
            
        # If it's already a channel ID (starts with C)
        if channel_name.startswith('C') and len(channel_name) > 8:
            return channel_name
        
        # Remove # if present
        if channel_name.startswith('#'):
            channel_name = channel_name[1:]
        
        # Try to get channel ID from Slack API
        try:
            response = requests.get(
                "https://slack.com/api/conversations.list",
                headers={"Authorization": f"Bearer {access_token}"},
                params={"types": "public_channel,private_channel"}
            )
            if response.ok:
                data = response.json()
                if data.get("ok"):
                    for channel in data.get("channels", []):
                        if channel.get("name") == channel_name:
                            return channel.get("id")
        except Exception as e:
            self.node.LogEvent("Channel Lookup Error", data={}, error=str(e))  # FIXED: Added data={}
        
        # If not found, return as-is (might be an ID)
        return channel_name

    def _get_user_id(self, user_identifier: str, access_token: str) -> str:
        """Convert user email/name to user ID - improved matching"""
        if not user_identifier:
            return None
            
        # If it's already a user ID (starts with U)
        if user_identifier.startswith('U') and len(user_identifier) > 8:
            return user_identifier
        
        try:
            # Try to find user by email or name
            response = requests.get(
                "https://slack.com/api/users.list",
                headers={"Authorization": f"Bearer {access_token}"}
            )
            if response.ok:
                data = response.json()
                if data.get("ok"):
                    found_users = []
                    identifier_lower = user_identifier.lower().strip()
                    
                    for user in data.get("members", []):
                        # Skip deleted users and bots
                        if user.get("deleted") or user.get("is_bot"):
                            continue
                        
                        profile = user.get("profile", {})
                        user_name = user.get("name", "").lower()
                        real_name = user.get("real_name", "").lower()
                        display_name = profile.get("display_name", "").lower()
                        user_email = profile.get("email", "").lower()
                        user_id = user.get("id", "")
                        
                        # Try multiple matching strategies
                        matches = False
                        
                        # Exact match
                        if (identifier_lower == user_name or 
                            identifier_lower == real_name or
                            identifier_lower == display_name or
                            identifier_lower == user_email or
                            identifier_lower == user_id.lower()):
                            matches = True
                        
                        # Partial match (contains)
                        elif (identifier_lower in user_name or
                              identifier_lower in real_name or
                              identifier_lower in display_name or
                              identifier_lower in user_email):
                            matches = True
                        
                        # Match without dots/formatting
                        identifier_clean = identifier_lower.replace('.', '').replace('_', '').replace('-', '')
                        user_name_clean = user_name.replace('.', '').replace('_', '').replace('-', '')
                        real_name_clean = real_name.replace('.', '').replace('_', '').replace('-', '')
                        
                        if (identifier_clean in user_name_clean or
                            identifier_clean in real_name_clean):
                            matches = True
                        
                        if matches:
                            found_user_id = user.get("id")
                            self.node.LogEvent("User Found", data={
                                "identifier": user_identifier,
                                "user_id": found_user_id,
                                "user_name": user.get("name"),
                                "real_name": user.get("real_name"),
                                "user_email": user_email
                            })
                            return found_user_id
                        
                        # Store for debugging (all users for better error message)
                        found_users.append({
                            "id": user_id,
                            "name": user.get("name"),
                            "real_name": user.get("real_name"),
                            "email": user_email or "(no email)",
                            "display_name": profile.get("display_name", "")
                        })
                    
                    # User not found - log all available users for debugging
                    self.node.LogEvent("User Not Found", data={
                        "identifier": user_identifier,
                        "searched_in": len(data.get("members", [])),
                        "available_users": found_users[:20]  # Show first 20 users
                    }, error=f"User '{user_identifier}' not found in workspace")
                    
                    # Return None instead of returning the email
                    return None
                else:
                    # API returned error
                    api_error = data.get("error", "Unknown error")
                    self.node.LogEvent("User Lookup API Error", data={
                        "identifier": user_identifier,
                        "api_error": api_error
                    }, error=f"Slack API error: {api_error}")
                    return None
            else:
                self.node.LogEvent("User Lookup HTTP Error", data={
                    "identifier": user_identifier,
                    "status_code": response.status_code
                }, error=f"HTTP {response.status_code}")
                return None
        except Exception as e:
            self.node.LogEvent("User Lookup Error", data={
                "identifier": user_identifier,
                "exception": str(e)
            }, error=str(e))
            return None

    def _send_message(self, channel_id: str, message: str, thread_ts: str = None) -> dict:
        """Send message to Slack"""
        access_token = self._get_active_token()
        
        if not access_token:
            raise Exception("No access token available. Please provide OAuth Access Token or Access Token.")
        
        payload = {
            "channel": channel_id,
            "text": message
        }
        
        if thread_ts:
            payload["thread_ts"] = thread_ts
        
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json"
        }
        
        response = requests.post(
            "https://slack.com/api/chat.postMessage",
            headers=headers,
            json=payload
        )
        
        if response.ok:
            return response.json()
        else:
            raise Exception(f"Slack API error: {response.status_code} - {response.text}")

    def Run(self, connection, data):
        response_data = {}
        
        try:
            # Get active token
            access_token = self._get_active_token()
            if not access_token:
                raise Exception("No access token available. Please configure OAuth Access Token or Access Token in node configuration.")
            
            # Apply Jinja templating to fields (similar to llm_node.py)
            if self.message != None:
                messageTemplate = Template(self.message)
                self.message = messageTemplate.render(**data)
            
            if self.channel != None:
                channelTemplate = Template(self.channel)
                self.channel = channelTemplate.render(**data)
            
            if self.user != None:
                userTemplate = Template(self.user)
                self.user = userTemplate.render(**data)
            
            if self.thread_ts != None and self.thread_ts != "":
                threadTsTemplate = Template(self.thread_ts)
                self.thread_ts = threadTsTemplate.render(**data)
            
            # Validate message
            if not self.message:
                raise Exception("Message is required")
            
            # Determine channel/user ID
            channel_id = None
            
            if self.send_message_to == "Channel":
                if not self.channel:
                    raise Exception("Channel is required when sending to channel")
                channel_id = self._get_channel_id(self.channel, access_token)
                if not channel_id:
                    raise Exception(f"Could not find channel: {self.channel}")
                    
            elif self.send_message_to in ["User", "Direct Message"]:
                if not self.user:
                    raise Exception("User is required when sending to user")
                
                # Get user ID
                user_id = self._get_user_id(self.user, access_token)
                
                # Validate user ID was found
                if not user_id:
                    raise Exception(
                        f"User '{self.user}' not found in Slack workspace. "
                        f"Please verify:\n"
                        f"1. The email/username is correct\n"
                        f"2. The user exists in your Slack workspace\n"
                        f"3. The user's email is visible to the bot\n"
                        f"4. Try using the user's Slack ID (starts with 'U') instead"
                    )
                
                # Validate it's actually a user ID (not still an email)
                if not user_id.startswith('U'):
                    raise Exception(
                        f"Could not convert '{self.user}' to a valid Slack user ID. "
                        f"Please use the user's Slack ID (starts with 'U') or ensure the email exists in the workspace."
                    )
                
                # Open DM channel
                try:
                    dm_response = requests.post(
                        "https://slack.com/api/conversations.open",
                        headers={"Authorization": f"Bearer {access_token}"},
                        json={"users": user_id}
                    )
                    if dm_response.ok:
                        dm_data = dm_response.json()
                        if dm_data.get("ok"):
                            channel_id = dm_data.get("channel", {}).get("id")
                        else:
                            error_msg = dm_data.get("error", "Unknown error")
                            # Check for specific errors
                            if error_msg == "missing_scope":
                                scope_location = "Bot Token Scopes" if self.send_as == "Bot" else "User Token Scopes"
                                raise Exception(
                                    f"Missing required Slack scope: 'im:write'. "
                                    f"Please add 'im:write' scope to your Slack app's {scope_location}. "
                                    f"Go to https://api.slack.com/apps → Your App → OAuth & Permissions → {scope_location} → Add 'im:write'"
                                )
                            elif error_msg == "user_not_found":
                                raise Exception(
                                    f"User '{self.user}' (ID: {user_id}) not found or cannot be accessed. "
                                    f"This might mean:\n"
                                    f"1. The user doesn't exist in the workspace\n"
                                    f"2. The bot doesn't have permission to see the user\n"
                                    f"3. The user ID is invalid"
                                )
                            else:
                                raise Exception(f"Failed to open DM: {error_msg}")
                    else:
                        raise Exception(f"Failed to open DM channel: HTTP {dm_response.status_code}")
                except Exception as e:
                    self.node.LogEvent("DM Channel Open Error", data={
                        "user_identifier": self.user,
                        "user_id": user_id,
                        "error": str(e)
                    }, error=str(e))
                    raise  # Re-raise the exception with better message
            
            if not channel_id:
                raise Exception("Could not determine channel ID")
            
            # Log the event
            self.node.LogEvent("Sending Slack Message", data={
                "channel": channel_id,
                "message_preview": self.message[:100],
                "connection_method": self.connection_method,
                "send_as": self.send_as
            })
            
            # Send message
            result = self._send_message(
                channel_id=channel_id,
                message=self.message,
                thread_ts=self.thread_ts if self.thread_ts else None
            )
            
            if result.get("ok"):
                response_data = {
                    "status": "success",
                    "channel": result.get("channel"),
                    "ts": result.get("ts"),  # Message timestamp
                    "message": result.get("message"),
                    "response": result,
                    "connection_method": self.connection_method,
                    "send_as": self.send_as
                }
                
                self.node.SetTargetPinData("Response", response_data)
                self.node.LogEvent("Slack Message Sent", data=response_data)
            else:
                error_msg = result.get("error", "Unknown error")
                raise Exception(f"Slack API error: {error_msg}")
        
        except Exception as e:
            error_data = {
                "error": str(e),
                "traceback": traceback.format_exc()
            }
            self.node.LogEvent("Slack Message Failed", data=error_data, error=str(e))
            self.node.SetTargetPinData("Response", error_data)
        
        # Continue workflow chain
        return self.node.TriggerAll()