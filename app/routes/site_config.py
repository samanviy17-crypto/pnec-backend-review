# app/routes/site_config.py
# Responsibility: Site configuration API — public read, admin write.

from datetime import datetime

from flask import Blueprint, request, jsonify, current_app
from flask_login import current_user

from app import db
from app.models.site_config import SiteConfig
from app.utils.errors import error_response
from app.utils.auth_decorators import requires_role

site_config_bp = Blueprint('site_config', __name__)

# Default config entries — seeding is additive (new keys added, existing values preserved)
DEFAULT_CONFIG = [
    # ── Navbar (top of every page) ───────────────────────────────────────────────
    {'key': 'brand_name',           'label': 'Brand Name',                  'description': 'Organization name shown in the top-left of the navbar', 'group': 'navbar', 'value': 'Poway NEC & FSC'},
    {'key': 'brand_tagline',        'label': 'Brand Tagline',               'description': 'Tagline under the brand name',                            'group': 'navbar', 'value': 'Neighbors Helping Neighbors'},
    {'key': 'brand_logo_url',       'label': 'Brand Logo URL',              'description': 'Logo image shown in the navbar (use the asset library)', 'group': 'navbar', 'value': ''},
    {'key': 'nav_label_about',          'label': 'Nav Link: About',          'description': 'Label for the About link in the top navigation',         'group': 'navbar', 'value': 'About'},
    {'key': 'nav_label_programs',       'label': 'Nav Link: Programs',       'description': 'Label for the Programs and Services link',              'group': 'navbar', 'value': 'Programs and Services'},
    {'key': 'nav_label_preparedness',   'label': 'Nav Link: Preparedness',   'description': 'Label for the Preparedness & Help link',                'group': 'navbar', 'value': 'Preparedness & Help'},
    {'key': 'nav_label_events',         'label': 'Nav Link: Events',         'description': 'Label for the Community Events link',                   'group': 'navbar', 'value': 'Community Events'},
    {'key': 'nav_label_neighborhood',   'label': 'Nav Link: Neighborhood',   'description': 'Label for the Find Your Neighborhood link',             'group': 'navbar', 'value': 'Find Your Neighborhood'},
    {'key': 'nav_label_contact',        'label': 'Nav Link: Contact',        'description': 'Label for the Contact link',                            'group': 'navbar', 'value': 'Contact'},
    {'key': 'nav_label_login',          'label': 'Nav Link: Login',          'description': 'Label for the Login link in the navbar',                'group': 'navbar', 'value': 'Login'},
    {'key': 'nav_label_register',       'label': 'Nav Link: Register',       'description': 'Label for the Register link in the navbar',             'group': 'navbar', 'value': 'Register'},
    {'key': 'nav_donate_label',         'label': 'Donate Button Label',      'description': 'Text on the green Donate button in the navbar',         'group': 'navbar', 'value': 'Donate Now'},
    # ── Footer (bottom of every page) ────────────────────────────────────────────
    {'key': 'footer_logo_url',          'label': 'Footer Logo URL',          'description': 'Logo image in the footer',                              'group': 'footer', 'value': ''},
    {'key': 'footer_org_name',          'label': 'Footer Org Name',          'description': 'Organization name in the footer',                       'group': 'footer', 'value': 'Poway Neighborhood Emergency Corps'},
    {'key': 'footer_tagline',           'label': 'Footer Tagline',           'description': 'Long tagline paragraph in the footer',                  'group': 'footer', 'value': 'Neighbor helping neighbor since 2011. PNEC helps Poway residents prepare, connect, and support one another during emergencies.'},
    {'key': 'footer_address',           'label': 'Footer Address',           'description': 'Organization address line in the footer',               'group': 'footer', 'value': 'Poway, CA 92064'},
    {'key': 'footer_email',             'label': 'Footer Email',             'description': 'Email address shown in the footer',                     'group': 'footer', 'value': 'contact@example.test'},
    {'key': 'footer_website',           'label': 'Footer Website',           'description': 'Website URL shown in the footer',                       'group': 'footer', 'value': 'powaynec.com'},
    {'key': 'footer_newsletter_heading', 'label': 'Newsletter Heading',      'description': 'Heading on the newsletter signup card in the footer',   'group': 'footer', 'value': 'Stay Prepared'},
    {'key': 'footer_newsletter_blurb',   'label': 'Newsletter Blurb',        'description': 'Description text on the newsletter card',               'group': 'footer', 'value': 'Stay informed about community meetings and activities. Join our mailing list today.'},
    {'key': 'footer_newsletter_cta',     'label': 'Newsletter CTA',          'description': 'Button text on the newsletter signup card',             'group': 'footer', 'value': 'Join Our Mailing List'},
    {'key': 'footer_newsletter_disclaimer', 'label': 'Newsletter Disclaimer','description': 'Small print under the newsletter signup',               'group': 'footer', 'value': 'We respect your privacy. Unsubscribe at any time.'},
    {'key': 'footer_copyright',         'label': 'Footer Copyright',         'description': 'Copyright line at the very bottom of the footer',       'group': 'footer', 'value': '© 2026 Poway Neighborhood Emergency Corps. All rights reserved.'},
    {'key': 'footer_link_contact',      'label': 'Footer Link: Contact',     'description': 'Footer-bottom Contact link label',                      'group': 'footer', 'value': 'Contact'},
    {'key': 'footer_link_privacy',      'label': 'Footer Link: Privacy',     'description': 'Footer-bottom Privacy Policy link label',               'group': 'footer', 'value': 'Privacy Policy'},
    # ── Contact ──────────────────────────────────────────────────────────────────
    {'key': 'contact_email',   'label': 'Contact Email',        'description': 'Main contact email shown on the Contact page', 'group': 'contact', 'value': 'contact@example.test'},
    {'key': 'contact_phone',   'label': 'Contact Phone',        'description': 'Phone number shown on the Contact page',        'group': 'contact', 'value': ''},
    {'key': 'contact_address', 'label': 'Organization Address', 'description': 'Mailing or street address',                    'group': 'contact', 'value': 'Poway, CA'},
    {'key': 'contact_volunteer_blurb', 'label': 'Volunteer Opportunities Text', 'description': 'HTML shown in the Volunteer Opportunities column on the Contact page', 'group': 'contact',
     'value': '<p style="text-align:center;">We love volunteers &#8211; please join us if you are interested in one of the following:</p><ul><li>Neighborhood Coordinator</li><li>Ham Radio Coordinator</li><li>Board Position</li><li>Events</li><li>Other</li></ul>'},
    # ── Social ───────────────────────────────────────────────────────────────────
    {'key': 'social_facebook',  'label': 'Facebook URL',    'description': 'Full URL to Facebook page',           'group': 'social', 'value': 'https://www.facebook.com/PowayNeighborhoodEmergencyCorps'},
    {'key': 'social_twitter',   'label': 'Twitter / X URL', 'description': 'Full URL to Twitter/X profile',       'group': 'social', 'value': 'https://twitter.com/powaynec?lang=en'},
    {'key': 'social_instagram', 'label': 'Instagram URL',   'description': 'Full URL to Instagram profile',       'group': 'social', 'value': ''},
    {'key': 'social_nextdoor',  'label': 'Nextdoor URL',    'description': 'Full URL to Nextdoor page',           'group': 'social', 'value': ''},
    {'key': 'social_linkedin',  'label': 'LinkedIn URL',    'description': 'Full URL to LinkedIn company page',   'group': 'social', 'value': 'https://www.linkedin.com/company/poway-neighborhood-emergency-corps/posts/?feedView=all'},
    # ── Homepage content ─────────────────────────────────────────────────────────
    {'key': 'hero_headline',  'label': 'Homepage Headline',     'description': 'Main tagline on the homepage hero banner',     'group': 'page_home', 'value': 'Neighbors Helping Neighbors'},
    {'key': 'hero_subline',   'label': 'Homepage Sub-headline', 'description': 'Secondary line under the main headline',       'group': 'page_home', 'value': 'Poway Neighborhood Emergency Corps — prepared together.'},
    {'key': 'about_blurb',    'label': 'Homepage About Blurb',  'description': 'Short paragraph on the homepage About section', 'group': 'page_home', 'value': 'PNEC is a community-based emergency preparedness organization serving the neighborhoods of Poway, CA.'},
    # ── About page content ───────────────────────────────────────────────────────
    {'key': 'about_who_para1', 'label': 'Who We Are — Paragraph 1', 'description': 'First paragraph under "Who Are We?" on the About page (HTML)', 'group': 'page_about',
     'value': '<p>Poway Neighborhood Emergency Corps (PNEC) is a 501(c)(3) nonprofit organization focused on disaster preparedness education.  We provide outreach activities and educational programs to better prepare community members for emergencies and disasters such as wildfires, earthquakes, and floods.</p>'},
    {'key': 'about_who_para2', 'label': 'Who We Are — Paragraph 2', 'description': 'Second paragraph under "Who Are We?" on the About page (HTML)', 'group': 'page_about',
     'value': '<p>PNEC is an all-volunteer organization and is not part of the City of Poway. However, PNEC works closely with the Poway Fire Department and serves only as an educational outreach organization as it relates to fire and wildfire safety and prevention.</p>'},
    {'key': 'about_history', 'label': 'History Section', 'description': 'HTML content of the History section on the About page', 'group': 'page_about',
     'value': '<p>The Poway Neighborhood Emergency Corps was established in 2011 after a group of residents identified the need for the community to be better prepared and informed regarding wildfire and other emergencies.</p><p>PNEC has been hosting and providing community workshops and events on emergency preparedness since its inception and has steadily grown outreach activities and collaborations.</p><p>PNEC established its 501(c)(3) status in 2018.</p>'},
    {'key': 'about_mission', 'label': 'Mission Statement', 'description': 'HTML for the mission statement paragraph on the About page', 'group': 'page_about',
     'value': '<p>To educate community members on emergency preparedness, how to prepare and what to do in disasters and emergency situations.</p>'},
    # ── Programs page content ────────────────────────────────────────────────────
    {'key': 'programs_pnec_para', 'label': 'PNEC Programs — Main Paragraph', 'description': 'HTML for the main PNEC programs description on the Programs & Services page', 'group': 'page_programs',
     'value': '<p>PNEC regularly organizes a variety of community preparedness &amp; resource presentations and has established complementary programs, collaborations, and services to aid in achieving its overall mission.</p><p>PNEC works with the Neighborhood Emergency Coordinators (NECs) who provide important preparedness information to their neighbors, similar to a calling tree. PNEC provides training, guidance, and informative links to county emergency services.</p>'},
    {'key': 'programs_fsc_para', 'label': 'Fire Safe Council — Paragraph', 'description': 'HTML for the Poway Fire Safe Council section on the Programs page', 'group': 'page_programs',
     'value': '<p>The Poway Fire Safe Council, established in 2017, is an extension of PNEC with a sole focus on fire safety and wildfire emergency preparedness. It is approved as a local FSC by the California Fire Safe Council and is part of the San Diego Regional Board Water Conservative Authority.</p>'},
    {'key': 'programs_pact_para', 'label': 'PACT Collaboration — Paragraph', 'description': 'HTML for the PACT Collaboration section on the Programs page', 'group': 'page_programs',
     'value': '<p>The collaboration with the Poway Auxiliary Communications Team (PACT) is an important collaboration for emergency communications during disasters. During a disaster, PACT will coordinate and collaborate as needed to provide communication services and share important information between the city and each identified neighborhood through the Neighborhood Emergency Coordinators (NECs) and Ham Radio Operators.</p>'},
    {'key': 'programs_large_animal_para', 'label': 'Large Animal Emergency — Paragraph', 'description': 'HTML for the Large Animal Emergency Planning section on the Programs page', 'group': 'page_programs',
     'value': '<p>Poway is the City in the Country and many of our residents have extended family in the form of horses, donkeys, goats, and backyard chickens. PNEC has gathered resources and developed best practices to help community members plan for their animals during an emergency.</p><p>Each year in November, PNEC hosts a Large Animal Emergency Planning community meeting with a panel of public safety subject matter experts.</p>'},
    # ── Organization ─────────────────────────────────────────────────────────────
    # NOTE: footer_tagline + footer_copyright already declared in the Footer
    # group at the top of this list (v2.31) — don't redeclare them here.
    {'key': 'org_name',       'label': 'Organization Name',    'description': 'Full official organization name',                'group': 'org', 'value': 'Poway Neighborhood Emergency Corps'},
    {'key': 'org_short_name', 'label': 'Short Name / Acronym', 'description': 'Abbreviation used in navigation and badges',    'group': 'org', 'value': 'PNEC'},
    {'key': 'donate_url',     'label': 'Donate Link URL',      'description': 'URL for the donation button',                   'group': 'org', 'value': ''},
    # ── Images ───────────────────────────────────────────────────────────────────
    {'key': 'about_banner_image',    'label': 'About Page — Banner Image URL',    'description': 'URL for the banner/hero image on the About page',              'group': 'images', 'value': ''},
    {'key': 'programs_banner_image', 'label': 'Programs Page — Banner Image URL', 'description': 'URL for the banner/hero image on the Programs & Services page', 'group': 'images', 'value': ''},
    {'key': 'homepage_banner_image', 'label': 'Homepage — Extra Banner Image URL','description': 'URL for an optional hero image override on the homepage',      'group': 'images', 'value': ''},
    # ── Theme ────────────────────────────────────────────────────────────────────
    {'key': 'theme_primary_color', 'label': 'Theme — Primary Color', 'description': 'Primary accent color used across the site', 'group': 'theme', 'value': '#1e3a8a'},
    {'key': 'theme_accent_color',  'label': 'Theme — Accent Color',  'description': 'Secondary accent color',                    'group': 'theme', 'value': '#f59e0b'},
    {'key': 'theme_logo_image',    'label': 'Theme — Logo Image',    'description': 'Site logo image URL',                       'group': 'theme', 'value': ''},
]


@site_config_bp.route('/site-config', methods=['GET'])
def get_site_config():
    """Return all site config entries as a key→value map (public) plus full entry list for admin."""
    rows = SiteConfig.query.order_by(SiteConfig.group, SiteConfig.key).all()
    return jsonify({
        'config':  {r.key: r.value for r in rows},
        'entries': [r.to_dict() for r in rows],
        'meta':    {cfg['key']: {'label': cfg['label'], 'description': cfg.get('description',''), 'group': cfg['group']} for cfg in DEFAULT_CONFIG},
    }), 200


@site_config_bp.route('/site-config/<string:key>', methods=['PATCH'])
@requires_role('admin')
def update_config_entry(key):
    """Update a single config entry by key. Admin only."""
    entry = SiteConfig.query.filter_by(key=key).first()
    if not entry:
        return error_response('NOT_FOUND', 404)

    data = request.get_json(silent=True) or {}
    if 'value' not in data:
        return error_response('VALIDATION_FAILED', 400, {'detail': 'value is required'})

    entry.value = str(data['value'])
    entry.updated_at = datetime.utcnow()
    entry.updated_by = current_user.id
    db.session.commit()
    return jsonify({'message': 'Config updated.', 'entry': entry.to_dict()}), 200


@site_config_bp.route('/site-config/<string:key>', methods=['DELETE'])
@requires_role('admin')
def reset_config_entry(key):
    """Delete a single config entry — caller falls back to the original
    HTML default. Admin only.

    Note: SiteConfig rows are seeded with current values; deleting the row
    means future reads return no value for that key, so applyAll() leaves
    the original HTML alone. That's the desired "reset to default" behavior.
    """
    entry = SiteConfig.query.filter_by(key=key).first()
    if entry:
        db.session.delete(entry)
        db.session.commit()
    return jsonify({'message': 'Config entry removed.'}), 200


@site_config_bp.route('/site-config/bulk', methods=['PATCH'])
@requires_role('admin')
def bulk_update_config():
    """Update multiple config entries at once. Admin only. Body: { updates: { key: value, ... } }"""
    data = request.get_json(silent=True) or {}
    updates = data.get('updates') or {}
    if not isinstance(updates, dict):
        return error_response('VALIDATION_FAILED', 400, {'detail': 'updates must be an object'})

    results = []
    for key, value in updates.items():
        entry = SiteConfig.query.filter_by(key=key).first()
        if entry:
            entry.value = str(value)
            entry.updated_at = datetime.utcnow()
            entry.updated_by = current_user.id
            results.append(key)

    db.session.commit()
    return jsonify({'message': f'Updated {len(results)} entries.', 'updated_keys': results}), 200


@site_config_bp.route('/site-config/upload-image', methods=['POST'])
@requires_role('admin')
def upload_cms_image():
    """Upload an image for use in CMS config (returns URL). Admin only.

    Phase 3 (v3): also creates a MediaPost row so the editor's asset
    library shows everything admins have uploaded — previously the
    library only listed files added through /api/media POST, which the
    editor never called, leaving the library empty for normal users.
    """
    from app.services.media_service import save_uploaded_file, determine_media_type, create_media_post
    from flask_login import current_user
    file = request.files.get('file')
    if not file or not file.filename:
        return error_response('VALIDATION_FAILED', 400, {'detail': 'file is required'})
    url, err = save_uploaded_file(file)
    if err:
        return error_response(err, 400)

    # Best-effort MediaPost — failure here MUST NOT break the upload,
    # because the file is already on disk and the URL is what the
    # editor needs back. We just log + continue.
    try:
        title = (request.form.get('title') or file.filename or 'Untitled').strip()[:140]
        caption = (request.form.get('caption') or '').strip()[:500]
        media_type = determine_media_type(file.filename)
        uploaded_by = current_user.id if current_user.is_authenticated else None
        create_media_post(title=title, caption=caption,
                          media_url=url, media_type=media_type,
                          uploaded_by=uploaded_by)
    except Exception as e:
        # Don't fail the upload over a metadata write
        try:
            current_app.logger.warning('upload-image: MediaPost create failed: %s', e)
        except Exception:
            pass

    return jsonify({'url': url}), 200


def seed_site_config():
    """Seed default config entries — additive: adds new keys without overwriting existing values."""
    existing_keys = {row.key for row in SiteConfig.query.with_entities(SiteConfig.key).all()}
    for cfg in DEFAULT_CONFIG:
        if cfg['key'] not in existing_keys:
            db.session.add(SiteConfig(**cfg))
    db.session.commit()
