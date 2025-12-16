# uye.py – PostgreSQL + SQLAlchemy 2.0+ (Railway Uyumlu – Mükemmel Versiyon)

import os
import logging
from datetime import datetime
from typing import Dict, Optional

from sqlalchemy import create_engine, Column, String, DateTime, func
from sqlalchemy.orm import sessionmaker, declarative_base, Session

# Logging (diğer dosyalarda aynı format olsun diye)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s"
)
logger = logging.getLogger("uye")

# DATABASE_URL (Railway reference ile otomatik gelir)
DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    raise ValueError("DATABASE_URL environment variable eksik! Railway'de PostgreSQL reference ekleyin.")

# postgres:// → postgresql:// düzeltmesi (SQLAlchemy 2.0+ için zorunlu)
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

# Engine – Production ayarları
engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    pool_size=5,
    max_overflow=10,
    pool_timeout=30,
    connect_args={"connect_timeout": 10}
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# ====================== MODEL ======================
class Uye(Base):
    __tablename__ = "uyeler"

    email = Column(String, primary_key=True, index=True, nullable=False)
    ad_soyad = Column(String, nullable=False)
    customer_id = Column(String, unique=True, nullable=True)  # Stripe Customer ID
    durum = Column(String, nullable=False, default="inactive")  # inactive, pending, active, past_due, canceled
    plan = Column(String, nullable=True)  # basic, pro, premium
    baslangic_tarihi = Column(DateTime(timezone=True), nullable=True)
    bitis_tarihi = Column(DateTime(timezone=True), nullable=True)
    kayit_tarihi = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    guncellenme_tarihi = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False
    )

# Tabloyu otomatik oluştur (ilk deploy'da)
Base.metadata.create_all(bind=engine)

# ====================== YARDIMCI FONKSİYONLAR ======================
def get_db_session() -> Session:
    """Tek kullanımlık güvenli session"""
    db = SessionLocal()
    try:
        return db
    except Exception as e:
        logger.error(f"DB session hatası: {e}")
        raise

# ====================== ANA FONKSİYONLAR ======================
def uye_ekle(email: str, ad_soyad: str, customer_id: str) -> str:
    """Ödeme linki oluşturulurken üye kaydı (pending)"""
    email = email.strip().lower()
    db = get_db_session()
    try:
        uye = Uye(
            email=email,
            ad_soyad=ad_soyad.strip(),
            customer_id=customer_id,
            durum="pending"
        )
        db.add(uye)
        db.commit()
        db.refresh(uye)
        logger.info(f"✅ Yeni üye kaydedildi: {email}")
        return email
    except Exception as e:
        db.rollback()
        logger.error(f"❌ Üye ekleme hatası ({email}): {e}")
        raise
    finally:
        db.close()

def abonelik_guncelle(
    email: str,
    durum: str,
    plan: Optional[str] = None,
    baslangic: Optional[datetime] = None,
    bitis: Optional[datetime] = None
) -> bool:
    """Webhook'lerden gelen güncellemeler"""
    email = email.strip().lower()
    db = get_db_session()
    try:
        uye = db.query(Uye).filter(Uye.email == email).first()
        if not uye:
            logger.warning(f"Güncellenecek üye bulunamadı: {email}")
            return False

        uye.durum = durum
        if plan is not None:
            uye.plan = plan
        if baslangic is not None:
            uye.baslangic_tarihi = baslangic
        if bitis is not None:
            uye.bitis_tarihi = bitis

        db.commit()
        logger.info(f"✅ Abonelik güncellendi: {email} → {durum} ({plan or uye.plan})")
        return True
    except Exception as e:
        db.rollback()
        logger.error(f"❌ Abonelik güncelleme hatası ({email}): {e}")
        return False
    finally:
        db.close()

def uye_getir(email: str) -> Optional[Dict]:
    """Kullanıcı bilgilerini getir"""
    email = email.strip().lower()
    db = get_db_session()
    try:
        uye = db.query(Uye).filter(Uye.email == email).first()
        if not uye:
            return None
        return {
            "email": uye.email,
            "ad_soyad": uye.ad_soyad,
            "customer_id": uye.customer_id,
            "durum": uye.durum,
            "plan": uye.plan,
            "baslangic_tarihi": uye.baslangic_tarihi,
            "bitis_tarihi": uye.bitis_tarihi,
            "kayit_tarihi": uye.kayit_tarihi,
            "guncellenme_tarihi": uye.guncellenme_tarihi,
        }
    except Exception as e:
        logger.error(f"❌ Üye getirme hatası ({email}): {e}")
        return None
    finally:
        db.close()

def abonelik_aktif_mi(email: str) -> bool:
    """Giriş ve erişim kontrolü için – EN KRİTİK FONKSİYON"""
    email = email.strip().lower()
    try:
        uye = uye_getir(email)
        if not uye:
            return False
        if uye["durum"] != "active":
            return False
        bitis = uye.get("bitis_tarihi")
        if bitis and datetime.utcnow() > bitis.replace(tzinfo=None):
            logger.info(f"Süresi dolmuş abonelik: {email}")
            return False
        return True
    except Exception as e:
        logger.error(f"abonelik_aktif_mi hatası ({email}): {e}")
        return False

# ====================== EKSTRA: Admin İçin Yardımcı ======================
def tum_uyeler() -> list:
    """Admin paneli için (isteğe bağlı)"""
    db = get_db_session()
    try:
        uyeler = db.query(Uye).all()
        return [uye_getir(u.email) for u in uyeler]
    finally:
        db.close()

# ====================== BAŞLANGIÇ LOGU ======================
logger.info("🚀 uye.py yüklendi – PostgreSQL bağlantısı hazır!")
