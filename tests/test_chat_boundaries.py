"""Cloud chat storage accepts bounded data and never crosses account boundaries."""
from app import db
from app.models.user import User
from werkzeug.security import generate_password_hash

def test_chat_ownership_and_bounded_payloads(app,admin_client):
    made=admin_client.post('/api/chat/sessions',json={'title':'Synthetic'})
    assert made.status_code==201
    ident=made.json['id']
    other=User(email='other-chat@example.test',display_name='Synthetic',role='resident',password_hash=generate_password_hash('synthetic-test-password'))
    token=other.generate_token();db.session.add(other);db.session.commit()
    client=app.test_client();headers={'Authorization':'Bearer '+token}
    for method,path in [('get',f'/api/chat/sessions/{ident}/messages'),('delete',f'/api/chat/sessions/{ident}')]:
        assert getattr(client,method)(path,headers=headers).status_code==404
    for payload in [[],{'messages':[{'role':'system','content':'bad'}]},{'messages':[None]}]:
        assert admin_client.post(f'/api/chat/sessions/{ident}/messages/batch',json=payload).status_code==400
    assert admin_client.post(f'/api/chat/sessions/{ident}/messages/batch',json={'messages':[{'role':'user','content':'Synthetic question'}]}).status_code==201
