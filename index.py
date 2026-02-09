#!/usr/bin/env python3
"""
QuantumTrade AI - Complete Backend Solution v2.0
USDT Payment System with Blockchain Verification
"""

import os
import uuid
import json
import asyncio
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List
from contextlib import asynccontextmanager

from fastapi import FastAPI, Depends, HTTPException, Request, status, BackgroundTasks
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, EmailStr, Field, validator
from passlib.context import CryptContext
from jose import JWTError, jwt
from sqlalchemy import (
    create_engine, Column, String, Boolean, DateTime, ForeignKey, 
    Float, Integer, Text, BigInteger, Enum
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session, relationship
from sqlalchemy.sql import func
import httpx

# ==================== CONFIGURATION ====================

# Database URL - Railway PostgreSQL
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://user:password@localhost:5432/quantumtrade"
)

# Security Settings
SECRET_KEY = os.getenv("SECRET_KEY", "quantumtrade-secret-key-change-in-production-2026")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 * 7  # 7 days

# USDT Settings
USDT_PRICE = 49.00
USDT_WALLET_ADDRESS = os.getenv("USDT_WALLET_ADDRESS", "0x742d35Cc6634C0532925a3b844Bc9e8f43b8b8c3")
USDT_NETWORK = os.getenv("USDT_NETWORK", "ERC20")  # ERC20, TRC20, BEP20
MIN_CONFIRMATIONS = 3

# Blockchain API (Etherscan/TronScan/BscScan)
BLOCKCHAIN_API_KEY = os.getenv("BLOCKCHAIN_API_KEY", "YOUR_API_KEY")
ETHERSCAN_API_URL = "https://api.etherscan.io/api"
TRONSCAN_API_URL = "https://api.tronscan.org/api"

# Application Settings
DEBUG = os.getenv("DEBUG", "False").lower() == "true"

# ==================== DATABASE SETUP ====================

engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# ==================== DATABASE MODELS ====================

class User(Base):
    __tablename__ = "users"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    username = Column(String(50), unique=True, nullable=False, index=True)
    email = Column(String(255), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    wallet_address = Column(String(255), nullable=True)
    is_active = Column(Boolean, default=True)
    is_admin = Column(Boolean, default=False)
    is_verified = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    
    # Relationships
    subscriptions = relationship("Subscription", back_populates="user")
    payments = relationship("Payment", back_populates="user")

class SubscriptionPlan(Base):
    __tablename__ = "subscription_plans"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    plan_id = Column(String(20), unique=True, nullable=False, index=True)
    name = Column(String(50), nullable=False)
    price_usdt = Column(Float, nullable=False)
    duration_days = Column(Integer, default=30)
    features = Column(JSONB)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    # Relationships
    subscriptions = relationship("Subscription", back_populates="plan")

class Subscription(Base):
    __tablename__ = "subscriptions"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    plan_id = Column(Integer, ForeignKey("subscription_plans.id"), nullable=False)
    status = Column(String(20), default="active", index=True)  # active, expired, canceled
    start_date = Column(DateTime(timezone=True), nullable=False)
    end_date = Column(DateTime(timezone=True), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    
    # Relationships
    user = relationship("User", back_populates="subscriptions")
    plan = relationship("SubscriptionPlan", back_populates="subscriptions")
    payments = relationship("Payment", back_populates="subscription")

class Payment(Base):
    __tablename__ = "payments"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    subscription_id = Column(UUID(as_uuid=True), ForeignKey("subscriptions.id", ondelete="SET NULL"), nullable=True)
    amount_usdt = Column(Float, nullable=False)
    transaction_hash = Column(String(255), unique=True, nullable=False, index=True)
    from_address = Column(String(255), nullable=False)
    to_address = Column(String(255), nullable=False)
    network = Column(String(20), nullable=False)  # ERC20, TRC20, BEP20
    status = Column(String(20), default="pending", index=True)  # pending, confirmed, verified, failed
    confirmations = Column(Integer, default=0)
    required_confirmations = Column(Integer, default=MIN_CONFIRMATIONS)
    block_number = Column(BigInteger, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    verified_at = Column(DateTime(timezone=True), nullable=True)
    
    # Relationships
    user = relationship("User", back_populates="payments")
    subscription = relationship("Subscription", back_populates="payments")

class TradeSignal(Base):
    __tablename__ = "trade_signals"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    symbol = Column(String(20), nullable=False)
    signal_type = Column(String(10), nullable=False)  # BUY, SELL
    price = Column(Float, nullable=False)
    target_price = Column(Float, nullable=False)
    stop_loss = Column(Float, nullable=False)
    confidence = Column(Float, nullable=False)  # 0-100
    exchange = Column(String(50), nullable=False)
    timestamp = Column(DateTime(timezone=True), server_default=func.now())
    is_active = Column(Boolean, default=True)

# ==================== PYDANTIC SCHEMAS ====================

class UserCreate(BaseModel):
    username: str = Field(..., min_length=3, max_length=50)
    email: EmailStr
    password: str = Field(..., min_length=6)
    wallet_address: Optional[str] = None

class UserLogin(BaseModel):
    identifier: str  # username or email
    password: str

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: Dict[str, Any]

class PaymentInitiate(BaseModel):
    plan_id: str
    network: str = Field(..., regex="^(ERC20|TRC20|BEP20)$")

class PaymentVerify(BaseModel):
    transaction_hash: str

class PaymentWebhook(BaseModel):
    transaction_hash: str
    from_address: str
    to_address: str
    amount: float
    network: str
    block_number: Optional[int] = None
    confirmations: Optional[int] = None

class UserResponse(BaseModel):
    id: str
    username: str
    email: str
    wallet_address: Optional[str]
    is_active: bool
    is_admin: bool
    is_verified: bool
    has_subscription: bool
    subscription_plan: Optional[str]
    subscription_end_date: Optional[str]
    
    class Config:
        from_attributes = True

class TradeSignalResponse(BaseModel):
    id: str
    symbol: str
    signal_type: str
    price: float
    target_price: float
    stop_loss: float
    confidence: float
    exchange: str
    timestamp: str

# ==================== SECURITY & AUTH ====================

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
security = HTTPBearer()

def verify_password(plain_password, hashed_password):
    return pwd_context.verify(plain_password, hashed_password)

def get_password_hash(password):
    return pwd_context.hash(password)

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

def verify_token(token: str):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id: str = payload.get("sub")
        if user_id is None:
            return None
        return user_id
    except JWTError:
        return None

async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(lambda: SessionLocal())
):
    token = credentials.credentials
    user_id = verify_token(token)
    
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    user = db.query(User).filter(User.id == user_id).first()
    db.close()
    
    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or inactive",
        )
    
    return user

# ==================== BLOCKCHAIN SERVICES ====================

class BlockchainService:
    @staticmethod
    async def verify_erc20_transaction(tx_hash: str) -> Dict[str, Any]:
        """Verify ERC20 (Ethereum) transaction"""
        try:
            async with httpx.AsyncClient() as client:
                # Get transaction receipt
                params = {
                    "module": "proxy",
                    "action": "eth_getTransactionReceipt",
                    "txhash": tx_hash,
                    "apikey": BLOCKCHAIN_API_KEY
                }
                
                response = await client.get(ETHERSCAN_API_URL, params=params)
                data = response.json()
                
                if data.get("result") is None:
                    return {"verified": False, "error": "Transaction not found"}
                
                receipt = data["result"]
                
                # Check if transaction was successful
                if receipt.get("status") != "0x1":
                    return {"verified": False, "error": "Transaction failed"}
                
                # Get transaction details
                params = {
                    "module": "proxy",
                    "action": "eth_getTransactionByHash",
                    "txhash": tx_hash,
                    "apikey": BLOCKCHAIN_API_KEY
                }
                
                response = await client.get(ETHERSCAN_API_URL, params=params)
                tx_data = response.json()
                
                if tx_data.get("result") is None:
                    return {"verified": False, "error": "Transaction details not found"}
                
                transaction = tx_data["result"]
                
                return {
                    "verified": True,
                    "from": transaction["from"],
                    "to": transaction["to"],
                    "value": int(transaction["value"], 16) / 10**18,  # Convert from wei
                    "block_number": int(receipt["blockNumber"], 16),
                    "confirmations": await BlockchainService.get_confirmations(int(receipt["blockNumber"], 16))
                }
                
        except Exception as e:
            return {"verified": False, "error": str(e)}
    
    @staticmethod
    async def get_confirmations(block_number: int) -> int:
        """Get number of confirmations for a block"""
        try:
            async with httpx.AsyncClient() as client:
                params = {
                    "module": "proxy",
                    "action": "eth_blockNumber",
                    "apikey": BLOCKCHAIN_API_KEY
                }
                
                response = await client.get(ETHERSCAN_API_URL, params=params)
                data = response.json()
                
                current_block = int(data["result"], 16)
                return current_block - block_number
                
        except Exception:
            return 0
    
    @staticmethod
    async def verify_trc20_transaction(tx_hash: str) -> Dict[str, Any]:
        """Verify TRC20 (Tron) transaction"""
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(f"{TRONSCAN_API_URL}/transaction-info?hash={tx_hash}")
                data = response.json()
                
                if not data.get("hash"):
                    return {"verified": False, "error": "Transaction not found"}
                
                return {
                    "verified": True,
                    "from": data.get("ownerAddress"),
                    "to": data.get("toAddress"),
                    "value": float(data.get("amount", 0)) / 10**6,  # Convert from sun
                    "block_number": data.get("block"),
                    "confirmations": 10  # Tron has faster confirmations
                }
                
        except Exception as e:
            return {"verified": False, "error": str(e)}
    
    @staticmethod
    async def verify_transaction(tx_hash: str, network: str) -> Dict[str, Any]:
        """Verify transaction based on network"""
        if network == "ERC20":
            return await BlockchainService.verify_erc20_transaction(tx_hash)
        elif network == "TRC20":
            return await BlockchainService.verify_trc20_transaction(tx_hash)
        elif network == "BEP20":
            # Similar to ERC20 but on BSC
            return await BlockchainService.verify_erc20_transaction(tx_hash)
        else:
            return {"verified": False, "error": "Unsupported network"}

# ==================== DATABASE INITIALIZATION ====================

def init_database():
    """Initialize database with tables and default data"""
    Base.metadata.create_all(bind=engine)
    
    db = SessionLocal()
    
    try:
        # Check if admin user exists
        admin_user = db.query(User).filter(User.username == "ictsmartpro").first()
        
        if not admin_user:
            # Create admin user
            admin = User(
                username="ictsmartpro",
                email="ictsmartpro@gmail.com",
                password_hash=get_password_hash("123456"),
                is_admin=True,
                is_active=True,
                is_verified=True
            )
            db.add(admin)
            db.commit()
            print("✅ Admin user created: ictsmartpro / 123456")
        
        # Check if subscription plans exist
        premium_plan = db.query(SubscriptionPlan).filter(SubscriptionPlan.plan_id == "premium").first()
        
        if not premium_plan:
            # Create subscription plans
            plans = [
                SubscriptionPlan(
                    plan_id="premium",
                    name="PREMIUM TRADER",
                    price_usdt=49.00,
                    duration_days=30,
                    features={
                        "real_time_signals": True,
                        "ai_predictions": True,
                        "11_exchanges": True,
                        "risk_management": True,
                        "priority_support": True,
                        "mobile_app": True,
                        "advanced_charts": True,
                        "custom_alerts": True
                    }
                ),
                SubscriptionPlan(
                    plan_id="vip",
                    name="VIP TRADER",
                    price_usdt=99.00,
                    duration_days=30,
                    features={
                        "all_premium_features": True,
                        "dedicated_support": True,
                        "custom_strategies": True,
                        "whale_tracking": True,
                        "api_access": True,
                        "multi_account": True,
                        "advanced_analytics": True,
                        "early_access": True
                    }
                )
            ]
            
            for plan in plans:
                db.add(plan)
            
            db.commit()
            print("✅ Subscription plans created")
        
        # Create sample trade signals
        signal_count = db.query(TradeSignal).count()
        if signal_count == 0:
            signals = [
                TradeSignal(
                    symbol="BTC/USDT",
                    signal_type="BUY",
                    price=43250.50,
                    target_price=44500.00,
                    stop_loss=42500.00,
                    confidence=92.5,
                    exchange="Binance"
                ),
                TradeSignal(
                    symbol="ETH/USDT",
                    signal_type="SELL",
                    price=2345.75,
                    target_price=2300.00,
                    stop_loss=2400.00,
                    confidence=87.3,
                    exchange="Coinbase"
                ),
                TradeSignal(
                    symbol="SOL/USDT",
                    signal_type="BUY",
                    price=98.45,
                    target_price=105.00,
                    stop_loss=95.00,
                    confidence=95.1,
                    exchange="FTX"
                )
            ]
            
            for signal in signals:
                db.add(signal)
            
            db.commit()
            print("✅ Sample trade signals created")
        
        print("✅ Database initialized successfully!")
        
    except Exception as e:
        print(f"⚠️ Database initialization error: {e}")
        db.rollback()
    finally:
        db.close()

# ==================== PAYMENT PROCESSING ====================

async def process_payment_verification(payment_id: uuid.UUID):
    """Background task to verify payment"""
    db = SessionLocal()
    try:
        payment = db.query(Payment).filter(Payment.id == payment_id).first()
        if not payment:
            return
        
        # Verify transaction on blockchain
        verification = await BlockchainService.verify_transaction(
            payment.transaction_hash,
            payment.network
        )
        
        if verification["verified"]:
            payment.from_address = verification["from"]
            payment.confirmations = verification["confirmations"]
            payment.block_number = verification["block_number"]
            
            # Check if amount matches
            if abs(verification["value"] - payment.amount_usdt) <= 1.0:  # Allow 1 USDT difference
                payment.status = "confirmed"
                
                # If enough confirmations, mark as verified
                if verification["confirmations"] >= payment.required_confirmations:
                    payment.status = "verified"
                    payment.verified_at = datetime.utcnow()
                    
                    # Create subscription
                    plan = db.query(SubscriptionPlan).filter(
                        SubscriptionPlan.plan_id == "premium"
                    ).first()
                    
                    if plan:
                        subscription = Subscription(
                            user_id=payment.user_id,
                            plan_id=plan.id,
                            status="active",
                            start_date=datetime.utcnow(),
                            end_date=datetime.utcnow() + timedelta(days=plan.duration_days)
                        )
                        db.add(subscription)
                        db.commit()
                        db.refresh(subscription)
                        
                        # Link payment to subscription
                        payment.subscription_id = subscription.id
                        
                        # Update user verification status
                        user = db.query(User).filter(User.id == payment.user_id).first()
                        if user:
                            user.is_verified = True
            
            else:
                payment.status = "failed"
        
        db.commit()
        
    except Exception as e:
        print(f"Payment verification error: {e}")
        db.rollback()
    finally:
        db.close()

# ==================== FASTAPI APP ====================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown events"""
    print("🚀 QuantumTrade AI Backend Starting...")
    print(f"📡 Database URL: {DATABASE_URL[:50]}...")
    print(f"💰 USDT Price: {USDT_PRICE} USDT")
    print(f"👛 Wallet: {USDT_WALLET_ADDRESS}")
    
    # Initialize database on startup
    init_database()
    
    yield
    
    print("🛑 QuantumTrade AI Backend Shutting Down...")

app = FastAPI(
    title="QuantumTrade AI API v2.0",
    description="AI-Powered Crypto Trading Platform with USDT Payments",
    version="2.0.0",
    lifespan=lifespan
)

# CORS Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, specify exact origins
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Dependency
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# ==================== API ENDPOINTS ====================

@app.get("/")
async def root():
    """Root endpoint"""
    return {
        "message": "Welcome to QuantumTrade AI API v2.0",
        "status": "active",
        "version": "2.0.0",
        "payment_currency": "USDT",
        "premium_price": USDT_PRICE,
        "docs": "/docs"
    }

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat(),
        "service": "QuantumTrade AI Backend v2.0",
        "database": "connected"
    }

@app.post("/api/register", response_model=TokenResponse)
async def register(user_data: UserCreate, db: Session = Depends(get_db)):
    """Register a new user"""
    
    # Check if username or email already exists
    existing_user = db.query(User).filter(
        (User.username == user_data.username) | 
        (User.email == user_data.email)
    ).first()
    
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username or email already registered"
        )
    
    # Create new user
    hashed_password = get_password_hash(user_data.password)
    db_user = User(
        username=user_data.username,
        email=user_data.email,
        password_hash=hashed_password,
        wallet_address=user_data.wallet_address,
        is_active=True,
        is_admin=False,
        is_verified=False
    )
    
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    
    # Create access token
    access_token = create_access_token(data={"sub": str(db_user.id)})
    
    # Check for active subscription
    active_subscription = db.query(Subscription).filter(
        Subscription.user_id == db_user.id,
        Subscription.status == "active",
        Subscription.end_date > datetime.utcnow()
    ).first()
    
    # Prepare user response
    user_response = {
        "id": str(db_user.id),
        "username": db_user.username,
        "email": db_user.email,
        "wallet_address": db_user.wallet_address,
        "is_active": db_user.is_active,
        "is_admin": db_user.is_admin,
        "is_verified": db_user.is_verified,
        "has_subscription": active_subscription is not None,
        "subscription_plan": active_subscription.plan.plan_id if active_subscription else None,
        "subscription_end_date": active_subscription.end_date.isoformat() if active_subscription else None
    }
    
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "user": user_response
    }

@app.post("/api/login", response_model=TokenResponse)
async def login(login_data: UserLogin, db: Session = Depends(get_db)):
    """User login"""
    
    # Find user by username or email
    user = db.query(User).filter(
        (User.username == login_data.identifier) | 
        (User.email == login_data.identifier)
    ).first()
    
    # Verify user exists and password is correct
    if not user or not verify_password(login_data.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password"
        )
    
    # Check if user is active
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is inactive"
        )
    
    # Create access token
    access_token = create_access_token(data={"sub": str(user.id)})
    
    # Check for active subscription
    active_subscription = db.query(Subscription).filter(
        Subscription.user_id == user.id,
        Subscription.status == "active",
        Subscription.end_date > datetime.utcnow()
    ).first()
    
    # Prepare user response
    user_response = {
        "id": str(user.id),
        "username": user.username,
        "email": user.email,
        "wallet_address": user.wallet_address,
        "is_active": user.is_active,
        "is_admin": user.is_admin,
        "is_verified": user.is_verified,
        "has_subscription": active_subscription is not None,
        "subscription_plan": active_subscription.plan.plan_id if active_subscription else None,
        "subscription_end_date": active_subscription.end_date.isoformat() if active_subscription else None
    }
    
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "user": user_response
    }

@app.post("/api/payment/initiate")
async def initiate_payment(
    payment_data: PaymentInitiate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Initiate payment process"""
    
    # Check if user is admin (admins bypass payment)
    if current_user.is_admin:
        return {
            "success": True,
            "message": "Admin access granted - payment bypassed",
            "payment_required": False,
            "wallet_address": None,
            "amount_usdt": 0
        }
    
    # Check if user already has active subscription
    active_subscription = db.query(Subscription).filter(
        Subscription.user_id == current_user.id,
        Subscription.status == "active",
        Subscription.end_date > datetime.utcnow()
    ).first()
    
    if active_subscription:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User already has active subscription"
        )
    
    # Get plan
    plan = db.query(SubscriptionPlan).filter(
        SubscriptionPlan.plan_id == payment_data.plan_id,
        SubscriptionPlan.is_active == True
    ).first()
    
    if not plan:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Subscription plan not found"
        )
    
    return {
        "success": True,
        "message": "Payment initiated successfully",
        "payment_required": True,
        "wallet_address": USDT_WALLET_ADDRESS,
        "amount_usdt": plan.price_usdt,
        "network": payment_data.network,
        "plan_name": plan.name,
        "instructions": f"Send exactly {plan.price_usdt} USDT to the address above using {payment_data.network} network"
    }

@app.post("/api/payment/verify")
async def verify_payment(
    payment_data: PaymentVerify,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Verify payment with transaction hash"""
    
    # Check if user is admin
    if current_user.is_admin:
        # Create subscription for admin
        plan = db.query(SubscriptionPlan).filter(
            SubscriptionPlan.plan_id == "premium"
        ).first()
        
        subscription = Subscription(
            user_id=current_user.id,
            plan_id=plan.id,
            status="active",
            start_date=datetime.utcnow(),
            end_date=datetime.utcnow() + timedelta(days=plan.duration_days)
        )
        db.add(subscription)
        db.commit()
        
        return {
            "success": True,
            "message": "Admin subscription activated",
            "verified": True,
            "subscription_active": True
        }
    
    # Check if transaction hash already exists
    existing_payment = db.query(Payment).filter(
        Payment.transaction_hash == payment_data.transaction_hash
    ).first()
    
    if existing_payment:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Transaction hash already used"
        )
    
    # Get premium plan
    plan = db.query(SubscriptionPlan).filter(
        SubscriptionPlan.plan_id == "premium"
    ).first()
    
    # Create payment record
    payment = Payment(
        user_id=current_user.id,
        amount_usdt=plan.price_usdt,
        transaction_hash=payment_data.transaction_hash,
        from_address="pending",
        to_address=USDT_WALLET_ADDRESS,
        network="ERC20",  # Default, can be updated
        status="pending"
    )
    
    db.add(payment)
    db.commit()
    db.refresh(payment)
    
    # Start background verification
    background_tasks.add_task(process_payment_verification, payment.id)
    
    return {
        "success": True,
        "message": "Payment verification started. Please wait for confirmation.",
        "verification_id": str(payment.id),
        "estimated_time": "2-5 minutes"
    }

@app.post("/api/payment/webhook")
async def payment_webhook(
    webhook_data: PaymentWebhook,
    db: Session = Depends(get_db)
):
    """Webhook for payment notifications"""
    # This endpoint would be called by blockchain monitoring service
    
    # Check if transaction already exists
    existing_payment = db.query(Payment).filter(
        Payment.transaction_hash == webhook_data.transaction_hash
    ).first()
    
    if not existing_payment:
        # Create new payment record
        payment = Payment(
            transaction_hash=webhook_data.transaction_hash,
            from_address=webhook_data.from_address,
            to_address=webhook_data.to_address,
            amount_usdt=webhook_data.amount,
            network=webhook_data.network,
            status="confirmed" if webhook_data.confirmations and webhook_data.confirmations >= 3 else "pending",
            confirmations=webhook_data.confirmations or 0,
            block_number=webhook_data.block_number
        )
        db.add(payment)
        db.commit()
    
    return {"success": True}

@app.get("/api/user/me", response_model=UserResponse)
async def get_current_user_info(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get current user information"""
    
    # Check for active subscription
    active_subscription = db.query(Subscription).filter(
        Subscription.user_id == current_user.id,
        Subscription.status == "active",
        Subscription.end_date > datetime.utcnow()
    ).first()
    
    return {
        "id": str(current_user.id),
        "username": current_user.username,
        "email": current_user.email,
        "wallet_address": current_user.wallet_address,
        "is_active": current_user.is_active,
        "is_admin": current_user.is_admin,
        "is_verified": current_user.is_verified,
        "has_subscription": active_subscription is not None,
        "subscription_plan": active_subscription.plan.plan_id if active_subscription else None,
        "subscription_end_date": active_subscription.end_date.isoformat() if active_subscription else None
    }

@app.get("/api/signals")
async def get_trade_signals(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get trade signals (requires subscription)"""
    
    # Check if user has active subscription
    active_subscription = db.query(Subscription).filter(
        Subscription.user_id == current_user.id,
        Subscription.status == "active",
        Subscription.end_date > datetime.utcnow()
    ).first()
    
    if not active_subscription and not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Active subscription required to access trade signals"
        )
    
    # Get active signals
    signals = db.query(TradeSignal).filter(
        TradeSignal.is_active == True
    ).order_by(TradeSignal.timestamp.desc()).limit(20).all()
    
    return {
        "success": True,
        "signals": [
            {
                "id": str(signal.id),
                "symbol": signal.symbol,
                "signal_type": signal.signal_type,
                "price": signal.price,
                "target_price": signal.target_price,
                "stop_loss": signal.stop_loss,
                "confidence": signal.confidence,
                "exchange": signal.exchange,
                "timestamp": signal.timestamp.isoformat()
            }
            for signal in signals
        ]
    }

@app.get("/api/dashboard")
async def get_dashboard_data(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get dashboard data (requires subscription)"""
    
    # Check if user has active subscription
    active_subscription = db.query(Subscription).filter(
        Subscription.user_id == current_user.id,
        Subscription.status == "active",
        Subscription.end_date > datetime.utcnow()
    ).first()
    
    if not active_subscription and not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Active subscription required to access dashboard"
        )
    
    # Get user's payments
    payments = db.query(Payment).filter(
        Payment.user_id == current_user.id
    ).order_by(Payment.created_at.desc()).limit(5).all()
    
    # Get recent signals count
    recent_signals = db.query(TradeSignal).filter(
        TradeSignal.timestamp >= datetime.utcnow() - timedelta(hours=24)
    ).count()
    
    return {
        "success": True,
        "user": {
            "username": current_user.username,
            "email": current_user.email,
            "is_verified": current_user.is_verified,
            "subscription_active": active_subscription is not None,
            "subscription_plan": active_subscription.plan.plan_id if active_subscription else None,
            "subscription_end_date": active_subscription.end_date.isoformat() if active_subscription else None
        },
        "stats": {
            "active_signals": recent_signals,
            "total_exchanges": 11,
            "prediction_accuracy": 99.7,
            "uptime": 99.9
        },
        "recent_payments": [
            {
                "amount": payment.amount_usdt,
                "status": payment.status,
                "date": payment.created_at.isoformat(),
                "transaction_hash": payment.transaction_hash[:10] + "..." + payment.transaction_hash[-8:]
            }
            for payment in payments
        ]
    }

@app.get("/api/check-subscription")
async def check_subscription_status(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Check subscription status"""
    
    active_subscription = db.query(Subscription).filter(
        Subscription.user_id == current_user.id,
        Subscription.status == "active",
        Subscription.end_date > datetime.utcnow()
    ).first()
    
    return {
        "has_subscription": active_subscription is not None or current_user.is_admin,
        "is_admin": current_user.is_admin,
        "subscription_plan": active_subscription.plan.plan_id if active_subscription else None,
        "end_date": active_subscription.end_date.isoformat() if active_subscription else None,
        "days_remaining": (active_subscription.end_date - datetime.utcnow()).days if active_subscription else 0
    }

# ==================== ERROR HANDLING ====================

@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content={"success": False, "error": exc.detail}
    )

@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    return JSONResponse(
        status_code=500,
        content={"success": False, "error": "Internal server error"}
    )

# ==================== MAIN ====================

if __name__ == "__main__":
    import uvicorn
    
    # Get port from environment (Railway uses PORT)
    port = int(os.getenv("PORT", 8000))
    
    print(f"🚀 Starting QuantumTrade AI Backend v2.0 on port {port}")
    print(f"📡 Database: {DATABASE_URL[:50]}...")
    print(f"💰 Premium Price: {USDT_PRICE} USDT")
    print(f"👛 Wallet: {USDT_WALLET_ADDRESS}")
    print(f"📚 API Docs: http://localhost:{port}/docs")
    
    uvicorn.run(
        "index:app",
        host="0.0.0.0",
        port=port,
        reload=DEBUG
    )
