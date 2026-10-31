# app/routes/news.py
# Responsibility: News lookup endpoint for assistant context.

from flask import Blueprint, jsonify, request

from app.services.news_service import search_news
from app.utils.errors import error_response

news_bp = Blueprint('news', __name__)


@news_bp.get('/news/search')
def search_recent_news():
    """
    Purpose: Return recent news items for local incident questions.
    Expected query params: q=search terms, limit=1..10
    """
    query = request.args.get('q', '').strip()
    limit = request.args.get('limit', 5, type=int)
    if len(query) > 160:
        return error_response('VALIDATION_FAILED', 400, {'detail': 'Search query is too long.'})

    try:
        items = search_news(query, limit=limit)
    except Exception:
        return error_response('SERVER_ERROR', 502, {'detail': 'News search request failed.'})

    return jsonify({
        'query': query,
        'items': items,
    }), 200
