# app/services/cms_registry.py
# Responsibility: Discover and cache the available CMS section types from the
# filesystem. Each section type lives in `<sections_root>/<type>/` and contains:
#   - <type>.html         Liquid template rendered server-side
#   - <type>.schema.json  Editor field schema
#   - <type>.preview.svg  (optional) icon shown in the section picker

import json
import os


REQUIRED_SCHEMA_FIELDS = ('type', 'label', 'settings')


class CmsRegistry:
    """In-memory registry of section types loaded from disk."""

    def __init__(self, sections_root):
        self.sections_root = sections_root
        self._types = {}              # type_id -> {schema, template_source, dir}
        self._loaded = False

    # ── Loading ──────────────────────────────────────────────────────────────

    def load(self):
        """Scan sections_root and populate _types. Idempotent."""
        self._types = {}
        if not os.path.isdir(self.sections_root):
            self._loaded = True
            return
        for entry in sorted(os.listdir(self.sections_root)):
            type_dir = os.path.join(self.sections_root, entry)
            if not os.path.isdir(type_dir):
                continue
            schema_path = os.path.join(type_dir, f'{entry}.schema.json')
            tmpl_path   = os.path.join(type_dir, f'{entry}.html')
            if not (os.path.exists(schema_path) and os.path.exists(tmpl_path)):
                continue
            try:
                with open(schema_path, 'r', encoding='utf-8') as f:
                    schema = json.load(f)
                with open(tmpl_path, 'r', encoding='utf-8') as f:
                    template_source = f.read()
            except (ValueError, OSError):
                continue
            if not all(k in schema for k in REQUIRED_SCHEMA_FIELDS):
                continue
            if schema.get('type') != entry:
                # The directory name is canonical; warn-and-skip on mismatch
                continue
            self._types[entry] = {
                'schema':          schema,
                'template_source': template_source,
                'dir':             type_dir,
            }
        self._loaded = True

    # ── Access ───────────────────────────────────────────────────────────────

    def list_types(self):
        """Return a list of public schema dicts (no template source)."""
        if not self._loaded:
            self.load()
        return [self._types[t]['schema'] for t in sorted(self._types.keys())]

    def get(self, type_id):
        """Return the registry entry for a type, or None."""
        if not self._loaded:
            self.load()
        return self._types.get(type_id)

    def get_schema(self, type_id):
        entry = self.get(type_id)
        return entry['schema'] if entry else None

    def get_template_source(self, type_id):
        entry = self.get(type_id)
        return entry['template_source'] if entry else None

    def default_settings(self, type_id):
        """Build a default settings dict from the schema's `default` values."""
        schema = self.get_schema(type_id)
        if not schema:
            return {}
        defaults = {}
        for field in schema.get('settings', []):
            if 'default' in field and 'id' in field:
                defaults[field['id']] = field['default']
        return defaults
