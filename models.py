# models.py
from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


class PromoCode(Base):
    __tablename__ = "promo_codes"

    id = Column(Integer, primary_key=True, index=True)
    code = Column(String(64), unique=True, index=True, nullable=False)
    bonus_questions = Column(Integer, nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=True)

    max_redemptions = Column(Integer, nullable=False, default=1)
    redemptions_used = Column(Integer, nullable=False, default=0)

    notes = Column(String(255), nullable=True)

    redemptions = relationship("PromoRedemption", back_populates="promo_code")


class PromoRedemption(Base):
    __tablename__ = "promo_redemptions"

    id = Column(Integer, primary_key=True, index=True)
    promo_code_id = Column(Integer, ForeignKey("promo_codes.id"), nullable=False)
    device_id = Column(String(128), nullable=False, index=True)
    redeemed_at = Column(DateTime(timezone=True), nullable=False)

    promo_code = relationship("PromoCode", back_populates="redemptions")
