# app/routes/chat.py
import json
from datetime import datetime

from flask import Blueprint, jsonify, request
from flask_login import current_user, login_required

from app import db
from app.models.chat import ChatSession, ChatMessage, ChatUserMemory
from app.utils.errors import error_response
from app.utils.auth_decorators import requires_role

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
    data = request.get_json(silent=True)
    if data is None:data={}
    if not isinstance(data,dict):return error_response('VALIDATION_FAILED',400)
    if not isinstance(data.get('title',''),str) or len(data.get('title',''))>200:
        return error_response('VALIDATION_FAILED',400)
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

    data = request.get_json(silent=True)
    if data is None:data={}
    if not isinstance(data,dict):return error_response('VALIDATION_FAILED',400)
    messages_data = data.get('messages', [])
    if (not isinstance(messages_data,list) or len(messages_data)>20 or
            any(not isinstance(m,dict) or m.get('role') not in ('user','assistant') or
                not isinstance(m.get('content'),str) or len(m['content'])>8000 or m.get('image_url') is not None for m in messages_data)):
        return error_response('VALIDATION_FAILED',400)
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
    data = request.get_json(silent=True)
    if data is None:data={}
    if not isinstance(data,dict):return error_response('VALIDATION_FAILED',400)
    if len(json.dumps(data))>32000:return error_response('VALIDATION_FAILED',400)
    memory = ChatUserMemory.query.filter_by(user_id=current_user.id).first()
    if not memory:
        memory = ChatUserMemory(user_id=current_user.id)
        db.session.add(memory)
    existing = memory.get()
    existing.update(data)
    memory.set(existing)
    db.session.commit()
    return jsonify(memory.get()), 200


@chat_bp.get('/chat/analytics')
@requires_role('admin')
def analytics():
    """Admin-only counts; never return residents' message text or identity."""
    from sqlalchemy import func
    total=ChatMessage.query.count()
    users=ChatMessage.query.filter_by(role='user').count()
    latest=db.session.query(func.max(ChatMessage.created_at)).scalar()
    return jsonify({'totalConvos':ChatSession.query.count(),'totalMsgs':total,
        'userMsgs':users,'botMsgs':total-users,'lastActive':latest.isoformat() if latest else None,
        'topics':{},'fbUp':0,'fbDown':0,'recentDown':[],'hours':[0]*24,'avgRespChars':0,
        'limitations':['Browser-only conversations and feedback are not uploaded or included.']})
