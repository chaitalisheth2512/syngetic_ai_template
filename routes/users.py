from flask import Blueprint, Flask, request, jsonify, g, Response
from semantic_kernel.functions.kernel_function_decorator import kernel_function
from functools import wraps
from services.chat_service import openai_query, openai_query_withworkflows, conversations_get, conversation_add, message_add, conversation_get
from services.user_service import agent_users_get, all_users_get, user_agent_add, user_agent_remove, agents_get, user_get, user_add

users_bp = Blueprint('users', __name__)

@users_bp.route('/user/<user_id>/agent/<agent_id>',methods=["POST"])
def users_agent_add(user_id:str,agent_id:str) -> Response:
    user_agent_add(agent_id=agent_id,user_id=user_id)
    return jsonify({"response":"Success"})

@users_bp.route('/user/<user_id>/agent/<agent_id>',methods=["DELETE"])
def users_agent_remove(user_id:str,agent_id:str) -> Response:
    user_agent_remove(agent_id=agent_id,user_id=user_id)
    return jsonify({"response":"Success"})

@users_bp.route('/user/myself',methods=["GET"])
def user_get_me_route() -> Response:
    user_email = request.headers.get("x-user-email")
    if user_email is None:
        return jsonify({"error":"User is not authenticated."})
    user = user_get(user_email)
    if user is None:
        user = user_add(email=user_email,display_name=user_email)
    return jsonify(user)

@users_bp.route('/users',methods=["GET"])
def all_users_get_route() -> Response:
    users = all_users_get()
    return jsonify(users)

@users_bp.route('/agent/<agent_id>/users',methods=["GET"])
def agent_users_get_route(agent_id) -> Response:
    users = agent_users_get(agent_id=agent_id)
    return jsonify(users)

