from datetime import datetime
from typing import Optional
from sqlalchemy import BigInteger, String, Boolean, ForeignKey, DateTime, Integer, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.ext.asyncio import AsyncAttrs

class Base(AsyncAttrs, DeclarativeBase):
    pass


class UserDiscipline(Base):
    """НА, порушення, остання причина Зв — окремо від профілю, зв’язок 1:1 по tg_id."""
    __tablename__ = "user_discipline"
    tg_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.tg_id", ondelete="CASCADE"), primary_key=True)
    na_count: Mapped[int] = mapped_column(Integer, default=0)
    violations_count: Mapped[int] = mapped_column(Integer, default=0)
    last_zv_reason: Mapped[str] = mapped_column(String, nullable=True)
    user: Mapped["User"] = relationship(back_populates="discipline")


class User(Base):
    __tablename__ = 'users'
    tg_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    list_number: Mapped[int] = mapped_column(Integer, nullable=True)
    full_name: Mapped[str] = mapped_column(String)
    username: Mapped[str] = mapped_column(String, nullable=True)
    phone_number: Mapped[str] = mapped_column(String, nullable=True)
    address: Mapped[str] = mapped_column(String, nullable=True)
    in_dorm: Mapped[bool] = mapped_column(Boolean, default=True)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    is_female: Mapped[bool] = mapped_column(Boolean, default=False)
    discipline: Mapped[Optional[UserDiscipline]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
        passive_deletes=True,
        uselist=False,
        lazy="selectin",
    )

    @property
    def na_count(self) -> int:
        return self.discipline.na_count if self.discipline is not None else 0

    @property
    def violations_count(self) -> int:
        return self.discipline.violations_count if self.discipline is not None else 0

    @property
    def last_zv_reason(self) -> Optional[str]:
        return self.discipline.last_zv_reason if self.discipline is not None else None

class Approval(Base):
    __tablename__ = 'approvals'
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger)
    type: Mapped[str] = mapped_column(String) 
    field: Mapped[str] = mapped_column(String, nullable=True) 
    old_value: Mapped[str] = mapped_column(String, nullable=True)
    new_value: Mapped[str] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    correspondence: Mapped[str] = mapped_column(String, nullable=True)


class ZvApprovedReport(Base):
    """Збережений звіт Зв після погодження командиром (для експорту «на тиждень»)."""
    __tablename__ = 'zv_approved_reports'
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger)
    payload_json: Mapped[str] = mapped_column(String)
    approved_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())

class Poll(Base):
    __tablename__ = 'polls'
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tg_poll_id: Mapped[str] = mapped_column(String, unique=True)
    message_id: Mapped[int] = mapped_column(BigInteger)
    chat_id: Mapped[int] = mapped_column(BigInteger)
    type: Mapped[str] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    report_text: Mapped[str] = mapped_column(String, nullable=True)

class Vote(Base):
    __tablename__ = 'votes'
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    poll_id: Mapped[int] = mapped_column(Integer, ForeignKey('polls.id', ondelete='CASCADE'))
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey('users.tg_id', ondelete='CASCADE'))
    option_selected: Mapped[str] = mapped_column(String)

class Setting(Base):
    __tablename__ = 'settings'
    key: Mapped[str] = mapped_column(String, primary_key=True)
    value: Mapped[str] = mapped_column(String)

class Schedule(Base):
    __tablename__ = 'schedule'
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    day: Mapped[str] = mapped_column(String)
    pair_num: Mapped[int] = mapped_column(Integer)
    lesson_text: Mapped[str] = mapped_column(String)
    is_next_week: Mapped[bool] = mapped_column(Boolean, default=False)
    date_str: Mapped[str] = mapped_column(String, nullable=True)
    location_text: Mapped[str] = mapped_column(String, nullable=True)