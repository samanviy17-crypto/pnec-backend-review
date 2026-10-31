# app/routes/media.py
# Responsibility: Media API endpoints — upload file, list posts.

from flask import Blueprint, request, jsonify, current_app, send_from_directory
from flask_login import current_user

from app.services import media_service
from app.utils.errors import error_response
from app.utils.auth_decorators import requires_role

media_bp = Blueprint('media', __name__)


@media_bp.route('/media', methods=['GET'])
def get_media():
    """Return paginated media posts for the gallery. Public access."""
    page = request.args.get('page', 1, type=int)
    result = media_service.get_media_posts(page=page)
    return jsonify(result), 200


@media_bp.route('/media', methods=['POST'])
@requires_role('coordinator', 'staff', 'admin')
def upload_media():
    """
    Upload a photo or video. Coordinator+ only.
    Expects multipart/form-data with 'file', 'title', optional 'caption' and 'event_id'.
    """
    file    = request.files.get('file')
    title   = (request.form.get('title') or '').strip()
    caption = (request.form.get('caption') or '').strip()
    event_id = request.form.get('event_id', type=int)

    if not title:
        return error_response('VALIDATION_FAILED', 400, {'detail': 'title is required'})

    media_url, err = media_service.save_uploaded_file(file)
    if err:
        return error_response(err, 400)

    media_type = media_service.determine_media_type(file.filename)
    post, err = media_service.create_media_post(
        title=title,
        caption=caption,
        media_url=media_url,
        media_type=media_type,
        uploaded_by=current_user.id,
        event_id=event_id,
    )
    if err:
        return error_response(err, 400)

    return jsonify({'message': 'Upload successful.', 'post': post}), 201


def serve_upload(filename):
    """Serve public gallery media from the same directory used by uploads.

    Attachment delivery prevents uploaded content from executing as backend HTML.
    Legacy stored /static/uploads URLs keep working; traversal is rejected.
    """
    import os
    from flask import abort
    if (filename != os.path.basename(filename) or filename.startswith('.') or
            not media_service.allowed_file(filename)):
        abort(404)
    response = send_from_directory(current_app.config['UPLOAD_FOLDER'], filename,
                                   as_attachment=True, conditional=True)
    response.headers['X-Content-Type-Options'] = 'nosniff'
    return response
