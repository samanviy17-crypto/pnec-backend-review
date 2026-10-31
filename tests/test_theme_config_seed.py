# tests/test_theme_config_seed.py
# Verifies the three theme keys are present in DEFAULT_CONFIG and seed correctly.

from app.routes.site_config import DEFAULT_CONFIG, seed_site_config
from app.models.site_config import SiteConfig


def _key_set():
    return {cfg['key'] for cfg in DEFAULT_CONFIG}


def test_theme_keys_present_in_default_config():
    keys = _key_set()
    assert 'theme_primary_color' in keys
    assert 'theme_accent_color'  in keys
    assert 'theme_logo_image'    in keys


def test_theme_keys_have_theme_group():
    by_key = {cfg['key']: cfg for cfg in DEFAULT_CONFIG}
    for k in ('theme_primary_color', 'theme_accent_color', 'theme_logo_image'):
        assert by_key[k]['group'] == 'theme', f"{k} missing group=theme"


def test_seed_inserts_theme_keys(app):
    with app.app_context():
        seed_site_config()
        keys = {row.key for row in SiteConfig.query.all()}
        assert 'theme_primary_color' in keys
        assert 'theme_accent_color'  in keys
        assert 'theme_logo_image'    in keys
