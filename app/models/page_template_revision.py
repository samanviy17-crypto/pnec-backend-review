# app/models/page_template_revision.py
# Responsibility: snapshot the JSON template before each PATCH so the editor
# can show real per-edit history and let admins revert any specific change.
#
# Phase 2 versioning — replaces "history" panel that was just a list of
# updated_at timestamps with no actual revert support for page templates.
#
# Design choices:
#   • One row per applied patch op (NOT per HTTP call — a single PATCH may
#     contain multiple ops, but we record each one separately so an admin
#     can revert exactly one block edit without losing the others)
#   • Stores the full JSON snapshot of the section's settings/blocks/order
#     BEFORE the op was applied. Reverting = restore that snapshot.
#   • Cap: 200 revisions per (page_slug, state). Older ones get pruned.
#   • Indexed by (page_slug, state, created_at desc) so the editor can
#     paginate the history view efficiently.

import json
from datetime import datetime
from app import db


class PageTemplateRevision(db.Model):
    """A snapshot of a page template at a moment in time.

    snapshot_json is the FULL template JSON BEFORE the op landed —
    reverting to this revision means: take this JSON, write it back into
    the matching PageTemplate row.
    """

    __tablename__ = 'page_template_revisions'
    __table_args__ = (
        db.Index('ix_revisions_page_state_time', 'page_slug', 'state', 'created_at'),
    )

    id            = db.Column(db.Integer,    primary_key=True)
    page_slug     = db.Column(db.String(80), nullable=False)
    state         = db.Column(db.String(16), nullable=False)  # draft | published
    op            = db.Column(db.String(32), nullable=False)  # add | remove | set | publish | revert | …
    op_target_sid = db.Column(db.String(64), nullable=True)   # which sid the op acted on, if applicable
    op_summary    = db.Column(db.String(280), nullable=True)  # human-readable detail for the panel
    snapshot_json = db.Column(db.Text,       nullable=False)  # the full template BEFORE the op
    created_at    = db.Column(db.DateTime,   nullable=False, default=datetime.utcnow, index=True)
    created_by    = db.Column(db.Integer,    db.ForeignKey('users.id'), nullable=True)

    # ── Helpers ──────────────────────────────────────────────────────────────

    def get_snapshot(self):
        try:
            d = json.loads(self.snapshot_json) if self.snapshot_json else {}
        except (ValueError, TypeError):
            d = {}
        if not isinstance(d, dict):
            d = {}
        d.setdefault('sections', {})
        d.setdefault('order', [])
        return d

    def to_dict(self):
        return {
            'id':            self.id,
            'page_slug':     self.page_slug,
            'state':         self.state,
            'op':            self.op,
            'op_target_sid': self.op_target_sid,
            'op_summary':    self.op_summary,
            'created_at':    self.created_at.isoformat() if self.created_at else None,
            'created_by':    self.created_by,
        }


# ─── Convenience helpers ─────────────────────────────────────────────────────

MAX_REVISIONS_PER_PAGE = 200


def record_revision(page_slug, state, op, snapshot, *,
                    op_target_sid=None, op_summary=None, created_by=None):
    """Append a revision row, pruning old ones beyond the cap.
    Caller is responsible for db.session.commit() — we just stage the writes.
    """
    if not isinstance(snapshot, dict):
        snapshot = {}
    rev = PageTemplateRevision(
        page_slug=page_slug,
        state=state,
        op=(op or 'unknown')[:32],
        op_target_sid=(op_target_sid or None),
        op_summary=(op_summary or None)[:280] if op_summary else None,
        snapshot_json=json.dumps(snapshot),
        created_by=created_by,
    )
    db.session.add(rev)

    # Prune oldest revisions beyond the per-page cap. Cheap because the
    # composite index covers (page_slug, state, created_at).
    excess = (PageTemplateRevision.query
              .filter_by(page_slug=page_slug, state=state)
              .order_by(PageTemplateRevision.created_at.desc())
              .offset(MAX_REVISIONS_PER_PAGE)
              .all())
    for old in excess:
        db.session.delete(old)
    return rev
