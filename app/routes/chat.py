# app/routes/chat.py
import json
from datetime import datetime

from flask import Blueprint, jsonify, request
from flask_login import current_user, login_required

from app import db
from app.models.chat import ChatSession, ChatMessage, ChatUserMemory
from app.utils.errors import error_response

chat_bp = Blueprint('chat', __name__)


@chat_bp.route('/chat/sessions', methods=['GET'])
@login_required
def list_sessions():
    sessions = ChatSession.query.filter_by(user_id=current_user.id)\
        .order_by(ChatSession.updated_at.desc()).limit(30).all()
    return jsonify([s.to_dict(include_preview=True) for s in sessions]), 200


@chat_bp.route('/chat/sessions', methods=['POST'])
@login_required
def create_session():
    data = request.get_json(silent=True) or {}
    session = ChatSession(user_id=current_user.id, title=data.get('title', ''))
    db.session.add(session)
    db.session.commit()
    return jsonify(session.to_dict()), 201


@chat_bp.route('/chat/sessions/<int:session_id>', methods=['DELETE'])
@login_required
def delete_session(session_id):
    session = ChatSession.query.filter_by(id=session_id, user_id=current_user.id).first()
    if not session:
        return error_response('NOT_FOUND', 404)
    db.session.delete(session)
    db.session.commit()
    return jsonify({'ok': True}), 200


@chat_bp.route('/chat/sessions/<int:session_id>/messages', methods=['GET'])
@login_required
def get_messages(session_id):
    session = ChatSession.query.filter_by(id=session_id, user_id=current_user.id).first()
    if not session:
        return error_response('NOT_FOUND', 404)
    return jsonify([m.to_dict() for m in session.messages]), 200


@chat_bp.route('/chat/sessions/<int:session_id>/messages/batch', methods=['POST'])
@login_required
def add_messages_batch(session_id):
    session = ChatSession.query.filter_by(id=session_id, user_id=current_user.id).first()
    if not session:
        return error_response('NOT_FOUND', 404)

    data = request.get_json(silent=True) or {}
    messages_data = data.get('messages', [])[:20]
    saved = []

    for m in messages_data:
        msg = ChatMessage(
            session_id=session_id,
            role=m.get('role', 'user'),
            content=str(m.get('content', ''))[:8000],
            image_url=m.get('image_url'),
        )
        db.session.add(msg)
        saved.append(msg)

    if saved and not session.title:
        first_user = next((m for m in saved if m.role == 'user'), None)
        if first_user:
            session.title = first_user.content[:80]

    session.updated_at = datetime.utcnow()
    db.session.commit()
    return jsonify([m.to_dict() for m in saved]), 201


@chat_bp.route('/chat/memory', methods=['GET'])
@login_required
def get_memory():
    memory = ChatUserMemory.query.filter_by(user_id=current_user.id).first()
    return jsonify(memory.get() if memory else {}), 200


@chat_bp.route('/chat/memory', methods=['PUT'])
@login_required
def update_memory():
    data = request.get_json(silent=True) or {}
    memory = ChatUserMemory.query.filter_by(user_id=current_user.id).first()
    if not memory:
        memory = ChatUserMemory(user_id=current_user.id)
        db.session.add(memory)
    existing = memory.get()
    existing.update(data)
    memory.set(existing)
    db.session.commit()
    return jsonify(memory.get()), 200
