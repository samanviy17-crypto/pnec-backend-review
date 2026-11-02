"""Small, canonical raster data URLs fitting MySQL TEXT without a migration."""
import base64
import binascii
from io import BytesIO
import re
import warnings
from PIL import Image, UnidentifiedImageError

MAX_AVATAR_BYTES = 60000  # entire ASCII data URL, not just decoded bytes


def validate_avatar(value):
    if len(value) > MAX_AVATAR_BYTES or not value.isascii():
        raise ValueError('Photo must fit 60,000 bytes after resizing.')
    match = re.fullmatch(r'data:image/(jpeg|png|webp|gif);base64,([A-Za-z0-9+/]*={0,2})', value)
    if not match:
        raise ValueError('Photo must be a raster image data URL (JPG, PNG, GIF or WebP).')
    try:
        raw = base64.b64decode(match[2], validate=True)
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(BytesIO(raw)) as image:
                if image.format != {'jpeg': 'JPEG', 'png': 'PNG', 'webp': 'WEBP', 'gif': 'GIF'}[match[1]]:
                    raise ValueError()
                if not (1 <= image.width <= 400 and 1 <= image.height <= 400):
                    raise ValueError()
                image.load()
                # Discard metadata, appended content and additional animation frames.
                output = BytesIO()
                image.convert('RGB').save(output, format='JPEG', quality=82)
                result = 'data:image/jpeg;base64,' + base64.b64encode(output.getvalue()).decode('ascii')
                if len(result) > MAX_AVATAR_BYTES:
                    raise ValueError()
                return result
    except (ValueError, OSError, binascii.Error, UnidentifiedImageError,
            Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise ValueError('Photo must be a valid raster image at most 400px and 60,000 encoded bytes.') from None
