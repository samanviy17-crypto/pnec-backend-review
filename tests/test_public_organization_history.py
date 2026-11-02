"""Public history consistency only; no existing database content is overwritten."""
from app.routes.site_config import DEFAULT_CONFIG,seed_site_config
from app.models.site_config import SiteConfig
from app.models.faq import FaqItem
from app import db

def test_fresh_public_history_agrees_with_official_source(app):
    values=[x['value'] for x in DEFAULT_CONFIG if x['key']=='footer_tagline']
    assert len(values)==1 and 'since 2011' in values[0]
    answers=[x.answer for x in FaqItem.query if 'has been preparing Poway residents' in x.answer]
    assert len(answers)==1 and 'since 2011' in answers[0]

def test_existing_owner_managed_content_is_preserved(app):
    seed_site_config()
    row=SiteConfig.query.filter_by(key='footer_tagline').one()
    row.value='Existing owner-maintained text';db.session.commit()
    seed_site_config()
    assert row.value=='Existing owner-maintained text'
