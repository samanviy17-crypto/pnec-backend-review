# app/services/cms_stega.py
# Responsibility: Encode editor metadata invisibly inside rendered text using
# zero-width Unicode characters. Inspired by Sanity's "stega" approach: a
# JSON payload describing the source field is embedded in the text itself,
# so the public site's DOM is self-describing in preview mode without any
# manual data-attribute annotations on every element.
#
# Encoding: each byte of the UTF-8 payload is encoded as 8 zero-width chars,
# one per bit (0 -> ZWSP U+200B, 1 -> ZWNJ U+200C). The encoded payload is
# prefixed with a sentinel sequence of 4 alternating ZWNJ/ZWSP so the
# decoder can locate it deterministically inside arbitrary surrounding text.

import json


# Two zero-width characters used as 0/1 bits.
ZWSP = '​'   # bit 0
ZWNJ = '‌'   # bit 1
# 4-char sentinel marking the start of an encoded payload.
SENTINEL = ZWNJ + ZWSP + ZWNJ + ZWSP


def encode(payload, text):
    """Return `text` with `payload` (any JSON-serializable object) embedded
    invisibly at the start. The visible characters of `text` are unchanged."""
    if text is None:
        text = ''
    text = str(text)
    if not isinstance(payload, str):
        payload = json.dumps(payload, separators=(',', ':'))
    bits = []
    for byte in payload.encode('utf-8'):
        bits.append(format(byte, '08b'))
    encoded = ''.join(ZWSP if c == '0' else ZWNJ for c in ''.join(bits))
    return SENTINEL + encoded + text


def decode(text):
    """If `text` begins with a stega payload, return (payload_dict_or_str,
    remaining_text). If not, return (None, text)."""
    if not text or not text.startswith(SENTINEL):
        return None, text
    rest = text[len(SENTINEL):]
    bits = []
    i = 0
    while i + 8 <= len(rest):
        byte_chars = rest[i:i + 8]
        if any(c not in (ZWSP, ZWNJ) for c in byte_chars):
            break
        byte_str = ''.join('0' if c == ZWSP else '1' for c in byte_chars)
        bits.append(int(byte_str, 2))
        i += 8
    if not bits:
        return None, text
    payload_bytes = bytes(bits)
    try:
        payload_str = payload_bytes.decode('utf-8')
    except UnicodeDecodeError:
        return None, text
    remaining = rest[i:]
    try:
        return json.loads(payload_str), remaining
    except (ValueError, TypeError):
        return payload_str, remaining


def cms_stega_filter(value, field_id, *, section_id=None):
    """Liquid filter helper. Wraps `value` with stega payload `{sid, field}`.
    Used like: `{{ settings.headline | cms_stega: 'headline' }}` — section_id
    is injected by the renderer into the template context so the filter can
    pick it up implicitly via a Liquid helper, OR passed positionally."""
    if not section_id:
        return value
    payload = {'sid': str(section_id), 'field': str(field_id)}
    return encode(payload, value)
