# app/services/news_service.py
# Responsibility: Lightweight news lookup for recent incident context.

from email.utils import parsedate_to_datetime
from html import unescape
import re
from urllib.parse import urlencode
import xml.etree.ElementTree as ET

import requests


NEWS_SEARCH_BASE = 'https://news.google.com/rss/search'
DEFAULT_QUERY = 'Poway CA wildfire OR brush fire'


def search_news(query, limit=5):
    """Return recent news results from Google News RSS."""
    query = (query or DEFAULT_QUERY).strip()[:160]
    if not query:
        query = DEFAULT_QUERY

    params = urlencode({
        'q': query,
        'hl': 'en-US',
        'gl': 'US',
        'ceid': 'US:en',
    })
    response = requests.get(f'{NEWS_SEARCH_BASE}?{params}', timeout=8)
    response.raise_for_status()

    root = ET.fromstring(response.content)
    items = []
    for item in root.findall('./channel/item')[:max(1, min(limit, 10))]:
        title = _text(item, 'title')
        link = _text(item, 'link')
        description = _clean_description(_text(item, 'description'))
        published = _format_pub_date(_text(item, 'pubDate'))
        source = item.find('source')
        source_name = source.text.strip() if source is not None and source.text else ''
        if title and link:
            items.append({
                'title': title,
                'url': link,
                'source': source_name,
                'published': published,
                'summary': description,
            })

    return items


def _text(node, tag):
    child = node.find(tag)
    return child.text.strip() if child is not None and child.text else ''


def _format_pub_date(value):
    if not value:
        return ''
    try:
        return parsedate_to_datetime(value).date().isoformat()
    except (TypeError, ValueError):
        return value


def _clean_description(value):
    if not value:
        return ''
    text = re.sub(r'<[^>]+>', ' ', value)
    text = unescape(text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text[:500]
