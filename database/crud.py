from sqlalchemy import desc, exists, select

from database.session import Session
from database.tables import AgentError, Snapshot


def add_snapshot(sha, status, modification: str):
    snapshot = Snapshot(sha=sha, status=status, modification=modification)
    with Session() as session:
        try:
            session.add(snapshot)
        except:
            session.rollback()
            raise
        else:
            session.commit()


def get_snapshot_by_status(status):
    with Session() as session:
        snapshot = (
            select(Snapshot).where(Snapshot.status == status).order_by(desc(Snapshot.snapshot_time))
        )
        first_snapshot = session.scalars(snapshot).first()
        if first_snapshot:
            return first_snapshot.id, first_snapshot.sha, first_snapshot.modification
        return None, None, None

def update_snapshot_status(snapshot_id, snapshot_status):
    with Session() as session:
        snapshot = session.get(Snapshot, snapshot_id)
        if snapshot:
            snapshot.status = snapshot_status
            session.commit()

def add_error(snapshot_id, error_text):
    with Session() as session:
        try:
            is_exist = session.scalar(select(exists().where(Snapshot.id == snapshot_id)))
            if not is_exist:
                raise ValueError(f"Snapshot with id={snapshot_id} not exist.")
            else:
                error = AgentError(snapshot_id=snapshot_id, error_text=error_text)
                session.add(error)
        except:
            session.rollback()
            raise
        else:
            session.commit()


def get_errors(snapshot_id):
    with Session() as session:
        errors = (
            select(AgentError)
            .where(AgentError.snapshot_id == snapshot_id)
            .order_by(desc(AgentError.error_time))
        )
