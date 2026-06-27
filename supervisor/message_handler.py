import json

from supervisor.rollback import *
from database.crud import update_snapshot_status, get_errors
from database.crud import add_error
from database.crud import add_snapshot

def error_handler(message: json):
    error_text = message.get("error")
    snapshot = get_snapshot_by_status("PENDING")
    if snapshot:
        snapshot_id, snapshot_sha, snapshot_message = snapshot
        add_error(snapshot_id, error_text)
        update_snapshot_status(snapshot_id, "ERROR")
        rollback_agent()
        start_agent()

def commit_handler(message: json):
    commit_sha = message.get("commit_sha")
    commit_text = message.get("commit_text")
    add_snapshot(commit_sha, "PENDING",commit_text)

def ack_handler():
    snapshot = get_snapshot_by_status("PENDING")
    if snapshot:
        snapshot_id, _, _ = snapshot
        update_snapshot_status(snapshot_id, "STABLE")




