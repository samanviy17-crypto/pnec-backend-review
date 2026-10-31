# app/services/cms_renderer.py
# Responsibility: Render a single CMS section to HTML using the Liquid template
# from the registry. Wraps output in a stable container with data attributes the
# editor uses to target the section (matches Shopify's `id="shopify-section-..."`
# convention).

from html import escape as html_escape

from liquid import Environment
from app.services.cms_stega import encode as stega_encode


def _cms_stega_filter(value, field_id, section_id):
    """Liquid filter: `{{ value | cms_stega: 'field_id', section.id }}`.
    Returns the value with a hidden stega payload (zero-width chars) so the
    public-page DOM is self-describing in preview mode.
    Returns the bare value if any arg is missing (defensive)."""
    if not section_id or not field_id:
        return value
    return stega_encode({'sid': str(section_id), 'field': str(field_id)}, value)


# Module-level Liquid environment; safe to share across requests.
_env = Environment()
_env.add_filter('cms_stega', _cms_stega_filter)


def render_section(section_id, section_data, registry):
    """Render one section dict to a wrapper HTML string.

    Args:
        section_id:    The unique sid (string) within the page's template.
        section_data:  {type, settings, visible, blocks, block_order}
        registry:      CmsRegistry instance used to look up the template.

    Returns:
        HTML string. On lookup or render failure, returns a sentinel comment so
        the editor can still detect the section in the DOM tree.
    """
    type_id = (section_data or {}).get('type')
    settings = (section_data or {}).get('settings') or {}
    visible = bool((section_data or {}).get('visible', True))
    device_visibility = (section_data or {}).get('device_visibility')
    if device_visibility is None:
        device_visibility = ['desktop', 'tablet', 'mobile']
    layout = (section_data or {}).get('layout') or {}
    blocks = (section_data or {}).get('blocks') or {}
    block_order = (section_data or {}).get('block_order') or []
    ordered_blocks = [
        {'id': bid, **(blocks.get(bid) or {})}
        for bid in block_order if bid in blocks
    ]

    entry = registry.get(type_id)
    if not entry:
        return _wrap(section_id, type_id or 'unknown', visible,
                     f'<!-- cms: unknown section type {html_escape(str(type_id))} -->',
                     device_visibility, layout)

    try:
        template = _env.from_string(entry['template_source'])
        body = template.render(
            section={'id': section_id, 'type': type_id, 'settings': settings,
                     'blocks': ordered_blocks},
            settings=settings,
            blocks=ordered_blocks,
        )
    except Exception as exc:                     # noqa: BLE001 — surface to dev console
        body = (f'<!-- cms: render error for {html_escape(type_id)}: '
                f'{html_escape(str(exc))} -->')

    if not visible:
        body = f'<!-- cms: section hidden -->{body}'

    return _wrap(section_id, type_id, visible, body, device_visibility, layout)


def _wrap(section_id, type_id, visible, body, device_visibility=None, layout=None):
    """Wrap rendered section body in stable container with editor data attrs.
    device_visibility: list of {'desktop','tablet','mobile'} allowed devices.
    layout: optional dict with per-instance spacing + background overrides:
      { padding_top, padding_bottom, background_color, background_image,
        text_color, max_width }.
    """
    classes = ['cms-section']
    if isinstance(device_visibility, list) and len(device_visibility) > 0:
        if 'desktop' not in device_visibility: classes.append('cms-hide-desktop')
        if 'tablet'  not in device_visibility: classes.append('cms-hide-tablet')
        if 'mobile'  not in device_visibility: classes.append('cms-hide-mobile')

    style_parts = []
    animation = ''
    if isinstance(layout, dict):
        if layout.get('padding_top'):       style_parts.append(f'padding-top:{html_escape(str(layout["padding_top"]))}')
        if layout.get('padding_bottom'):    style_parts.append(f'padding-bottom:{html_escape(str(layout["padding_bottom"]))}')
        if layout.get('background_color'):  style_parts.append(f'background-color:{html_escape(str(layout["background_color"]))}')
        if layout.get('background_image'):
            url = html_escape(str(layout['background_image'])).replace('"', '%22')
            style_parts.append(f'background-image:url("{url}");background-size:cover;background-position:center')
        if layout.get('text_color'):        style_parts.append(f'color:{html_escape(str(layout["text_color"]))}')
        if layout.get('max_width'):         style_parts.append(f'max-width:{html_escape(str(layout["max_width"]))};margin-left:auto;margin-right:auto')
        # Entrance animation — emitted as a class. Frontend (hydrate.js) attaches
        # an IntersectionObserver and adds .cms-anim-in once the element is visible.
        anim = (layout.get('animation') or '').strip()
        if anim in {'fade-in', 'fade-up', 'fade-down', 'slide-left', 'slide-right', 'zoom-in'}:
            classes.append(f'cms-anim cms-anim-{anim}')
            animation = anim
    style_attr = f' style="{"; ".join(style_parts)}"' if style_parts else ''
    anim_attr  = f' data-cms-animation="{html_escape(animation)}"' if animation else ''

    return (
        f'<div id="cms-section-{html_escape(str(section_id))}"'
        f' class="{" ".join(classes)}"'
        f' data-cms-section-id="{html_escape(str(section_id))}"'
        f' data-cms-section-type="{html_escape(str(type_id))}"'
        f' data-cms-section-visible="{ "true" if visible else "false" }"'
        f'{anim_attr}'
        f'{style_attr}>'
        f'{body}</div>'
    )


def render_page(template_dict, registry):
    """Render every section in the page template, in `order`.

    Returns a dict {section_id: html_string}. Sections in `sections` but missing
    from `order` are rendered too (defensive).
    """
    sections  = (template_dict or {}).get('sections') or {}
    order     = (template_dict or {}).get('order') or []
    out       = {}
    for sid in order:
        if sid in sections:
            out[sid] = render_section(sid, sections[sid], registry)
    # Render any orphan sections not in order (helps debug stale state)
    for sid, sdata in sections.items():
        if sid not in out:
            out[sid] = render_section(sid, sdata, registry)
    return out
