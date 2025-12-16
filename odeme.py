# odeme.py (SON HAL – WEBHOOK'SUZ, SADECE İŞ MANTIĞI)

import os
import stripe
import logging
from datetime import datetime, timezone
from uye import uye_ekle, abonelik_guncelle

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Stripe ayarları
stripe.api_key = os.getenv("STRIPE_SECRET_KEY")
WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET")

if not stripe.api_key:
    raise ValueError("STRIPE_SECRET_KEY eksik!")
if not WEBHOOK_SECRET:
    raise ValueError("STRIPE_WEBHOOK_SECRET eksik!")

# PLANLAR – LÜTFEN GERÇEK PRICE ID'LERİ YAZ!
PLANLAR = {
    "basic": {"price_id": "price_1RealBasicIDBuraya", "ad": "Basic", "fiyat": 999},
    "pro": {"price_id": "price_1RealProIDBuraya", "ad": "Pro", "fiyat": 2499},
    "premium": {"price_id": "price_1RealPremiumIDBuraya", "ad": "Premium", "fiyat": 4999},
}

def musteri_olustur(email: str, ad_soyad: str) -> str:
    email = email.lower()
    customers = stripe.Customer.list(email=email, limit=1)
    if customers.data:
        logger.info(f"Mevcut müşteri bulundu: {email}")
        return customers.data[0].id

    customer = stripe.Customer.create(
        email=email,
        name=ad_soyad,
        metadata={"created_by": "ictsmartpro.ai"}
    )
    logger.info(f"Yeni Stripe müşteri oluşturuldu: {email}")
    return customer.id

def odeme_linki_olustur(email: str, ad_soyad: str, plan: str) -> str:
    if plan not in PLANLAR:
        raise ValueError("Geçersiz plan: basic, pro, premium")

    email = email.lower()
    customer_id = musteri_olustur(email, ad_soyad)
    uye_ekle(email, ad_soyad, customer_id)

    try:
        session = stripe.checkout.Session.create(
            payment_method_types=["card"],
            customer=customer_id,
            line_items=[{"price": PLANLAR[plan]["price_id"], "quantity": 1}],
            mode="subscription",
            subscription_data={
                "metadata": {
                    "email": email,
                    "plan": plan
                }
            },
            success_url="https://ictsmartpro.ai/odeme/basarili?session_id={CHECKOUT_SESSION_ID}",
            cancel_url="https://ictsmartpro.ai/odeme/iptal",
            allow_promotion_codes=True,
            billing_address_collection="required",
        )
        logger.info(f"Ödeme linki oluşturuldu: {email} → {plan}")
        return session.url
    except Exception as e:
        logger.error(f"Checkout session hatası: {e}")
        raise

# ------------------- WEBHOOK HANDLER FONKSİYONLARI (main.py'de kullanılacak) -------------------

def handle_checkout_completed(session):
    if session.mode != "subscription" or session.payment_status != "paid":
        return
    sub = stripe.Subscription.retrieve(session.subscription, expand=["customer"])
    email = session.metadata.get("email") or (sub.customer.email if hasattr(sub.customer, "email") else None)
    if not email:
        logger.error("Webhook: Email bulunamadı (checkout.session.completed)")
        return

    price_id = sub.items.data[0].price.id
    plan = next((k for k, v in PLANLAR.items() if v["price_id"] == price_id), "unknown")

    abonelik_guncelle(
        email=email.lower(),
        durum="active",
        plan=plan,
        baslangic=datetime.fromtimestamp(sub.current_period_start, tz=timezone.utc),
        bitis=datetime.fromtimestamp(sub.current_period_end, tz=timezone.utc)
    )
    logger.info(f"WEBHOOK → Yeni abonelik aktif: {email} → {plan}")

def handle_invoice_paid(invoice):
    if not invoice.subscription:
        return
    sub = stripe.Subscription.retrieve(invoice.subscription, expand=["customer"])
    email = sub.customer.email if hasattr(sub.customer, "email") else None
    if not email:
        return

    price_id = sub.items.data[0].price.id
    plan = next((k for k, v in PLANLAR.items() if v["price_id"] == price_id), "unknown")

    abonelik_guncelle(
        email=email.lower(),
        durum="active",
        plan=plan,
        baslangic=datetime.fromtimestamp(sub.current_period_start, tz=timezone.utc),
        bitis=datetime.fromtimestamp(sub.current_period_end, tz=timezone.utc)
    )
    logger.info(f"WEBHOOK → Aylık ödeme alındı: {email}")

def handle_invoice_failed(invoice):
    if not invoice.subscription:
        return
    sub = stripe.Subscription.retrieve(invoice.subscription, expand=["customer"])
    email = sub.customer.email if hasattr(sub.customer, "email") else None
    if email:
        abonelik_guncelle(email=email.lower(), durum="past_due")
        logger.warning(f"WEBHOOK → Ödeme başarısız: {email}")

def handle_subscription_deleted(subscription):
    customer = stripe.Customer.retrieve(subscription.customer) if isinstance(subscription.customer, str) else subscription.customer
    email = customer.email if customer and hasattr(customer, "email") else None
    if email:
        abonelik_guncelle(email=email.lower(), durum="canceled")
        logger.info(f"WEBHOOK → Abonelik iptal: {email}")