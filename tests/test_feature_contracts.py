"""Resident/admin API routes that the handoff audit found unregistered or missing."""
import pytest
from app import db
from app.models.faq import FaqItem

@pytest.mark.parametrize('method,path',[
 ('get','/api/announcements/all'),('post','/api/announcements'),
 ('get','/api/faq'),('delete','/api/faq/1'),('delete','/api/media/1'),
 ('get','/api/chat/analytics'),('get','/api/chat/sessions')])
def test_privileged_features_reject_guest(client,method,path):
    assert getattr(client,method)(path,json={} if method=='post' else None).status_code in (401,403)


def test_announcement_admin_crud_and_public_banner(admin_client,client):
    made=admin_client.post('/api/announcements',json={'message':'Synthetic exercise','level':'info'})
    assert made.status_code==201
    ident=made.json['announcement']['id']
    assert any(r['id']==ident for r in client.get('/api/announcements').json['announcements'])
    assert admin_client.patch(f'/api/announcements/{ident}',json={'is_active':False}).status_code==200
    assert all(r['id']!=ident for r in client.get('/api/announcements').json['announcements'])
    assert admin_client.delete(f'/api/announcements/{ident}').status_code==200


def test_faq_admin_list_delete_and_aggregate_analytics(admin_client):
    listing=admin_client.get('/api/faq')
    assert listing.status_code==200 and listing.json['faqs']
    ident=listing.json['faqs'][0]['id']
    assert admin_client.delete(f'/api/faq/{ident}').status_code==200
    assert db.session.get(FaqItem,ident) is None
    metrics=admin_client.get('/api/chat/analytics')
    assert metrics.status_code==200 and metrics.json['totalMsgs']==0
    assert 'limitations' in metrics.json


def test_fresh_neighborhood_seed_uses_reviewed_public_map_and_preserves_existing(app):
    import json
    from pathlib import Path
    from app.models.neighborhood import Neighborhood
    from app.services.neighborhood_service import seed_neighborhoods
    rows=json.loads((Path(__file__).resolve().parents[1]/'app/data/neighborhoods.json').read_text())
    actual=[{'number':r.number,'name':r.name,'zone':r.zone} for r in Neighborhood.query.order_by(Neighborhood.number)]
    assert actual==rows and len(rows)==60
    assert all(r.coordinator_email is None for r in Neighborhood.query)
    first=Neighborhood.query.order_by(Neighborhood.number).first()
    first.name='Existing operator-reviewed assignment';db.session.commit()
    assert seed_neighborhoods()==0
    assert Neighborhood.query.order_by(Neighborhood.number).first().name=='Existing operator-reviewed assignment'
