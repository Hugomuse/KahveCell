"""KahveCell case-study API. Demo-only OTP and payment simulation."""
import base64
import hashlib
import hmac
import io
import json
import math
import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

import jwt
import qrcode
from fastapi import Depends, FastAPI, HTTPException, Header, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, JSON, String, create_engine, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

DATABASE_URL = os.getenv('DATABASE_URL', 'sqlite:///./kahvecell.db')
SECRET = os.getenv('SECRET_KEY', 'local-development-only-change-this')
if DATABASE_URL.startswith('sqlite'):
    engine = create_engine(DATABASE_URL, connect_args={'check_same_thread': False})
else:
    engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine)

class Base(DeclarativeBase): pass

def ident(): return str(uuid.uuid4())
def now(): return datetime.now(timezone.utc).replace(tzinfo=None)

class User(Base):
    __tablename__='users'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=ident)
    phone_number: Mapped[str] = mapped_column(String(20), unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(100), default='')
    email: Mapped[str] = mapped_column(String(255), default='')
    role: Mapped[str] = mapped_column(String(20), default='CUSTOMER')
    preferences: Mapped[dict] = mapped_column(JSON, default=dict)

class Plan(Base):
    __tablename__='plans'
    id: Mapped[str] = mapped_column(String(30), primary_key=True)
    price: Mapped[float] = mapped_column(Float)
    credits: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    guest_credits: Mapped[int] = mapped_column(Integer, default=0)
    priority: Mapped[bool] = mapped_column(Boolean, default=False)

class Subscription(Base):
    __tablename__='subscriptions'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=ident)
    user_id: Mapped[str] = mapped_column(ForeignKey('users.id'), index=True)
    plan_id: Mapped[str] = mapped_column(ForeignKey('plans.id'))
    remaining_credits: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    remaining_guest_credits: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(20), default='ACTIVE')
    started_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    expires_at: Mapped[datetime] = mapped_column(DateTime)

class Shop(Base):
    __tablename__='shops'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=ident)
    name: Mapped[str] = mapped_column(String(100))
    address: Mapped[str] = mapped_column(String(255))
    lat: Mapped[float] = mapped_column(Float)
    lng: Mapped[float] = mapped_column(Float)
    rating: Mapped[float] = mapped_column(Float, default=4.5)
    hours: Mapped[str] = mapped_column(String(100), default='08:00–22:00')
    owner_id: Mapped[Optional[str]] = mapped_column(ForeignKey('users.id'), nullable=True)

class Product(Base):
    __tablename__='products'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=ident)
    shop_id: Mapped[str] = mapped_column(ForeignKey('shops.id'), index=True)
    name: Mapped[str] = mapped_column(String(80))
    category: Mapped[str] = mapped_column(String(50), default='Kahveler')
    price: Mapped[float] = mapped_column(Float)

class Order(Base):
    __tablename__='orders'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=ident)
    user_id: Mapped[str] = mapped_column(ForeignKey('users.id'), index=True)
    shop_id: Mapped[str] = mapped_column(ForeignKey('shops.id'), index=True)
    product_id: Mapped[str] = mapped_column(ForeignKey('products.id'))
    status: Mapped[str] = mapped_column(String(20), default='PENDING')
    customizations: Mapped[dict] = mapped_column(JSON, default=dict)
    is_guest: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)

class Payment(Base):
    __tablename__='payments'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=ident)
    user_id: Mapped[str] = mapped_column(ForeignKey('users.id'))
    plan_id: Mapped[str] = mapped_column(ForeignKey('plans.id'))
    amount: Mapped[float] = mapped_column(Float)
    success: Mapped[bool] = mapped_column(Boolean)
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=now)

app = FastAPI(title='KahveCell API', version='1.0.0')
app.add_middleware(CORSMiddleware, allow_origins=os.getenv('CORS_ORIGINS','http://localhost:5173').split(','), allow_methods=['*'], allow_headers=['*'])

def db():
    with SessionLocal() as session: yield session

def fail(status, detail): raise HTTPException(status_code=status, detail=detail)

def token(user: User, kind='access'):
    lifetime=timedelta(days=7) if kind=='refresh' else timedelta(hours=8)
    return jwt.encode({'sub':user.id, 'role':user.role, 'type':kind, 'exp':datetime.now(timezone.utc)+lifetime},SECRET,algorithm='HS256')

def user_from_token(authorization: Optional[str], session: Session, expected='access'):
    if not authorization or not authorization.startswith('Bearer '): fail(401,'Giriş yapmanız gerekiyor')
    try:
        payload=jwt.decode(authorization[7:],SECRET,algorithms=['HS256'])
        if payload.get('type') != expected: fail(401,'Geçersiz token türü')
        u=session.get(User,payload['sub'])
        if u is None: fail(401,'Kullanıcı bulunamadı')
        return u
    except jwt.PyJWTError: fail(401,'Geçersiz veya süresi dolmuş token')

def current(authorization:Optional[str]=Header(None),session:Session=Depends(db)):
    return user_from_token(authorization,session)

def owner(user=Depends(current)):
    if user.role not in ('SHOP_OWNER','ADMIN'): fail(403,'Dükkân sahibi yetkisi gerekli')
    return user

def user_dict(u): return {'id':u.id,'phone_number':u.phone_number,'full_name':u.full_name,'email':u.email,'role':u.role,'preferences':u.preferences}
def plan_dict(p): return {'id':p.id,'name':p.id,'price':p.price,'credits':p.credits,'guest_credits':p.guest_credits,'priority':p.priority}
def sub_dict(s): return {'id':s.id,'plan_type':s.plan_id,'remaining_credits':s.remaining_credits,'remaining_guest_credits':s.remaining_guest_credits,'status':s.status,'expires_at':s.expires_at.isoformat()}
def shop_dict(s,distance=None):
    a={'id':s.id,'name':s.name,'address':s.address,'lat':s.lat,'lng':s.lng,'rating':s.rating,'hours':s.hours}
    if distance is not None:a['distance_km']=round(distance,2)
    return a

def qr_payload(o):
    data={'order_id':o.id,'user_id':o.user_id,'shop_id':o.shop_id,'created_at':o.created_at.isoformat()+'Z'}
    data['signature']=hmac.new(SECRET.encode(),json.dumps(data,sort_keys=True).encode(),hashlib.sha256).hexdigest()
    return data

def qr_image(payload):
    img=qrcode.make(json.dumps(payload,ensure_ascii=False)); b=io.BytesIO(); img.save(b,format='PNG')
    return 'data:image/png;base64,'+base64.b64encode(b.getvalue()).decode()

def order_dict(o,session,include_qr=True):
    shop=session.get(Shop,o.shop_id); product=session.get(Product,o.product_id)
    data={'id':o.id,'shop_id':o.shop_id,'shop_name':shop.name if shop else '', 'product_name':product.name if product else '', 'status':o.status,'created_at':o.created_at.isoformat(),'customizations':o.customizations,'is_guest':o.is_guest}
    if include_qr and o.status!='DELIVERED':data['qr_code']=qr_image(qr_payload(o))
    return data

class RegisterIn(BaseModel):
    phone_number:str=Field(min_length=10,max_length=20)
    full_name:str=Field(default='',max_length=100)
    email:str=''
class OTPIn(BaseModel):
    phone_number:str
    otp:str
class ProfileIn(BaseModel):
    full_name:Optional[str]=None
    email:Optional[str]=None
    preferences:Optional[dict]=None
class PaymentIn(BaseModel):
    subscription_plan:str
    user_id:Optional[str]=None
    card_token:str='4242-4242-4242-4242'
class SubscriptionIn(BaseModel):
    plan_type:str
    card_token:str='4242-4242-4242-4242'
class OrderIn(BaseModel):
    shop_id:str
    product_id:str
    size:str='M'
    milk:str='Normal'
    sugar:str='Yok'
    extra_shot:bool=False
    is_guest:bool=False
class StatusIn(BaseModel): status:str
class QRIn(BaseModel): payload:dict

@app.get('/')
def home():return {'message':'KahveCell API çalışıyor','docs':'/docs'}

@app.post('/api/v1/auth/register')
def register(data:RegisterIn,session:Session=Depends(db)):
    phone=''.join(c for c in data.phone_number if c.isdigit())
    if len(phone)<10:fail(422,'Telefon numarası geçersiz')
    u=session.scalar(select(User).where(User.phone_number==phone))
    if u is None:
        u=User(phone_number=phone,full_name=data.full_name,email=data.email,role='CUSTOMER');session.add(u)
    else:
        if data.full_name:u.full_name=data.full_name
        if data.email:u.email=data.email
    session.commit()
    return {'message':'Demo OTP kodunuz: 1234','demo_otp':'1234'}

@app.post('/api/v1/auth/verify-otp')
def verify(data:OTPIn,session:Session=Depends(db)):
    if data.otp!='1234':fail(400,'OTP hatalı')
    u=session.scalar(select(User).where(User.phone_number==''.join(c for c in data.phone_number if c.isdigit())))
    if not u:fail(404,'Önce kayıt olun')
    return {'access_token':token(u),'refresh_token':token(u,'refresh'),'token_type':'bearer','user':user_dict(u)}

@app.post('/api/v1/auth/refresh')
def refresh(authorization:Optional[str]=Header(None),session:Session=Depends(db)):
    u=user_from_token(authorization,session,'refresh');return {'access_token':token(u),'token_type':'bearer'}

@app.get('/api/v1/users/me')
def me(u=Depends(current)):return user_dict(u)

@app.patch('/api/v1/users/me')
def profile(data:ProfileIn,u=Depends(current),session:Session=Depends(db)):
    fresh=session.get(User,u.id)
    for k,v in data.model_dump(exclude_none=True).items():setattr(fresh,k,v)
    session.commit();return user_dict(fresh)

@app.get('/api/v1/subscriptions/plans')
def plans(session:Session=Depends(db)):return [plan_dict(p) for p in session.scalars(select(Plan)).all()]

def active_subscription(session,user_id):
    s=session.scalar(select(Subscription).where(Subscription.user_id==user_id,Subscription.status=='ACTIVE').order_by(Subscription.started_at.desc()))
    if s and s.expires_at<=now():s.status='EXPIRED';session.commit();return None
    return s

def process_payment(session, uid, plan_id, card):
    p=session.get(Plan,plan_id)
    if not p:fail(404,'Paket bulunamadı')
    success=card.replace(' ','')=='4242-4242-4242-4242' or card.replace(' ','')=='4242424242424242'
    payment=Payment(user_id=uid,plan_id=plan_id,amount=p.price,success=success)
    session.add(payment);session.flush()
    return payment,p

@app.post('/api/v1/payments/process')
def payment(data:PaymentIn,u=Depends(current),session:Session=Depends(db)):
    if data.user_id and data.user_id!=u.id:fail(403,'Başka kullanıcı adına ödeme yapılamaz')
    payment,p=process_payment(session,u.id,data.subscription_plan,data.card_token);session.commit()
    return {'success':payment.success,'transaction_id':payment.id,'amount':p.price,'timestamp':payment.timestamp.isoformat()}

@app.get('/api/v1/payments/history')
def payment_history(u=Depends(current),session:Session=Depends(db)):
    return [{'transaction_id':p.id,'plan':p.plan_id,'amount':p.amount,'success':p.success,'timestamp':p.timestamp.isoformat()} for p in session.scalars(select(Payment).where(Payment.user_id==u.id).order_by(Payment.timestamp.desc()))]

@app.post('/api/v1/subscriptions')
def subscribe(data:SubscriptionIn,u=Depends(current),session:Session=Depends(db)):
    if active_subscription(session,u.id):fail(409,'Aktif aboneliğiniz var; paket değiştirin')
    pay,p=process_payment(session,u.id,data.plan_type,data.card_token)
    if not pay.success:session.commit();fail(402,'Ödeme başarısız (demo kart: 4242-4242-4242-4242)')
    s=Subscription(user_id=u.id,plan_id=p.id,remaining_credits=p.credits,remaining_guest_credits=p.guest_credits,expires_at=now()+timedelta(days=30))
    session.add(s);session.commit();return sub_dict(s)

@app.get('/api/v1/subscriptions/me')
def my_subscription(u=Depends(current),session:Session=Depends(db)):
    s=active_subscription(session,u.id);return sub_dict(s) if s else None

@app.patch('/api/v1/subscriptions/me')
def change_subscription(data:SubscriptionIn,u=Depends(current),session:Session=Depends(db)):
    s=active_subscription(session,u.id)
    if not s:fail(404,'Aktif abonelik bulunamadı')
    if s.plan_id==data.plan_type:fail(400,'Zaten bu pakettesiniz')
    pay,p=process_payment(session,u.id,data.plan_type,data.card_token)
    if not pay.success:session.commit();fail(402,'Ödeme başarısız')
    s.plan_id=p.id;s.remaining_credits=p.credits;s.remaining_guest_credits=p.guest_credits;s.started_at=now();s.expires_at=now()+timedelta(days=30)
    session.commit();return sub_dict(s)

@app.delete('/api/v1/subscriptions/me')
def cancel(u=Depends(current),session:Session=Depends(db)):
    s=active_subscription(session,u.id)
    if not s:fail(404,'Aktif abonelik bulunamadı')
    s.status='CANCELLED';session.commit();return {'success':True}

def distance_km(a,b,c,d):
    r1,r2=math.radians(a),math.radians(c)
    dr=r2-r1;dl=math.radians(d-b)
    h=math.sin(dr/2)**2+math.cos(r1)*math.cos(r2)*math.sin(dl/2)**2
    return 6371*2*math.asin(min(1,math.sqrt(h)))

@app.get('/api/v1/shops')
def shops(
    lat: Optional[float] = None,
    lng: Optional[float] = None,
    radius: float = Query(default=100, ge=0.1, le=500),
    q: str = '',
    min_rating: float = 0,
    session: Session = Depends(db)
):
    out = []

    for s in session.scalars(select(Shop)):
        if q.lower() not in (s.name + ' ' + s.address).lower() or s.rating < min_rating:
            continue

        d = distance_km(lat, lng, s.lat, s.lng) if lat is not None and lng is not None else None

        if d is not None and d > radius:
            continue

        out.append(shop_dict(s, d))

    return sorted(out, key=lambda item: item.get('distance_km') or 0)
@app.get('/api/v1/shops/{shop_id}')
def shop_detail(shop_id:str,session:Session=Depends(db)):
    s=session.get(Shop,shop_id)
    if not s:fail(404,'Dükkân yok')
    return shop_dict(s)

@app.get('/api/v1/shops/{shop_id}/menu')
def menu(shop_id:str,session:Session=Depends(db)):
    if not session.get(Shop,shop_id):fail(404,'Dükkân yok')
    return [{'id':p.id,'name':p.name,'price':p.price,'category':p.category} for p in session.scalars(select(Product).where(Product.shop_id==shop_id))]

@app.post('/api/v1/orders')
def create_order(data:OrderIn,u=Depends(current),session:Session=Depends(db)):
    if data.size not in ('S','M','L'):fail(422,'Boyut S, M veya L olmalı')
    s=active_subscription(session,u.id)
    if not s:fail(403,'Aktif abonelik gerekli')
    shop=session.get(Shop,data.shop_id);prod=session.get(Product,data.product_id)
    if not shop or not prod or prod.shop_id!=shop.id:fail(404,'Ürün veya dükkân bulunamadı')
    if data.is_guest:
        if s.remaining_guest_credits<=0:fail(409,'Misafir hakkınız kalmadı')
        s.remaining_guest_credits-=1
    elif s.remaining_credits is not None:
        # Lock row on PostgreSQL to guard concurrent decrements.
        s=session.scalar(select(Subscription).where(Subscription.id==s.id).with_for_update())
        if s.remaining_credits<=0:fail(409,'Kahve hakkınız kalmadı')
        s.remaining_credits-=1
    o=Order(user_id=u.id,shop_id=shop.id,product_id=prod.id,is_guest=data.is_guest,customizations=data.model_dump(include={'size','milk','sugar','extra_shot'}))
    session.add(o);session.commit();session.refresh(o)
    return order_dict(o,session)

@app.get('/api/v1/orders/history')
def history(u=Depends(current),session:Session=Depends(db)):
    return [order_dict(o,session,False) for o in session.scalars(select(Order).where(Order.user_id==u.id).order_by(Order.created_at.desc()))]

@app.get('/api/v1/orders/owner/pending')
def owner_orders(u=Depends(owner),session:Session=Depends(db)):
    query=select(Order).order_by(Order.created_at.desc())
    if u.role!='ADMIN':
        ids=[s.id for s in session.scalars(select(Shop).where(Shop.owner_id==u.id))]
        query=query.where(Order.shop_id.in_(ids))
    return [order_dict(o,session,False) for o in session.scalars(query)]

@app.get('/api/v1/orders/{order_id}/qr-payload')
def get_qr_payload(order_id:str,u=Depends(current),session:Session=Depends(db)):
    o=session.get(Order,order_id)
    if not o:fail(404,'Sipariş yok')
    if o.user_id!=u.id:fail(403,'Yetkiniz yok')
    if o.status=='DELIVERED':fail(409,'Sipariş teslim edildi')
    return qr_payload(o)

@app.get('/api/v1/orders/{order_id}')
def get_order(order_id:str,u=Depends(current),session:Session=Depends(db)):
    o=session.get(Order,order_id)
    if not o:fail(404,'Sipariş yok')
    shop=session.get(Shop,o.shop_id)
    if o.user_id!=u.id and u.role!='ADMIN' and not (u.role=='SHOP_OWNER' and shop.owner_id==u.id):fail(403,'Yetkiniz yok')
    return order_dict(o,session)

NEXT={'PENDING':'ACCEPTED','ACCEPTED':'PREPARING','PREPARING':'READY','READY':'DELIVERED'}
@app.patch('/api/v1/orders/{order_id}/status')
def change_status(order_id:str,data:StatusIn,u=Depends(owner),session:Session=Depends(db)):
    o=session.get(Order,order_id)
    if not o:fail(404,'Sipariş yok')
    shop=session.get(Shop,o.shop_id)
    if u.role!='ADMIN' and shop.owner_id!=u.id:fail(403,'Bu dükkân size ait değil')
    if NEXT.get(o.status)!=data.status:fail(409,'Geçersiz durum geçişi')
    if data.status=='DELIVERED':fail(400,'Teslim için QR doğrulaması gerekli')
    o.status=data.status;session.commit();return order_dict(o,session,False)

@app.post('/api/v1/orders/verify-qr')
def verify_qr(data:QRIn,u=Depends(owner),session:Session=Depends(db)):
    p=data.payload
    try:
        signature=p['signature'];body={k:p[k] for k in ('order_id','user_id','shop_id','created_at')}
        expected=hmac.new(SECRET.encode(),json.dumps(body,sort_keys=True).encode(),hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature,expected):fail(400,'QR imzası geçersiz')
        o=session.get(Order,p['order_id'])
        if not o or o.user_id!=p['user_id'] or o.shop_id!=p['shop_id'] or o.created_at.isoformat()+'Z'!=p['created_at']:fail(400,'QR siparişle eşleşmiyor')
        shop=session.get(Shop,o.shop_id)
        if u.role!='ADMIN' and shop.owner_id!=u.id:fail(403,'Bu dükkâna erişiminiz yok')
        if o.status!='READY':fail(409,'Sipariş henüz hazır değil veya teslim edilmiş')
        o.status='DELIVERED';session.commit();return {'success':True,'order':order_dict(o,session,False)}
    except (KeyError,TypeError):fail(400,'QR içeriği geçersiz')

def seed():
    Base.metadata.create_all(engine)
    with SessionLocal() as s:
        if s.scalar(select(Plan.id).limit(1)):return
        for p in [Plan(id='Starter',price=89.99,credits=10,guest_credits=0),Plan(id='Premium',price=149.99,credits=20,guest_credits=2),Plan(id='Unlimited',price=249.99,credits=None,guest_credits=5,priority=True)]:s.add(p)
        shop_owner=User(phone_number='05550000002',full_name='Demo Dükkân Sahibi',role='SHOP_OWNER')
        s.add(shop_owner);s.flush()
        locations=[('Kordon Kahve','Alsancak, İzmir',38.4385,27.1416),('Saat Kulesi Coffee','Konak, İzmir',38.4192,27.1287),('Bornova Brew','Kazımdirik, Bornova, İzmir',38.4620,27.2161),('Karşıyaka Roastery','Karşıyaka, İzmir',38.4555,27.1103),('Bostanlı Espresso','Bostanlı, İzmir',38.4561,27.0964)]
        drinks=[('Espresso','Espresso Bazlı',65),('Americano','Espresso Bazlı',75),('Latte','Espresso Bazlı',95),('Cappuccino','Espresso Bazlı',90),('Flat White','Espresso Bazlı',100),('Filtre Kahve','Filtre Kahveler',80),('Cold Brew','Soğuk İçecekler',105),('Iced Latte','Soğuk İçecekler',110),('Türk Kahvesi','Diğer',70),('Mocha','Espresso Bazlı',115)]
        for name,addr,lat,lng in locations:
            sh=Shop(name=name,address=addr,lat=lat,lng=lng,owner_id=shop_owner.id)
            s.add(sh);s.flush()
            for name2,category,price in drinks:s.add(Product(shop_id=sh.id,name=name2,category=category,price=price))
        s.commit()
seed()
