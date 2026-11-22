"""Integration tests; use an isolated in-memory SQLite database by default."""
import os
import tempfile

fd, path = tempfile.mkstemp(suffix='.db')
os.close(fd)
os.environ['DATABASE_URL']='sqlite:///'+path
os.environ['SECRET_KEY']='test-key'
from fastapi.testclient import TestClient
import main

client = TestClient(main.app)

def test_customer_order_pickup():
    phone='05551119988'
    assert client.post('/api/v1/auth/register',json={'phone_number':phone,'full_name':'Test Müşteri'}).status_code==200
    auth=client.post('/api/v1/auth/verify-otp',json={'phone_number':phone,'otp':'1234'}).json()
    headers={'Authorization':'Bearer '+auth['access_token']}
    assert client.post('/api/v1/subscriptions',json={'plan_type':'Starter','card_token':'4000-0000-0000-0002'},headers=headers).status_code==402
    assert client.post('/api/v1/subscriptions',json={'plan_type':'Starter','card_token':'4242-4242-4242-4242'},headers=headers).status_code==200
    shop=client.get('/api/v1/shops').json()[0]
    product=client.get(f"/api/v1/shops/{shop['id']}/menu").json()[0]
    r=client.post('/api/v1/orders',json={'shop_id':shop['id'],'product_id':product['id']},headers=headers)
    assert r.status_code==200
    order=r.json()
    assert order['qr_code'].startswith('data:image/png;base64,')
    payload=client.get(f"/api/v1/orders/{order['id']}/qr-payload",headers=headers).json()
    owner_token=client.post('/api/v1/auth/verify-otp',json={'phone_number':'05550000002','otp':'1234'}).json()['access_token']
    owner={'Authorization':'Bearer '+owner_token}
    for state in ('ACCEPTED','PREPARING','READY'):
        assert client.patch(f"/api/v1/orders/{order['id']}/status",headers=owner,json={'status':state}).status_code==200
    assert client.post('/api/v1/orders/verify-qr',headers=owner,json={'payload':payload}).status_code==200
    assert client.post('/api/v1/orders/verify-qr',headers=owner,json={'payload':payload}).status_code==409
    assert client.get(f"/api/v1/orders/{order['id']}",headers=headers).json()['status']=='DELIVERED'
