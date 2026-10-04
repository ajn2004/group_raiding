"""Live adapters for Wipefest coaching and the established WCL workflow."""
from __future__ import annotations

from typing import Any

from app.pull_coach.coaching.inference import (
    CoachingInferenceError, InvalidCoachingResponse, OpenRouterConfig, OpenRouterInferenceProvider,
    ProviderRequestError,
)
from app.pull_coach.orchestration import CoachingRunResult, CoachingSourceError
from app.pull_coach.persistence.coaching_profiles import (
    ActiveCoachingRevisionMissing, CoachingProfileNotFound, CoachingProfileRepository,
)
from app.pull_coach.persistence.coaching_sessions import CoachingSessionRepository
from app.pull_coach.wipefest_context import build_fight_coaching_context
from app.web_requests.warcraft_logs import parse_report_code
from app.web_requests.wipefest import WipefestProvider, WipefestSnapshotRepository, WipefestProviderError
from app.pull_coach.workflow import PullCoachWorkflow, source_report_url


class WipefestCoachingSource:
    def __init__(self, provider=None, session_factory=None, inference=None):
        self.provider = provider or WipefestProvider()
        if session_factory is None:
            from app.db.database import session_scope
            session_factory = session_scope
        self.session_factory = session_factory
        self.inference = inference

    def coach(self, report_reference: str, fight: dict[str, Any]) -> CoachingRunResult:
        code = parse_report_code(report_reference)
        fight_id, encounter_id = str(fight["id"]), str(fight["encounterID"])
        try:
            fetched = self.provider.fetch_fight(code, fight_id, encounter_id)
        except WipefestProviderError as exc:
            raise CoachingSourceError("Wipefest source failed") from exc

        try:
            with self.session_factory() as session:
                snapshots = WipefestSnapshotRepository(session)
                snapshot = snapshots.persist(fetched)
                context = build_fight_coaching_context(snapshot)
                profile = CoachingProfileRepository(session).active("raid_coach")
                revision = profile.active_revision
                sessions = CoachingSessionRepository(session)
                coaching_session = sessions.start(snapshot_id=snapshot.id, encounter_id=encounter_id,
                    context_schema_version=str(context["context_schema_version"]), request_context=context,
                    profile_revision_id=revision.id, audience="raid")
                try:
                    if self.inference is not None:
                        inference = self.inference
                    else:
                        try:
                            inference = OpenRouterInferenceProvider(OpenRouterConfig.from_env())
                        except ValueError as exc:
                            raise CoachingSourceError("OpenRouter configuration is invalid") from exc
                    result = inference.infer(context, revision)
                except InvalidCoachingResponse as exc:
                    sessions.fail(coaching_session, status="invalid_output", error={"message": str(exc)},
                        raw_response=exc.raw_response, provider_request_id=exc.provider_request_id,
                        provider_response_id=exc.provider_response_id, actual_model=exc.actual_model,
                        usage=exc.usage)
                    session.commit()
                    raise CoachingSourceError("coaching provider returned invalid output") from exc
                except ProviderRequestError as exc:
                    sessions.fail(coaching_session, error={"message": str(exc)})
                    session.commit()
                    raise CoachingSourceError("coaching inference failed") from exc
                except CoachingInferenceError as exc:
                    sessions.fail(coaching_session, error={"message": str(exc)})
                    session.commit()
                    raise CoachingSourceError("coaching inference configuration is invalid") from exc
                sessions.complete(coaching_session, structured_response=result.response,
                    raw_response=result.raw_response, provider_request_id=result.provider_request_id,
                    provider_response_id=result.provider_response_id, actual_model=result.actual_model,
                    usage=result.usage)
                session.commit()
                return CoachingRunResult(code, fight_id, encounter_id, fight.get("name", "Unknown encounter"),
                    source_report_url(report_reference, code, fight_id), result.response,
                    coaching_session.id, "wipefest")
        except (CoachingSourceError, CoachingProfileNotFound, ActiveCoachingRevisionMissing) as exc:
            if isinstance(exc, CoachingSourceError):
                raise
            raise CoachingSourceError("raid_coach profile is not configured") from exc


class LegacyWCLCoachingSource:
    def __init__(self, workflow: PullCoachWorkflow):
        self.workflow = workflow

    def coach(self, report_reference: str, fight: dict[str, Any]) -> CoachingRunResult:
        result = self.workflow.run(report_reference, str(fight["id"]))
        selected = result.selected_pull
        return CoachingRunResult(result.report_code, str(selected.fight_id),
            str(selected.encounter.encounter_id), selected.encounter.name, result.source_url,
            {}, None, "legacy", result)

    def coach_encounter_sample(self, report_reference: str, encounter_id: str) -> CoachingRunResult:
        result = self.workflow.run_encounter_sample(report_reference, encounter_id)
        selected = result.selected_pull
        return CoachingRunResult(result.report_code, str(selected.fight_id),
            str(selected.encounter.encounter_id), selected.encounter.name, result.source_url,
            {}, None, "legacy", result)


class LazyLegacyWCLCoachingSource:
    """Load verified mechanic configuration only if legacy coaching is selected."""
    def __init__(self, factory):
        self.factory = factory

    def coach(self, report_reference: str, fight: dict[str, Any]) -> CoachingRunResult:
        return LegacyWCLCoachingSource(self.factory()).coach(report_reference, fight)

    def coach_encounter_sample(self, report_reference: str, encounter_id: str) -> CoachingRunResult:
        return LegacyWCLCoachingSource(self.factory()).coach_encounter_sample(report_reference, encounter_id)
