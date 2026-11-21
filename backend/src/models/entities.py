from datetime import datetime, timezone
from sqlalchemy import String, Integer, JSON, DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from src.config.database import Base

def now(): return datetime.now(timezone.utc).replace(tzinfo=None)
class User(Base):
    __tablename__='users'
    id: Mapped[int]=mapped_column(primary_key=True)
    email: Mapped[str]=mapped_column(String(120),unique=True)
    role: Mapped[str]=mapped_column(String(20))
    password_hash: Mapped[str]=mapped_column(String(250))
class LogSet(Base):
    __tablename__='log_sets'
    id: Mapped[int]=mapped_column(primary_key=True)
    name: Mapped[str]=mapped_column(String(100),unique=True)
    initial: Mapped[dict]=mapped_column(JSON)
    records: Mapped[list]=mapped_column(JSON)
    description: Mapped[str]=mapped_column(String(500))
class CrashCase(Base):
    __tablename__='crash_cases'
    id: Mapped[int]=mapped_column(primary_key=True)
    log_set_id: Mapped[int]=mapped_column(ForeignKey('log_sets.id'))
    name: Mapped[str]=mapped_column(String(100),unique=True)
    crash_after: Mapped[int]=mapped_column(Integer)
class Recovery(Base):
    __tablename__='recoveries'
    id: Mapped[int]=mapped_column(primary_key=True)
    crash_case_id: Mapped[int]=mapped_column(ForeignKey('crash_cases.id'))
    label: Mapped[str]=mapped_column(String(120))
    status: Mapped[str]=mapped_column(String(20),default='queued')
    snapshot: Mapped[dict]=mapped_column(JSON)
    result: Mapped[dict | None]=mapped_column(JSON,nullable=True)
    created_at: Mapped[datetime]=mapped_column(DateTime,default=now)
class Replay(Base):
    """双路并发复演：同一冻结输入切成两个日志片段，由两条通道各自演算后合并发布。"""
    __tablename__='replays'
    id: Mapped[int]=mapped_column(primary_key=True)
    crash_case_id: Mapped[int]=mapped_column(ForeignKey('crash_cases.id'))
    label: Mapped[str]=mapped_column(String(120))
    status: Mapped[str]=mapped_column(String(20),default='queued')
    snapshot: Mapped[dict]=mapped_column(JSON)
    result: Mapped[dict | None]=mapped_column(JSON,nullable=True)
    attempts_total: Mapped[int]=mapped_column(Integer,default=0)
    published_at: Mapped[datetime | None]=mapped_column(DateTime,nullable=True)
    created_at: Mapped[datetime]=mapped_column(DateTime,default=now)
    shards: Mapped[list['ReplayShard']]=relationship(back_populates='replay',cascade='all, delete-orphan',order_by='ReplayShard.lane')
class ReplayShard(Base):
    """一条通道负责的片段；结果仅保留该路最新一份，整次复演最多两份待合并结果。"""
    __tablename__='replay_shards'
    __table_args__=(UniqueConstraint('replay_id','lane',name='uq_replay_lane'),)
    id: Mapped[int]=mapped_column(primary_key=True)
    replay_id: Mapped[int]=mapped_column(ForeignKey('replays.id',ondelete='CASCADE'))
    lane: Mapped[str]=mapped_column(String(1))
    # 崩溃点为 0 时没有可切片段，区间为空（NULL），该路分片直接就绪。
    lsn_from: Mapped[int | None]=mapped_column(Integer,nullable=True)
    lsn_to: Mapped[int | None]=mapped_column(Integer,nullable=True)
    status: Mapped[str]=mapped_column(String(20),default='pending')
    attempts: Mapped[int]=mapped_column(Integer,default=0)
    result: Mapped[dict | None]=mapped_column(JSON,nullable=True)
    last_error: Mapped[str | None]=mapped_column(String(500),nullable=True)
    updated_at: Mapped[datetime]=mapped_column(DateTime,default=now,onupdate=now)
    replay: Mapped[Replay]=relationship(back_populates='shards')
class Audit(Base):
    __tablename__='audits'
    id: Mapped[int]=mapped_column(primary_key=True)
    actor: Mapped[str]=mapped_column(String(120))
    action: Mapped[str]=mapped_column(String(120))
    created_at: Mapped[datetime]=mapped_column(DateTime,default=now)
