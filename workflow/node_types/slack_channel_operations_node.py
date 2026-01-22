# workflow/node_types/slack_channel_operations_node.py

from workflow.workflow_datatypes import Pin, NodeConfig, FieldType
from workflow.workflow_executor import Node
import requests
import json
import traceback
from jinja2 import Template

class slack_channel_operations_node:

    default_setup: NodeConfig = {
        "id": "SlackChannelOperations",
        "name": "Slack Channel Operations",
        "description": "Perform channel operations: Create, Join, Archive, Invite, List, and more (like n8n)",
        "pins": {
            "trigger_pins": [{"name": "Start"}],
            "input_pins": [{"name": "Channel Data"}],
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
                "label": "OAuth Bot Token (from OAuth flow)",
                "type": FieldType.SINGLE_LINE,
                "width": "100%"
            },
            {
                "id": "OAuthUserToken",
                "label": "OAuth User Token (from OAuth flow)",
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
                "label": "Slack Bot Token (if using Access Token method)",
                "type": FieldType.SINGLE_LINE,
                "width": "100%"
            },
            {
                "id": "UserToken",
                "label": "Slack User Token (if using Access Token method)",
                "type": FieldType.SINGLE_LINE,
                "width": "100%"
            },
            
            # ============================================
            # OPERATION SELECTION
            # ============================================
            {
                "id": "Operation",
                "label": "Operation",
                "type": FieldType.SINGLE_SELECT,
                "width": "100%",
                "options": [
                    "Create Channel",
                    "Join Channel",
                    "Leave Channel",
                    "Archive Channel",
                    "Unarchive Channel",
                    "Rename Channel",
                    "Set Topic",
                    "Set Purpose",
                    "Invite Users",
                    "Remove User",
                    "List Channels",
                    "Get Channel Info",
                    "List Members",
                    "Get Channel History",
                    # "Get Thread"
                ]
            },
            
            # ============================================
            # SEND AS CONFIGURATION
            # ============================================
            {
                "id": "SendAs",
                "label": "Perform operations as",
                "type": FieldType.SINGLE_SELECT,
                "width": "100%",
                "options": ["Bot", "User"]
            },
            
            # ============================================
            # CHANNEL FIELDS (for most operations)
            # ============================================
            {
                "id": "Channel",
                "label": "Channel (name or ID, e.g., #general or C123456)",
                "type": FieldType.SINGLE_LINE,
                "width": "50%"
            },
            
            # ============================================
            # CREATE CHANNEL FIELDS
            # ============================================
            {
                "id": "ChannelName",
                "label": "Channel Name (for Create operation)",
                "type": FieldType.SINGLE_LINE,
                "width": "50%"
            },
            {
                "id": "IsPrivate",
                "label": "Private Channel (for Create operation)",
                "type": FieldType.SINGLE_SELECT,
                "width": "50%",
                "options": ["Public", "Private"]
            },
            
            # ============================================
            # USER FIELDS (for Invite/Remove)
            # ============================================
            {
                "id": "Users",
                "label": "User IDs or Emails (comma-separated, for Invite/Remove)",
                "type": FieldType.TEXT,
                "width": "100%"
            },
            
            # ============================================
            # RENAME/SET TOPIC/PURPOSE FIELDS
            # ============================================
            {
                "id": "NewName",
                "label": "New Channel Name (for Rename operation)",
                "type": FieldType.SINGLE_LINE,
                "width": "50%"
            },
            {
                "id": "Topic",
                "label": "Topic (for Set Topic operation)",
                "type": FieldType.SINGLE_LINE,
                "width": "100%"
            },
            {
                "id": "Purpose",
                "label": "Purpose (for Set Purpose operation)",
                "type": FieldType.SINGLE_LINE,
                "width": "100%"
            },
            
            # ============================================
            # HISTORY/THREAD FIELDS
            # ============================================
            {
                "id": "Limit",
                "label": "Limit (for History/Thread operations, default: 100)",
                "type": FieldType.SINGLE_LINE,
                "width": "50%"
            },
            {
                "id": "Oldest",
                "label": "Oldest Timestamp (for History, optional)",
                "type": FieldType.SINGLE_LINE,
                "width": "50%"
            },
            {
                "id": "Latest",
                "label": "Latest Timestamp (for History, optional)",
                "type": FieldType.SINGLE_LINE,
                "width": "50%"
            },
            {
                "id": "ThreadTS",
                "label": "Thread Timestamp (for Get Thread operation)",
                "type": FieldType.SINGLE_LINE,
                "width": "50%"
            },
            
            # ============================================
            # DM FIELDS
            # ============================================
            {
                "id": "DMUser",
                "label": "User ID or Email (for Open/Close DM)",
                "type": FieldType.SINGLE_LINE,
                "width": "50%"
            },
            {
                "id": "DMChannel",
                "label": "DM Channel ID (for Close DM)",
                "type": FieldType.SINGLE_LINE,
                "width": "50%"
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
        self.oauth_access_token = cfg.get("OAuthAccessToken", "")
        self.oauth_user_token = cfg.get("OAuthUserToken", "")
        self.oauth_refresh_token = cfg.get("OAuthRefreshToken", "")
        
        # Access Token (direct method)
        self.access_token = cfg.get("AccessToken", "")
        self.user_token = cfg.get("UserToken", "")
        
        # Operation
        self.operation = cfg.get("Operation", "List Channels")
        
        # Send as configuration
        self.send_as = cfg.get("SendAs", "Bot")  # "Bot" or "User"
        
        # Channel fields
        self.channel = cfg.get("Channel", "")
        self.channel_name = cfg.get("ChannelName", "")
        self.is_private = cfg.get("IsPrivate", "Public")
        
        # User fields
        self.users = cfg.get("Users", "")
        
        # Rename/Topic/Purpose
        self.new_name = cfg.get("NewName", "")
        self.topic = cfg.get("Topic", "")
        self.purpose = cfg.get("Purpose", "")
        
        # History/Thread
        self.limit = cfg.get("Limit", "100")
        self.oldest = cfg.get("Oldest", "")
        self.latest = cfg.get("Latest", "")
        self.thread_ts = cfg.get("ThreadTS", "")
        
        # DM fields
        self.dm_user = cfg.get("DMUser", "")
        self.dm_channel = cfg.get("DMChannel", "")

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
                        "message": "User Token not provided, falling back to Bot Token. Operation will be performed as bot."
                    })
                    return self.oauth_access_token or self.access_token
            else:
                if self.user_token:
                    return self.user_token
                else:
                    # Fallback to bot token with warning
                    self.node.LogEvent("Warning", data={
                        "message": "User Token not provided, falling back to Bot Token. Operation will be performed as bot."
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
            self.node.LogEvent("Channel Lookup Error", data={}, error=str(e))
        
        # If not found, return as-is (might be an ID)
        return channel_name

    def _get_user_ids(self, users_string: str, access_token: str) -> list:
        """Convert comma-separated user emails/names to user IDs"""
        if not users_string:
            return []
        
        user_identifiers = [u.strip() for u in users_string.split(',')]
        user_ids = []
        
        try:
            response = requests.get(
                "https://slack.com/api/users.list",
                headers={"Authorization": f"Bearer {access_token}"}
            )
            if response.ok:
                data = response.json()
                if data.get("ok"):
                    for identifier in user_identifiers:
                        # If already a user ID, use it
                        if identifier.startswith('U') and len(identifier) > 8:
                            user_ids.append(identifier)
                            continue
                        
                        # Try to find user
                        identifier_lower = identifier.lower().strip()
                        for user in data.get("members", []):
                            if user.get("deleted") or user.get("is_bot"):
                                continue
                            
                            profile = user.get("profile", {})
                            user_name = user.get("name", "").lower()
                            real_name = user.get("real_name", "").lower()
                            user_email = profile.get("email", "").lower()
                            user_id = user.get("id", "")
                            
                            if (identifier_lower == user_name or 
                                identifier_lower == real_name or
                                identifier_lower == user_email or
                                identifier_lower == user_id.lower()):
                                user_ids.append(user_id)
                                break
        except Exception as e:
            self.node.LogEvent("User Lookup Error", data={}, error=str(e))
        
        return user_ids

    def _call_slack_api(self, method: str, endpoint: str, payload: dict = None) -> dict:
        """Make a Slack API call"""
        access_token = self._get_active_token()
        
        if not access_token:
            raise Exception("No access token available. Please configure OAuth Access Token or Access Token.")
        
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json"
        }
        
        url = f"https://slack.com/api/{endpoint}"
        
        if method.upper() == "GET":
            response = requests.get(url, headers=headers, params=payload or {})
        else:
            response = requests.post(url, headers=headers, json=payload or {})
        
        if response.ok:
            return response.json()
        else:
            raise Exception(f"Slack API error: {response.status_code} - {response.text}")

    def Run(self, connection, data):
        response_data = {}
        
        try:
            access_token = self._get_active_token()
            if not access_token:
                raise Exception("No access token available. Please configure OAuth Access Token or Access Token.")
            
            operation = self.operation
            
            # ============================================
            # CREATE CHANNEL
            # ============================================
            if operation == "Create Channel":
                if not self.channel_name:
                    raise Exception("Channel Name is required for Create Channel operation")
                
                payload = {
                    "name": self.channel_name,
                    "is_private": self.is_private == "Private"
                }
                
                result = self._call_slack_api("POST", "conversations.create", payload)
                
                if result.get("ok"):
                    channel_info = result.get("channel", {})
                    channel_id = channel_info.get("id")
                    
                    # Store response data initially
                    response_data = {
                        "status": "success",
                        "operation": "Create Channel",
                        "channel": channel_info,
                        "response": result
                    }
                    
                    # Automatically invite users if provided
                    if self.users:
                        try:
                            user_ids = self._get_user_ids(self.users, access_token)
                            if user_ids:
                                invite_payload = {
                                    "channel": channel_id,
                                    "users": ",".join(user_ids)
                                }
                                invite_result = self._call_slack_api("POST", "conversations.invite", invite_payload)
                                response_data["invitation"] = {
                                    "ok": invite_result.get("ok"),
                                    "user_ids": user_ids,
                                    "response": invite_result
                                }
                                if not invite_result.get("ok"):
                                    self.node.LogEvent("Channel Invitation Failed", 
                                                      data={"error": invite_result.get("error")}, 
                                                      error=invite_result.get("error"))
                        except Exception as invite_err:
                            self.node.LogEvent("Channel Invitation Error", 
                                              data={"error": str(invite_err)}, 
                                              error=str(invite_err))
                            response_data["invitation_error"] = str(invite_err)
                else:
                    raise Exception(f"Slack API error: {result.get('error', 'Unknown error')}")
            
            # ============================================
            # JOIN CHANNEL
            # ============================================
            elif operation == "Join Channel":
                if not self.channel:
                    raise Exception("Channel is required for Join Channel operation")
                
                channel_id = self._get_channel_id(self.channel, access_token)
                payload = {"channel": channel_id}
                
                result = self._call_slack_api("POST", "conversations.join", payload)
                
                if result.get("ok"):
                    response_data = {
                        "status": "success",
                        "operation": "Join Channel",
                        "channel": result.get("channel", {}),
                        "response": result
                    }
                else:
                    raise Exception(f"Slack API error: {result.get('error', 'Unknown error')}")
            
            # ============================================
            # LEAVE CHANNEL
            # ============================================
            elif operation == "Leave Channel":
                if not self.channel:
                    raise Exception("Channel is required for Leave Channel operation")
                
                channel_id = self._get_channel_id(self.channel, access_token)
                payload = {"channel": channel_id}
                
                result = self._call_slack_api("POST", "conversations.leave", payload)
                
                if result.get("ok"):
                    response_data = {
                        "status": "success",
                        "operation": "Leave Channel",
                        "response": result
                    }
                else:
                    raise Exception(f"Slack API error: {result.get('error', 'Unknown error')}")
            
            # ============================================
            # ARCHIVE CHANNEL
            # ============================================
            elif operation == "Archive Channel":
                if not self.channel:
                    raise Exception("Channel is required for Archive Channel operation")
                
                channel_id = self._get_channel_id(self.channel, access_token)
                payload = {"channel": channel_id}
                
                result = self._call_slack_api("POST", "conversations.archive", payload)
                
                if result.get("ok"):
                    response_data = {
                        "status": "success",
                        "operation": "Archive Channel",
                        "response": result
                    }
                else:
                    raise Exception(f"Slack API error: {result.get('error', 'Unknown error')}")
            
            # ============================================
            # UNARCHIVE CHANNEL
            # ============================================
            elif operation == "Unarchive Channel":
                if not self.channel:
                    raise Exception("Channel is required for Unarchive Channel operation")
                
                channel_id = self._get_channel_id(self.channel, access_token)
                payload = {"channel": channel_id}
                
                result = self._call_slack_api("POST", "conversations.unarchive", payload)
                
                if result.get("ok"):
                    response_data = {
                        "status": "success",
                        "operation": "Unarchive Channel",
                        "response": result
                    }
                else:
                    raise Exception(f"Slack API error: {result.get('error', 'Unknown error')}")
            
            # ============================================
            # RENAME CHANNEL
            # ============================================
            elif operation == "Rename Channel":
                if not self.channel:
                    raise Exception("Channel is required for Rename Channel operation")
                if not self.new_name:
                    raise Exception("New Channel Name is required for Rename Channel operation")
                
                channel_id = self._get_channel_id(self.channel, access_token)
                payload = {
                    "channel": channel_id,
                    "name": self.new_name
                }
                
                result = self._call_slack_api("POST", "conversations.rename", payload)
                
                if result.get("ok"):
                    response_data = {
                        "status": "success",
                        "operation": "Rename Channel",
                        "channel": result.get("channel", {}),
                        "response": result
                    }
                else:
                    raise Exception(f"Slack API error: {result.get('error', 'Unknown error')}")
            
            # ============================================
            # SET TOPIC
            # ============================================
            elif operation == "Set Topic":
                if not self.channel:
                    raise Exception("Channel is required for Set Topic operation")
                
                channel_id = self._get_channel_id(self.channel, access_token)
                payload = {
                    "channel": channel_id,
                    "topic": self.topic or ""
                }
                
                result = self._call_slack_api("POST", "conversations.setTopic", payload)
                
                if result.get("ok"):
                    response_data = {
                        "status": "success",
                        "operation": "Set Topic",
                        "channel": result.get("channel", {}),
                        "topic": result.get("topic", ""),
                        "response": result
                    }
                else:
                    raise Exception(f"Slack API error: {result.get('error', 'Unknown error')}")
            
            # ============================================
            # SET PURPOSE
            # ============================================
            elif operation == "Set Purpose":
                if not self.channel:
                    raise Exception("Channel is required for Set Purpose operation")
                
                channel_id = self._get_channel_id(self.channel, access_token)
                payload = {
                    "channel": channel_id,
                    "purpose": self.purpose or ""
                }
                
                result = self._call_slack_api("POST", "conversations.setPurpose", payload)
                
                if result.get("ok"):
                    response_data = {
                        "status": "success",
                        "operation": "Set Purpose",
                        "channel": result.get("channel", {}),
                        "purpose": result.get("purpose", ""),
                        "response": result
                    }
                else:
                    raise Exception(f"Slack API error: {result.get('error', 'Unknown error')}")
            
            # ============================================
            # INVITE USERS
            # ============================================
            elif operation == "Invite Users":
                target_channel = self.channel or self.channel_name
                if not target_channel:
                    raise Exception("Channel or Channel Name is required for Invite Users operation")
                if not self.users:
                    raise Exception("Users are required for Invite Users operation")
                
                channel_id = self._get_channel_id(target_channel, access_token)
                user_ids = self._get_user_ids(self.users, access_token)
                
                if not user_ids:
                    raise Exception("Could not find any valid users. Please check user IDs or emails.")
                
                payload = {
                    "channel": channel_id,
                    "users": ",".join(user_ids)
                }
                
                result = self._call_slack_api("POST", "conversations.invite", payload)
                
                if result.get("ok"):
                    response_data = {
                        "status": "success",
                        "operation": "Invite Users",
                        "channel": result.get("channel", {}),
                        "response": result
                    }
                else:
                    raise Exception(f"Slack API error: {result.get('error', 'Unknown error')}")
            
            # ============================================
            # REMOVE USER
            # ============================================
            elif operation == "Remove User":
                target_channel = self.channel or self.channel_name
                if not target_channel:
                    raise Exception("Channel or Channel Name is required for Remove User operation")
                if not self.users:
                    raise Exception("User is required for Remove User operation")
                
                channel_id = self._get_channel_id(target_channel, access_token)
                user_ids = self._get_user_ids(self.users, access_token)
                
                if not user_ids:
                    raise Exception("Could not find valid user. Please check user ID or email.")
                
                payload = {
                    "channel": channel_id,
                    "user": user_ids[0]  # Remove first user
                }
                
                result = self._call_slack_api("POST", "conversations.kick", payload)
                
                if result.get("ok"):
                    response_data = {
                        "status": "success",
                        "operation": "Remove User",
                        "response": result
                    }
                else:
                    raise Exception(f"Slack API error: {result.get('error', 'Unknown error')}")
            
            # ============================================
            # LIST CHANNELS
            # ============================================
            elif operation == "List Channels":
                all_channels = []
                cursor = None
                
                while True:
                    params = {
                        "types": "public_channel,private_channel",
                        "exclude_archived": True,
                        "limit": 1000  # Request max possible per page
                    }
                    if cursor:
                        params["cursor"] = cursor
                        
                    result = self._call_slack_api("GET", "conversations.list", params)
                    
                    if result.get("ok"):
                        all_channels.extend(result.get("channels", []))
                        
                        # Check for next page
                        cursor = result.get("response_metadata", {}).get("next_cursor")
                        if not cursor:
                            break
                    else:
                        raise Exception(f"Slack API error during pagination: {result.get('error', 'Unknown error')}")
                
                response_data = {
                    "status": "success",
                    "operation": "List Channels",
                    "channels": all_channels,
                    "count": len(all_channels)
                }
            
            # ============================================
            # GET CHANNEL INFO
            # ============================================
            elif operation == "Get Channel Info":
                if not self.channel:
                    raise Exception("Channel is required for Get Channel Info operation")
                
                channel_id = self._get_channel_id(self.channel, access_token)
                params = {"channel": channel_id}
                
                result = self._call_slack_api("GET", "conversations.info", params)
                
                if result.get("ok"):
                    response_data = {
                        "status": "success",
                        "operation": "Get Channel Info",
                        "channel": result.get("channel", {}),
                        "response": result
                    }
                else:
                    raise Exception(f"Slack API error: {result.get('error', 'Unknown error')}")
            
            # ============================================
            # LIST MEMBERS
            # ============================================
            elif operation == "List Members":
                if not self.channel:
                    raise Exception("Channel is required for List Members operation")
                
                channel_id = self._get_channel_id(self.channel, access_token)
                all_members = []
                cursor = None
                
                while True:
                    params = {
                        "channel": channel_id,
                        "limit": 1000
                    }
                    if cursor:
                        params["cursor"] = cursor
                        
                    result = self._call_slack_api("GET", "conversations.members", params)
                    
                    if result.get("ok"):
                        all_members.extend(result.get("members", []))
                        cursor = result.get("response_metadata", {}).get("next_cursor")
                        if not cursor:
                            break
                    else:
                        raise Exception(f"Slack API error during pagination: {result.get('error', 'Unknown error')}")
                
                response_data = {
                    "status": "success",
                    "operation": "List Members",
                    "members": all_members,
                    "count": len(all_members)
                }
            
            # ============================================
            # GET CHANNEL HISTORY
            # ============================================
            elif operation == "Get Channel History":
                if not self.channel:
                    raise Exception("Channel is required for Get Channel History operation")
                
                channel_id = self._get_channel_id(self.channel, access_token)
                all_messages = []
                cursor = None
                target_limit = int(self.limit) if self.limit else 0
                
                while True:
                    params = {
                        "channel": channel_id,
                        "limit": 1000 if not target_limit or target_limit > 1000 else target_limit
                    }
                    if cursor:
                        params["cursor"] = cursor
                    if self.oldest:
                        params["oldest"] = self.oldest
                    if self.latest:
                        params["latest"] = self.latest
                        
                    result = self._call_slack_api("GET", "conversations.history", params)
                    
                    if result.get("ok"):
                        messages = result.get("messages", [])
                        all_messages.extend(messages)
                        
                        # Stop if we reached the requested limit
                        if target_limit and len(all_messages) >= target_limit:
                            all_messages = all_messages[:target_limit]
                            break
                            
                        cursor = result.get("response_metadata", {}).get("next_cursor")
                        if not cursor:
                            break
                    else:
                        raise Exception(f"Slack API error during pagination: {result.get('error', 'Unknown error')}")
                
                response_data = {
                    "status": "success",
                    "operation": "Get Channel History",
                    "messages": all_messages,
                    "count": len(all_messages)
                }
            
            # ============================================
            # GET THREAD
            # ============================================
            elif operation == "Get Thread":
                if not self.channel:
                    raise Exception("Channel is required for Get Thread operation")
                if not self.thread_ts:
                    raise Exception("Thread Timestamp is required for Get Thread operation")
                
                channel_id = self._get_channel_id(self.channel, access_token)
                all_messages = []
                cursor = None
                target_limit = int(self.limit) if self.limit else 0
                
                while True:
                    params = {
                        "channel": channel_id,
                        "ts": self.thread_ts,
                        "limit": 1000 if not target_limit or target_limit > 1000 else target_limit
                    }
                    if cursor:
                        params["cursor"] = cursor
                        
                    result = self._call_slack_api("GET", "conversations.replies", params)
                    
                    if result.get("ok"):
                        messages = result.get("messages", [])
                        all_messages.extend(messages)
                        
                        # Stop if we reached requested limit
                        if target_limit and len(all_messages) >= target_limit:
                            all_messages = all_messages[:target_limit]
                            break
                            
                        cursor = result.get("response_metadata", {}).get("next_cursor")
                        if not cursor:
                            break
                    else:
                        raise Exception(f"Slack API error during pagination: {result.get('error', 'Unknown error')}")
                
                response_data = {
                    "status": "success",
                    "operation": "Get Thread",
                    "messages": all_messages,
                    "count": len(all_messages)
                }
            
            # ============================================
            # OPEN DM
            # ============================================
            elif operation == "Open DM":
                if not self.dm_user:
                    raise Exception("User is required for Open DM operation")
                
                user_ids = self._get_user_ids(self.dm_user, access_token)
                if not user_ids:
                    raise Exception("Could not find valid user. Please check user ID or email.")
                
                payload = {"users": user_ids[0]}
                
                result = self._call_slack_api("POST", "conversations.open", payload)
                
                if result.get("ok"):
                    response_data = {
                        "status": "success",
                        "operation": "Open DM",
                        "channel": result.get("channel", {}),
                        "response": result
                    }
                else:
                    raise Exception(f"Slack API error: {result.get('error', 'Unknown error')}")
            
            # ============================================
            # CLOSE DM
            # ============================================
            elif operation == "Close DM":
                if not self.dm_channel:
                    raise Exception("DM Channel ID is required for Close DM operation")
                
                payload = {"channel": self.dm_channel}
                
                result = self._call_slack_api("POST", "conversations.close", payload)
                
                if result.get("ok"):
                    response_data = {
                        "status": "success",
                        "operation": "Close DM",
                        "response": result
                    }
                else:
                    raise Exception(f"Slack API error: {result.get('error', 'Unknown error')}")
            
            else:
                raise Exception(f"Unknown operation: {operation}")  
            
            # Set output data
            self.node.SetTargetPinData("Response", response_data)
            self.node.LogEvent("Slack Channel Operation Success", data=response_data)
        
        except Exception as e:
            error_data = {
                "error": str(e),
                "operation": self.operation,
                "traceback": traceback.format_exc()
            }
            self.node.LogEvent("Slack Channel Operation Failed", data=error_data, error=str(e))
            self.node.SetTargetPinData("Response", error_data)
        
        # Continue workflow chain
        return self.node.TriggerAll()