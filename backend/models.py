"""Veritabanı tabloları: users ve sessions."""
from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, DateTime, Integer, String

from database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    first_name = Column(String(100), nullable=True)
    last_name = Column(String(100), nullable=True)
    tc_no = Column(String(11), unique=True, nullable=True, index=True)
    phone = Column(String(20), unique=True, nullable=True, index=True)
    birth_year = Column(Integer, nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)


class SessionRecord(Base):
    __tablename__ = "sessions"

    id = Column(Integer, primary_key=True, index=True)
    ip_address = Column(String(45), nullable=False)
    mac_address = Column(String(17), nullable=False)
    username = Column(String(100), nullable=False, index=True)  # TC no veya telefon
    session_token = Column(String(64), nullable=False, index=True)
    login_time = Column(DateTime(timezone=True), default=utcnow, nullable=False)
    logout_time = Column(DateTime(timezone=True), nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)


class SiteVisit(Base):
    """DNS sorgusundan türetilen, kullanıcıya bağlanmış site ziyareti kaydı."""
    __tablename__ = "site_visits"

    id = Column(Integer, primary_key=True, index=True)
    timestamp = Column(DateTime(timezone=True), default=utcnow, nullable=False, index=True)
    username = Column(String(100), nullable=False, index=True)  # TC no veya telefon; eşleşmezse "(kimliksiz)"
    ip_address = Column(String(45), nullable=False, index=True)
    mac_address = Column(String(17), nullable=False)
    domain = Column(String(255), nullable=False, index=True)
    query_type = Column(String(10), nullable=False)
