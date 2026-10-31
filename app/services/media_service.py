# app/services/media_service.py
# Responsibility: Media upload business logic — validate, save file, persist record.

import os
import secrets
from werkzeug.utils import secure_filename
from flask import current_app
from app import db
from app.models.media import MediaPost

ALLOWED_IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.gif', '.webp'}
ALLOWED_VIDEO_EXTENSIONS = {'.mp4', '.mov', '.webm'}


def allowed_file(filename):
    """
    Purpose: Check whether a filename has an allowed media extension.
    @param {str} filename - Original filename from the upload
    @returns {bool} True if the extension is permitted
    """
    _, ext = os.path.splitext(filename.lower())
    return ext in ALLOWED_IMAGE_EXTENSIONS | ALLOWED_VIDEO_EXTENSIONS


def determine_media_type(filename):
    """
    Purpose: Return 'image' or 'video' based on file extension.
    @param {str} filename - Filename to inspect
    @returns {str} 'image' or 'video'
    """
    _, ext = os.path.splitext(filename.lower())
    return 'video' if ext in ALLOWED_VIDEO_EXTENSIONS else 'image'


def save_uploaded_file(file_storage):
    """
    Purpose: Save a Werkzeug FileStorage object to the upload folder.
    @param {FileStorage} file_storage - The uploaded file object from request.files
    @returns {tuple} (relative_url, None) on success, (None, error_key) on failure
    Algorithm:
    1. Validate file is present and allowed
    2. Create an exclusive random filename in the configured upload directory
    3. Save the file
    4. Return the relative URL path
    """
    if not file_storage or not file_storage.filename:
        return None, 'UPLOAD_FAILED'

    filename = secure_filename(file_storage.filename)
    if not allowed_file(filename):
        return None, 'VALIDATION_FAILED'

    upload_folder = current_app.config.get('UPLOAD_FOLDER', 'instance/uploads')
    os.makedirs(upload_folder, exist_ok=True)

    # Exclusive creation prevents overwrites even if a random-name collision
    # occurs. Original names are not exposed as filesystem paths.
    extension = os.path.splitext(filename)[1].lower()
    for _ in range(5):
        stored_name = secrets.token_hex(16) + extension
        save_path = os.path.join(upload_folder, stored_name)
        try:
            target = open(save_path, 'xb')
        except FileExistsError:
            continue
        try:
            with target:
                file_storage.save(target)
        except Exception:
            os.unlink(save_path)
            raise
        relative_url = f'/static/uploads/{stored_name}'
        break
    else:
        return None, 'UPLOAD_FAILED'

    return relative_url, None


def create_media_post(title, caption, media_url, media_type, uploaded_by=None, event_id=None):
    """
    Purpose: Persist a new MediaPost record after the file has been saved.
    @param {str}      title       - Post title (required)
    @param {str}      caption     - Optional caption text
    @param {str}      media_url   - Relative URL to the saved file
    @param {str}      media_type  - 'image' or 'video'
    @param {int|None} uploaded_by - User FK
    @param {int|None} event_id    - Optional event FK
    @returns {tuple} (MediaPost dict, None) on success, (None, error_key) on failure
    """
    if not title or not media_url:
        return None, 'VALIDATION_FAILED'

    post = MediaPost(
        title=title.strip(),
        caption=(caption or '').strip(),
        media_url=media_url,
        media_type=media_type,
        uploaded_by=uploaded_by,
        event_id=event_id,
    )
    db.session.add(post)
    db.session.commit()
    return post.to_dict(), None


def get_media_posts(page=1, per_page=12):
    """
    Purpose: Return a paginated list of media posts ordered newest first.
    @param {int} page     - Page number (1-indexed)
    @param {int} per_page - Items per page
    @returns {dict} { posts, total, page, pages }
    """
    pagination = (MediaPost.query
                  .order_by(MediaPost.created_at.desc())
                  .paginate(page=page, per_page=per_page, error_out=False))
    return {
        'posts': [p.to_dict() for p in pagination.items],
        'total': pagination.total,
        'page':  pagination.page,
        'pages': pagination.pages,
    }
