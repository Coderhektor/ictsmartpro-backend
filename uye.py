# uye.py - PostgreSQL + SQLAlchemy (Railway & Production Uyumlu - SON HAL)

import os
import logging
from datetime import datetime
from sqlalchemy import create_engine, Column, String, DateTime, func
from sqlalchemy.orm import sessionmaker, declarative_base, Session

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# DATABASE_URL
DATABASE_URL = os.getenv("DATABASE_URL")
if DATABASE_URL and DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

if not DATABASE_URL:
    raise ValueError("DATABASE_URL eksik! Railway'de PostgreSQL reference ekleyin.")

# Engine (production ayarları)
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

# Model
class Uye(Base):
    __tablename__ = "uyeler"

    email = Column(String, primary_key=True, index=True)
    ad_soyad = Column(String, nullable=False)
    customer_id = Column(String, unique=True, nullable=True)
    durum = Column(String, nullable=False, default="inactive")  # inactive, pending, active, past_due, canceled
    plan = Column(String, nullable=True)  # basic, pro, premium
    baslangic_tarihi = Column(DateTime(timezone=True), nullable=True)
    bitis_tarihi = Column(DateTime(timezone=True), nullable=True)
    kayit_tarihi = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    guncellenme_tarihi = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

# Tablo oluştur
Base.metadata.create_all(bind=engine)

# Fonksiyonlar (hepsi aynı session mantığıyla)
def uye_ekle(email: str, ad_soyad: str, customer_id: str) -> str:
    db = SessionLocal()
    try:
        uye = Uye(
            email=email.lower(),
            ad_soyad=ad_soyad,
            customer_id=customer_id,
            durum="pending"
        )
        db.add(uye)
        db.commit()
        db.refresh(uye)
        logger.info(f"Üye eklendi: {email}")
        return email.lower()
    except Exception as e:
        db.rollback()
        logger.error(f"Üye ekleme hatası ({email}): {e}")
        raise
    finally:
        db.close()

def abonelik_guncelle(email: str, durum: str, plan: str = None,
                      baslangic: datetime = None, bitis: datetime = None):
    db = SessionLocal()
    try:
        uye = db.query(Uye).filter(Uye.email == email.lower()).first()
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
        logger.info(f"Abonelik güncellendi: {email} → {durum} ({plan or uye.plan})")
        return True
    except Exception as e:
        db.rollback()
        logger.error(f"Abonelik güncelleme hatası ({email}): {e}")
        return False
    finally:
        db.close()

def uye_getir(email: str) -> dict | None:
    db = SessionLocal()
    try:
        uye = db.query(Uye).filter(Uye.email == email.lower()).first()
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
    finally:
        db.close()

def abonelik_aktif_mi(email: str) -> bool:
    uye = uye_getir(email.lower())
    if not uye:
        return False
    if uye["durum"] != "active":
        return False
    if uye["bitis_tarihi"]:
        if datetime.utcnow() > uye["bitis_tarihi"].replace(tzinfo=None):
            return False
    return True