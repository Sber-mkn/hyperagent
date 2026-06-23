from datetime import datetime
from sqlalchemy import CheckConstraint
from sqlalchemy import String
from sqlalchemy import ForeignKey
from sqlalchemy import DateTime
from sqlalchemy import Text

from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.orm import relationship
from sqlalchemy.orm import Mapped
from sqlalchemy.orm import mapped_column
from sqlalchemy.sql.functions import current_timestamp

class Base(DeclarativeBase):
    pass

class Snapshot(Base):
    __tablename__ = "snapshots"
    id: Mapped[int] = mapped_column(primary_key=True)
    sha: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(20))
    snapshot_time: Mapped[datetime] = mapped_column(DateTime(timezone=False),
        server_default=current_timestamp())
    modification: Mapped[str] = mapped_column(Text)
    __table_args__ = (
        CheckConstraint("status = 'PENDING' or status = 'STABLE' or status = 'ERROR'",
                        name='check_status'),
    )

class AgentError(Base):
    __tablename__ = "errors"
    id: Mapped[int] = mapped_column(primary_key=True)
    snapshot_id: Mapped[int] = mapped_column(
        ForeignKey(
            'snapshots.id',
            ondelete='CASCADE',
            onupdate='CASCADE',
            name='fk_snapshot'
        )
    )
    error_text: Mapped[str] = mapped_column(Text)
    error_time: Mapped[datetime] = mapped_column(DateTime(timezone=False),
        server_default=current_timestamp())
    snapshot: Mapped["Snapshot"] = relationship()


