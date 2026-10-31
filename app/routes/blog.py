from flask import Blueprint, request, jsonify
from flask_login import current_user
from datetime import datetime
import re

from app import db
from app.models.blog import BlogPost
from app.utils.errors import error_response
from app.utils.auth_decorators import requires_role

blog_bp = Blueprint('blog', __name__)


def _slugify(text):
    slug = text.lower()
    slug = re.sub(r'[^\w\s-]', '', slug)
    slug = re.sub(r'[\s_-]+', '-', slug)
    return slug.strip('-')


def _unique_slug(title, exclude_id=None):
    base = _slugify(title)
    slug = base
    n = 1
    while True:
        q = BlogPost.query.filter_by(slug=slug)
        if exclude_id:
            q = q.filter(BlogPost.id != exclude_id)
        if not q.first():
            return slug
        slug = f'{base}-{n}'
        n += 1


@blog_bp.route('/blog', methods=['GET'])
def list_posts():
    show_all = request.args.get('all') == '1'
    if show_all:
        if not current_user.is_authenticated:
            return error_response('UNAUTHORIZED', 401)
        if current_user.role != 'admin':
            return error_response('FORBIDDEN', 403)

    q = BlogPost.query
    if not show_all:
        q = q.filter_by(published=True)
    posts = q.order_by(BlogPost.created_at.desc()).all()
    return jsonify({'posts': [p.to_dict(include_content=False) for p in posts]}), 200


@blog_bp.route('/blog/<slug>', methods=['GET'])
def get_post(slug):
    post = BlogPost.query.filter_by(slug=slug).first()
    if not post:
        return error_response('NOT_FOUND', 404)
    if not post.published:
        if not current_user.is_authenticated or current_user.role != 'admin':
            return error_response('NOT_FOUND', 404)
    return jsonify({'post': post.to_dict()}), 200


@blog_bp.route('/blog', methods=['POST'])
@requires_role('admin')
def create_post():
    data = request.get_json(silent=True) or {}
    title = (data.get('title') or '').strip()
    if not title:
        return error_response('VALIDATION_FAILED', 400, {'detail': 'title is required'})

    raw_slug = (data.get('slug') or '').strip()
    if raw_slug:
        slug = _slugify(raw_slug)
        if BlogPost.query.filter_by(slug=slug).first():
            return error_response('VALIDATION_FAILED', 400, {'detail': 'slug already exists'})
    else:
        slug = _unique_slug(title)

    # Role-authenticated writes always have a database-backed author.
    author_id = current_user.id if current_user.is_authenticated else None
    post = BlogPost(
        title           = title,
        slug            = slug,
        content         = data.get('content') or '',
        excerpt         = data.get('excerpt') or None,
        cover_image_url = data.get('cover_image_url') or None,
        published       = bool(data.get('published', False)),
        author_id       = author_id,
    )
    db.session.add(post)
    db.session.commit()
    return jsonify({'post': post.to_dict(), 'message': 'Post created.'}), 201


@blog_bp.route('/blog/<int:post_id>', methods=['PATCH'])
@requires_role('admin')
def update_post(post_id):
    post = BlogPost.query.get(post_id)
    if not post:
        return error_response('NOT_FOUND', 404)

    data = request.get_json(silent=True) or {}

    if 'title' in data:
        title = (data['title'] or '').strip()
        if title:
            post.title = title

    if 'slug' in data and data['slug']:
        new_slug = _slugify(data['slug'].strip())
        if new_slug != post.slug:
            if BlogPost.query.filter(BlogPost.slug == new_slug, BlogPost.id != post_id).first():
                return error_response('VALIDATION_FAILED', 400, {'detail': 'slug already exists'})
            post.slug = new_slug

    if 'content' in data:
        post.content = data['content']
    if 'excerpt' in data:
        post.excerpt = data['excerpt'] or None
    if 'cover_image_url' in data:
        post.cover_image_url = data['cover_image_url'] or None
    if 'published' in data:
        post.published = bool(data['published'])

    post.updated_at = datetime.utcnow()
    db.session.commit()
    return jsonify({'post': post.to_dict(), 'message': 'Post updated.'}), 200


@blog_bp.route('/blog/<int:post_id>', methods=['DELETE'])
@requires_role('admin')
def delete_post(post_id):
    post = BlogPost.query.get(post_id)
    if not post:
        return error_response('NOT_FOUND', 404)
    db.session.delete(post)
    db.session.commit()
    return jsonify({'message': 'Post deleted.'}), 200
