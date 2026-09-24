from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
import os, sys
from dotenv import load_dotenv
import google.generativeai as genai

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
BACKEND_DIR = os.path.dirname(CURRENT_DIR)
sys.path.append(BACKEND_DIR)

from db import get_db_connection

load_dotenv()

# FIX 1: url_prefix add chesa - migathavi laga /api vastundi
chat_bp = Blueprint('chat', __name__, url_prefix='/api')

try:
    genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
    model = genai.GenerativeModel("gemini-1.5-flash")
except Exception as e:
    print(f"Gemini error: {e}")
    model = None

# --- FIX 2: Frontend kosam /chat/new route add chesa ---
@chat_bp.route('/chat/new', methods=['POST', 'OPTIONS'])
@jwt_required(optional=True)
def new_chat_alias():
    if request.method == 'OPTIONS':
        return jsonify({"status": "ok"}), 200
    conn = None
    try:
        user_id = get_jwt_identity()
        data = request.get_json() or {}
        title = data.get('title', 'New Chat')
        conn = get_db_connection()
        with conn.cursor() as cur:
            cur.execute("INSERT INTO chats (user_id, title) VALUES (%s, %s)", (user_id, title))
            conn.commit()
            chat_id = cur.lastrowid
        return jsonify({"id": chat_id, "title": title, "success": True}), 201
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        if conn: conn.close()

@chat_bp.route('/chats', methods=['GET'])
@jwt_required()
def get_chats():
    conn = None
    try:
        user_id = get_jwt_identity()
        conn = get_db_connection()
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM chats WHERE user_id=%s ORDER BY updated_at DESC", (user_id,))
            chats = cur.fetchall()
        return jsonify(chats), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        if conn: conn.close()

@chat_bp.route('/chats', methods=['POST'])
@jwt_required()
def create_chat():
    conn = None
    try:
        user_id = get_jwt_identity()
        data = request.get_json() or {}
        title = data.get('title', 'New Chat')
        conn = get_db_connection()
        with conn.cursor() as cur:
            cur.execute("INSERT INTO chats (user_id, title) VALUES (%s, %s)", (user_id, title))
            conn.commit()
            chat_id = cur.lastrowid
        return jsonify({"id": chat_id, "title": title}), 201
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        if conn: conn.close()

@chat_bp.route('/chats/<int:chat_id>/messages', methods=['GET'])
@jwt_required()
def get_messages(chat_id):
    conn = None
    try:
        user_id = get_jwt_identity()
        conn = get_db_connection()
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM messages WHERE chat_id=%s ORDER BY created_at ASC", (chat_id,))
            msgs = cur.fetchall()
        return jsonify(msgs), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        if conn: conn.close()

@chat_bp.route('/chats/<int:chat_id>/messages', methods=['POST'])
@jwt_required()
def send_message(chat_id):
    conn = None
    try:
        user_id = get_jwt_identity()
        data = request.get_json()
        user_msg = data.get('message', '')
        if not model:
            return jsonify({"error": "Gemini API Key ledu .env lo"}), 500
        response = model.generate_content(user_msg)
        ai_reply = response.text
        conn = get_db_connection()
        with conn.cursor() as cur:
            cur.execute("INSERT INTO messages (chat_id, user_id, role, content) VALUES (%s, %s, 'user', %s)", (chat_id, user_id, user_msg))
            cur.execute("INSERT INTO messages (chat_id, user_id, role, content) VALUES (%s, %s, 'assistant', %s)", (chat_id, user_id, ai_reply))
            cur.execute("UPDATE chats SET updated_at=NOW() WHERE id=%s", (chat_id,))
            conn.commit()
        return jsonify({"reply": ai_reply}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        if conn: conn.close()

@chat_bp.route('/chats/<int:chat_id>', methods=['DELETE'])
@jwt_required()
def delete_chat(chat_id):
    conn = None
    try:
        user_id = get_jwt_identity()
        conn = get_db_connection()
        with conn.cursor() as cur:
            cur.execute("DELETE FROM messages WHERE chat_id=%s", (chat_id,))
            cur.execute("DELETE FROM chats WHERE id=%s AND user_id=%s", (chat_id, user_id))
            conn.commit()
        return jsonify({"msg": "Deleted"}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        if conn: conn.close()