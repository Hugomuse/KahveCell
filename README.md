# KahveCell ☕

FastAPI + React/Leaflet + PostgreSQL (Docker) tabanlı dijital kahve abonelik uygulaması. Case dokümanına dayalı, eğitim amaçlı uçtan uca demo.

## En kolay çalıştırma: Docker

Bilgisayarınızda Docker Desktop yüklüyse proje klasöründe:

```bash
docker compose up --build
```

- Web arayüzü: http://localhost:5173
- API / Swagger: http://localhost:8000/docs

Docker yerine yerel kurulum da mümkün:

```bash
cd backend
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --reload
```

İkinci terminalde:

```bash
cd frontend
npm install
npm run dev
```

Yerel backend varsayılan olarak SQLite dosyası kullanır. `docker compose` ile PostgreSQL kullanılır.

## Demo senaryosu

1. Müşteri için herhangi bir 10+ haneli telefonla giriş/kayıt yapın. OTP her zaman **1234**.
2. Paketlerden Starter, Premium veya Unlimited seçin. Başarılı ödeme kartı `4242-4242-4242-4242`; başarısız kart `4000-0000-0000-0002`.
3. Beş İzmir kahvecisinden birini seçip kahve özelleştirin; siparişi oluşturun ve QR kodunu görün.
4. Ayrı tarayıcıda dükkân sahibi telefonu **05550000002** ve OTP **1234** ile giriş yapın, panelden siparişi kabul edin, hazırlayın ve hazır durumuna getirin.
5. Müşteri QR ekranında **Demo QR içeriğini kopyala** düğmesine basıp dükkân panelindeki doğrulama alanına yapıştırarak teslim işlemini test edin. Bu akış bir demo kolaylaştırmasıdır; gerçek kamera ile okutma henüz eklenmemiştir.

## Özellikler

- OTP demo giriş, JWT access/refresh token, müşteri / dükkân sahibi rollerine göre API yetkilendirmesi
- Paket alma, paket değiştirme, iptal etme, hak ve misafir kredisi takibi
- Ödeme başarısı/başarısızlığı simülasyonu ve ödeme kayıtları
- Harita, arama, konum/mesafe sorgusu, beş örnek İzmir dükkânı ve 50 ürün
- Sipariş, özelleştirme, QR imzası (HMAC-SHA256), sipariş geçmişi, geçerli durum geçişleri
- Sipariş durumunu periyodik sorgulama ve dükkân sipariş paneli
- Otomatik Swagger/OpenAPI, docker compose

## Önemli sınırlamalar

Bu proje **geliştirme demosudur**, gerçek ödeme veya SMS servisi değildir. Sabit OTP, demo kartlar, şifre/OTP giriş kısıtlamalarının olmayışı, demo JWT secret varsayılanı nedeniyle internete açık üretim ortamına yüklenmemelidir. Üretim için gerçek OTP servisi, rate limiting, secret yönetimi, migration/Alembic, kapsamlı testler, işlem kilitleme/idempotency, ödeme sağlayıcısı ve güvenli QR tarayıcı gerekir.

**Case ile farklar:** Kullanıcı profili için temel API var ama arayüzde profil düzenleme yok; otomatik aylık yenileme scheduler'ı yok; açık/kapalı filtresi, gerçek puan/fotoğraf veri kaynağı, favori sipariş tekrarı ve kamera QR okuyucu henüz eklenmedi. Harita için başlangıç noktası İzmir'dir. UI sipariş takibi WebSocket yerine 4 saniyelik polling kullanır.

## Mimari

`frontend (React/Leaflet)` → REST `/api/v1` → `backend (FastAPI/SQLAlchemy)` → `PostgreSQL / SQLite`.

Backend iş mantığı bu sürümde tek `main.py` dosyasındadır; case'deki Controller/Service/Repository katman ayrımı bir sonraki refactor aşamasıdır.
