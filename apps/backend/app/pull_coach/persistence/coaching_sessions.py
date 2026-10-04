"""Persistence boundary for auditable, replayable coaching provider runs."""
from datetime import datetime, timezone
import hashlib
import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.pull_coach import CoachingSession, CoachingSessionMessage
from app.db.models.pull_coach import CoachingProfileRevision
from app.db.models.wipefest import WipefestFightSnapshot


def context_fingerprint(context: dict) -> str:
    """Stable SHA-256 for the exact normalized request context."""
    encoded = json.dumps(context, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


class CoachingSessionRepository:
    """Accepts a caller-owned transaction; never copies the source snapshot."""

    def __init__(self, session: Session):
        self.session = session

    def start(self, *, snapshot_id: int, encounter_id: str,
              audience: str, context_schema_version: str, request_context: dict,
              profile_revision_id: int,
              target_player_id: str | None = None, target_player_name: str | None = None,
              messages: tuple[dict, ...] = ()) -> CoachingSession:
        if audience not in {"raid", "player"}:
            raise ValueError("audience must be 'raid' or 'player'")
        if (audience == "player") != (target_player_id is not None):
            raise ValueError("player sessions require target_player_id; raid sessions must not have one")
        snapshot = self.session.get(WipefestFightSnapshot, snapshot_id)
        if snapshot is None:
            raise LookupError(f"Wipefest snapshot {snapshot_id} was not found")
        revision = self.session.get(CoachingProfileRevision, profile_revision_id)
        if revision is None:
            raise LookupError(f"Coaching profile revision {profile_revision_id} was not found")
        row = CoachingSession(snapshot_id=snapshot_id, report_code=snapshot.report_code, fight_id=snapshot.fight_id,
            encounter_id=encounter_id, audience=audience, target_player_id=target_player_id,
            target_player_name=target_player_name, context_schema_version=context_schema_version,
            context_fingerprint=context_fingerprint(request_context), request_context=request_context,
            profile_revision_id=profile_revision_id, provider=revision.provider, requested_model=revision.model_slug,
            status="pending")
        self.session.add(row)
        self.session.flush()
        for sequence, message in enumerate(messages):
            self.append_message(row, role=message["role"], content=message["content"],
                                metadata=message.get("metadata"), sequence=sequence)
        self.session.flush()
        return row

    def append_message(self, session: CoachingSession, *, role: str, content: str,
                       metadata: dict | None = None, sequence: int | None = None) -> CoachingSessionMessage:
        if role not in {"system", "user", "assistant"}:
            raise ValueError("role must be system, user, or assistant")
        if sequence is None:
            last_sequence = self.session.scalar(select(CoachingSessionMessage.sequence).where(
                CoachingSessionMessage.session_id == session.id).order_by(
                CoachingSessionMessage.sequence.desc()).limit(1))
            sequence = 0 if last_sequence is None else last_sequence + 1
        row = CoachingSessionMessage(session_id=session.id, sequence=sequence, role=role,
                                     content=content, message_metadata=metadata)
        self.session.add(row)
        self.session.flush()
        return row

    def complete(self, session: CoachingSession, *, structured_response: dict,
                 raw_response: dict | str, provider_request_id: str | None = None,
                 actual_model: str | None = None,
                 provider_response_id: str | None = None, usage: dict | None = None,
                 cost: dict | None = None, assistant_content: str | None = None) -> CoachingSession:
        if session.status != "pending":
            raise ValueError("only pending coaching sessions can be completed")
        session.status = "completed"
        session.completed_at = datetime.now(timezone.utc)
        session.structured_response = structured_response
        session.raw_response = raw_response
        session.provider_request_id = provider_request_id
        session.actual_model = actual_model
        session.provider_response_id = provider_response_id
        session.usage = usage
        session.cost = cost
        if assistant_content is not None:
            self.append_message(session, role="assistant", content=assistant_content)
        self.session.flush()
        return session

    def fail(self, session: CoachingSession, *, error: dict, raw_response: dict | str | None = None,
             status: str = "failed", provider_request_id: str | None = None,
             provider_response_id: str | None = None, actual_model: str | None = None,
             usage: dict | None = None, cost: dict | None = None) -> CoachingSession:
        if status not in {"failed", "invalid_output"}:
            raise ValueError("failure status must be failed or invalid_output")
        if session.status != "pending":
            raise ValueError("only pending coaching sessions can be failed")
        session.status = status
        session.completed_at = datetime.now(timezone.utc)
        session.error = error
        session.raw_response = raw_response
        session.provider_request_id = provider_request_id
        session.provider_response_id = provider_response_id
        session.actual_model = actual_model
        session.usage = usage
        session.cost = cost
        self.session.flush()
        return session
