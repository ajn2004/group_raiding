"""Synthetic provider-shaped DAL-60..65 onboarding through DAL-59 history."""
import asyncio
import json
import os
from types import SimpleNamespace

import pytest

for key, value in {
    "SQLALCHEMY_DATABASE_USER": "test", "SQLALCHEMY_DATABASE_PASSWORD": "test",
    "SQLALCHEMY_DATABASE_HOST": "localhost", "SQLALCHEMY_DATABASE_PORT": "5432",
    "SQLALCHEMY_DATABASE_DB": "test",
}.items():
    os.environ[key] = value
import app.config as app_config
app_config.USERNAME, app_config.PASSWORD = "test", "test"
app_config.DB_SERVER, app_config.DB_NAME = "localhost:5432", "test"

from app.discord_bot.commands.pull_coach import (
    HistoricalEncounterPicker, HistoricalEncounterSelection, PullCoach,
)
from app.pull_coach.coaching import CoachingSynthesizer
from app.pull_coach.history import EncounterCatalogDiscovery, EncounterDiscoveryService
from app.pull_coach.mechanics.draft import MechanicDraftService, candidate_id_for, draft_to_json
from app.pull_coach.mechanics.store import DirectoryMechanicsStore, configured_mechanics_registry
from app.pull_coach.mechanics.verification import MechanicVerificationService, VerifiedMechanicInput
from app.pull_coach.analysis import PullAnalyzer
from app.pull_coach.progression import ProgressionComparator
from app.pull_coach.workflow import PullCoachWorkflow, UnsupportedEncounter
from app.pull_coach.models import EncounterIdentity, ProgressionStatus, discovery_to_json
from app.discord_bot.commands.pull_coach import PullCoachDetailsView
from app.web_requests.warcraft_logs import WCLClient


SYNTHETIC_ENCOUNTER = "990066"
REPORT_CODE = "SYNTHETIC_REPORT_66"


def synthetic_report():
    # Provider-shaped, entirely synthetic report.  Three chronological wipes show
    # repeated Lingering Gaze, improvement, then a regression; Eye Sore is factual
    # context but is intentionally not promoted into analyzer semantics.
    fights, events = [], {}
    shapes = ((3, 1), (1, 0), (2, 1))
    for number, (gaze_hits, eye_hits) in enumerate(shapes, 1):
        start = number * 100_000
        fights.append({"id": number, "encounterID": int(SYNTHETIC_ENCOUNTER), "name": "Synthetic Gaze Trial",
                       "difficulty": 5, "kill": False, "startTime": start, "endTime": start + 30_000,
                       "inProgress": False, "bossPercentage": 70 - number * 10, "fightPercentage": 70,
                       "friendlyPlayers": [1]})
        page = []
        for hit in range(gaze_hits):
            page.append({"timestamp": start + 1000 + hit * 3000, "type": "damage", "sourceID": 90,
                         "targetID": 1, "abilityGameID": 140495, "amount": 1200,
                         "ability": {"guid": 140495, "name": "Lingering Gaze"},
                         "privateProviderNote": "SECRET_REPORT_CODE"})
        for hit in range(eye_hits):
            page.append({"timestamp": start + 15_000 + hit * 1000, "type": "damage", "sourceID": 91,
                         "targetID": 2, "abilityGameID": 134755, "amount": 800,
                         "ability": {"guid": 134755, "name": "Eye Sore"}})
        events[number] = page
    fights.append({"id": 4, "encounterID": 990067, "name": "Unrelated Synthetic Boss",
                   "difficulty": 5, "kill": False, "startTime": 450_000, "endTime": 480_000,
                   "inProgress": False, "bossPercentage": 90, "fightPercentage": 90,
                   "friendlyPlayers": [1]})
    events[4] = []
    report = {"code": REPORT_CODE, "revision": 1, "startTime": 1, "endTime": 500_000,
              "fights": fights,
              "masterData": {"actors": [
                  {"id": 1, "gameID": 1001, "type": "Player", "name": "Private Player", "subType": "Warrior"},
                  {"id": 2, "gameID": 1002, "type": "Player", "name": "Synthetic Ally", "subType": "Mage"},
                  {"id": 90, "gameID": 9000, "type": "NPC", "name": "Synthetic Gaze", "subType": ""},
                  {"id": 91, "gameID": 9001, "type": "NPC", "name": "Synthetic Eye", "subType": ""}],
                  "abilities": [{"gameID": 140495, "name": "Lingering Gaze"},
                                {"gameID": 134755, "name": "Eye Sore"}]}}
    return report, events


class FakeWCLTransport:
    def __init__(self):
        self.report, self.event_pages = synthetic_report()
        self.report_queries = 0
        self.event_fights = []

    def graphql(self, query, variables):
        if "events(" not in query:
            self.report_queries += 1
            return {"data": {"reportData": {"report": self.report}}}
        fight_id = variables["fightIDs"][0]
        self.event_fights.append(str(fight_id))
        return {"data": {"reportData": {"report": {"events": {
            "data": self.event_pages[fight_id], "nextPageTimestamp": None}}}}}


class Interaction:
    def __init__(self, user_id=7, fight="1"):
        self.user = SimpleNamespace(id=user_id)
        self.data = {"values": [fight]}
        self.response = self
        self.followup = _Followup(self)
        self.sent, self.channel_messages = [], []
        self.channel = self

    async def edit_message(self, **kwargs):
        self.sent.append(("edit", kwargs))

    async def send(self, message=None, **kwargs):
        self.channel_messages.append((message, kwargs))
        return SimpleNamespace()

    async def send_message(self, message, **kwargs):
        self.sent.append((message, kwargs))


class _Followup:
    def __init__(self, interaction):
        self.interaction = interaction

    async def send(self, message=None, **kwargs):
        self.interaction.sent.append((message, kwargs))
        return SimpleNamespace()


def _seed_old_verified(store):
    store.write_verified("880001", {"schema_version": 1, "registry_version": "legacy-1", "definitions": [{
        "definition_version": "1", "encounter": {"encounter_id": "880001", "name": "Existing Synthetic Boss"},
        "mechanic_id": "old-rule", "name": "Existing rule", "event_types": ["damage"],
        "failure_category": "avoidable_damage", "severity": "medium", "avoidable": True,
        "expected_roles": [], "weight": 1, "ability_ids": [777001],
    }]})


def test_unknown_encounter_discovery_review_promotion_and_historical_coaching(tmp_path, monkeypatch):
    root = tmp_path / "mechanics"
    store = DirectoryMechanicsStore(root)
    root.mkdir()
    _seed_old_verified(store)
    transport = FakeWCLTransport()
    client = WCLClient(transport=transport)
    assert "SECRET_REPORT_CODE" in json.dumps(transport.report) + json.dumps(transport.event_pages)
    monkeypatch.setenv("PULL_COACH_MECHANICS_ROOT", str(root))
    monkeypatch.delenv("PULL_COACH_MECHANICS_FILE", raising=False)
    monkeypatch.setenv("PULL_COACH_SOURCE", "legacy")

    # Normal catalog factory semantics see only verified lane; discovery itself
    # and a draft do not make the encounter selectable as supported.
    catalog_factory = lambda: EncounterCatalogDiscovery(client, configured_mechanics_registry())
    catalog = catalog_factory().discover(f"https://www.warcraftlogs.com/reports/{REPORT_CODE}")
    summary = next(item for item in catalog.encounters if item.encounter_id == SYNTHETIC_ENCOUNTER)
    assert summary.mechanics_supported is False
    workflow = PullCoachWorkflow(client, PullAnalyzer(configured_mechanics_registry()),
                                  ProgressionComparator(), CoachingSynthesizer())
    try:
        workflow.run_encounter_sample(catalog.source_url, SYNTHETIC_ENCOUNTER)
        assert False, "unverified encounter must be rejected"
    except UnsupportedEncounter:
        pass

    # Drive DAL-65 picker and unsupported handler, with actual discovery/store.
    def workflow_factory():
        return PullCoachWorkflow(client, PullAnalyzer(configured_mechanics_registry()),
                                 ProgressionComparator(), CoachingSynthesizer())

    cog = PullCoach(None, workflow_factory=workflow_factory, catalog_factory=catalog_factory,
                    mechanics_store_factory=lambda: store,
                    discovery_factory=lambda writer: EncounterDiscoveryService(client, writer))
    async def make_picker():
        return HistoricalEncounterPicker(catalog, 7, lambda *_: (_ for _ in ()).throw(AssertionError("analyzer called")),
                                         cog._handle_unsupported_selection)
    picker = asyncio.run(make_picker())
    outsider = Interaction(user_id=8, fight=SYNTHETIC_ENCOUNTER)
    assert asyncio.run(picker.interaction_check(outsider)) is False
    assert outsider.sent[-1][1]["ephemeral"] is True
    interaction = Interaction(fight=SYNTHETIC_ENCOUNTER)
    interaction.data["values"] = [SYNTHETIC_ENCOUNTER]
    order = []
    original_edit = interaction.edit_message
    async def ack(**kwargs):
        order.append(("ack", picker.completed, all(x.disabled for x in picker.children)))
        await original_edit(**kwargs)
    interaction.edit_message = ack
    original_to_thread = asyncio.to_thread
    async def tracked_to_thread(fn, *args):
        order.append(("work",))
        return await original_to_thread(fn, *args)
    monkeypatch.setattr("app.discord_bot.commands.pull_coach.asyncio.to_thread", tracked_to_thread)
    asyncio.run(picker._select(interaction))
    assert order[0] == ("ack", True, True) and order[1][0] == "work"
    assert transport.event_fights == ["1", "2", "3"]
    response = interaction.sent[-1]
    assert response[1]["ephemeral"] is True and "hasn't verified" in response[0]
    assert "review" in response[0] and not interaction.channel_messages
    assert "Private Player" not in response[0] and "SECRET_REPORT_CODE" not in response[0]

    discovery = store.read_discovery(SYNTHETIC_ENCOUNTER)
    serialized_discovery = discovery_to_json(discovery)
    assert discovery.stage == "discovered" and discovery.schema_version == 1
    by_id = {str(candidate.ability_id): candidate for candidate in discovery.candidates}
    assert {"140495", "134755"}.issubset(by_id)
    assert dict(by_id["140495"].fight_occurrence_counts) == {"1": 3, "2": 1, "3": 2}
    assert dict(by_id["134755"].fight_occurrence_counts) == {"1": 1, "3": 1}
    assert len(discovery.provenance) == 3 and all(len(p.source_fingerprint) == 64 for p in discovery.provenance)
    assert all(secret not in serialized_discovery for secret in ("Private Player", "SECRET_REPORT_", '"actor_id"', '"failure_category"'))
    assert not any(x in serialized_discovery for x in ("avoidability", "severity", "role_responsibility", "exposure"))

    # Freshness reuse: unchanged report + completed fight set avoids event-page refetch.
    before_events = list(transport.event_fights)
    discovered_bytes = (root / "discovered" / f"{SYNTHETIC_ENCOUNTER}.json").read_bytes()
    asyncio.run(cog._handle_unsupported_selection(HistoricalEncounterSelection(REPORT_CODE, catalog.source_url,
               SYNTHETIC_ENCOUNTER), summary, Interaction(fight=SYNTHETIC_ENCOUNTER)))
    assert list(transport.event_fights) == before_events
    assert store.read_discovery(SYNTHETIC_ENCOUNTER) == discovery
    assert (root / "discovered" / f"{SYNTHETIC_ENCOUNTER}.json").read_bytes() == discovered_bytes

    # Draft outage is non-blocking; stable factual scaffold is not production input.
    class BrokenProposal:
        def propose(self, candidate):
            raise RuntimeError("provider outage")
    draft_service = MechanicDraftService(store)
    draft = draft_service.generate_and_write(SYNTHETIC_ENCOUNTER, BrokenProposal())
    draft_json = json.dumps(store.read_draft(SYNTHETIC_ENCOUNTER), sort_keys=True)
    repeated = draft_service.generate_and_write(SYNTHETIC_ENCOUNTER, BrokenProposal())
    assert draft_to_json(draft) == draft_to_json(repeated)
    gaze = next(item for item in draft.candidates if str(item.ability_id) == "140495")
    assert gaze.candidate_id == candidate_id_for(SYNTHETIC_ENCOUNTER, 140495)
    assert gaze.proposal is None
    assert all(item["semantics"]["failure_category"] is None and item["semantics"]["avoidable"] is None
               for item in store.read_draft(SYNTHETIC_ENCOUNTER)["candidates"])
    assert '"Private Player"' not in draft_json and "SECRET_REPORT_CODE" not in draft_json
    assert "name:" not in draft_json and not store.load_verified_registry().for_encounter(
        EncounterIdentity(SYNTHETIC_ENCOUNTER, "Synthetic Gaze Trial"))
    assert not summary.mechanics_supported

    verification = MechanicVerificationService(store)
    candidate_id = gaze.candidate_id
    verified_before = {path.name: path.read_bytes() for path in (root / "verified").glob("*.json")}
    with pytest.raises(ValueError):
        verification.promote(SYNTHETIC_ENCOUNTER, candidate_id,
            VerifiedMechanicInput("", "", "avoidable_damage", "high", "true", (), "observed_ability", "reviewer"))
    assert {path.name: path.read_bytes() for path in (root / "verified").glob("*.json")} == verified_before
    assert not store.load_verified_registry().for_encounter(
        EncounterIdentity(SYNTHETIC_ENCOUNTER, "Synthetic Gaze Trial"))

    # Human-supplied semantics are explicit and independent of any proposal.
    verification.promote(SYNTHETIC_ENCOUNTER, candidate_id, VerifiedMechanicInput(
        mechanic_id="lingering-gaze", name="Lingering Gaze", failure_category="avoidable_damage",
        severity="high", avoidability="true", expected_roles=(), selector_interpretation="observed_ability",
        reviewer="e2e-test-reviewer"))
    verified_text = (root / "verified" / f"{SYNTHETIC_ENCOUNTER}.json").read_text()
    assert "e2e-test-reviewer" in verified_text and "source_discovery_sha256" in verified_text
    assert all(secret not in verified_text for secret in ("Private Player", "SECRET_REPORT_CODE", '"actor_id"'))
    assert store.read_discovery(SYNTHETIC_ENCOUNTER) == discovery and store.read_draft(SYNTHETIC_ENCOUNTER)
    assert store.load_verified_registry().for_encounter(
        EncounterIdentity("880001", "Existing Synthetic Boss"))

    # Same Cog, normal catalog/workflow factories: only a verified file changes
    # support on the next browser invocation; no process restart/config edit.
    supported_catalog = cog.catalog_factory().discover(catalog.source_url)
    supported_summary = next(item for item in supported_catalog.encounters if item.encounter_id == SYNTHETIC_ENCOUNTER)
    assert supported_summary.mechanics_supported is True
    assert cog.catalog_factory().discover(catalog.source_url) == supported_catalog
    assert cog.workflow_factory is workflow_factory
    output = Interaction(fight=SYNTHETIC_ENCOUNTER)
    async def make_supported_picker():
        return HistoricalEncounterPicker(supported_catalog, 7, cog._handle_historical_selection)
    supported_picker = asyncio.run(make_supported_picker())
    asyncio.run(supported_picker._select(output))
    public = next((kwargs for message, kwargs in output.channel_messages if message is None and "embed" in kwargs), None)
    # The picker sends the normal DAL-59 embed publicly through channel.send.
    assert public is not None
    embed = public["embed"]
    assert embed.title.startswith("Historical Pull Coach")
    assert isinstance(public["view"], PullCoachDetailsView)
    details = public["view"].details
    assert details and "Lingering Gaze" in details and "evidence" in details.lower()
    assert "SECRET_REPORT_CODE" not in details and "Private Player" not in details
    assert "Eye Sore" not in details and "proposal" not in details.lower()
    assert transport.event_fights[-3:] == ["1", "2", "3"]
    # Only verified 140495 has analyzer meaning; proposal/draft never entered it.
    first_result = PullCoachWorkflow(client, PullAnalyzer(configured_mechanics_registry()),
                                     ProgressionComparator(), CoachingSynthesizer()).run_encounter_sample(
                                         catalog.source_url, SYNTHETIC_ENCOUNTER)
    second = PullCoachWorkflow(client, PullAnalyzer(configured_mechanics_registry()),
                               ProgressionComparator(), CoachingSynthesizer()).run_encounter_sample(
                                   catalog.source_url, SYNTHETIC_ENCOUNTER)
    assert first_result.progression.compared_pull_numbers == (1, 2, 3)
    gaze_progression = next(item for item in first_result.progression.subjects
                            if item.subject_id == "mechanic:lingering-gaze")
    assert gaze_progression.status == ProgressionStatus.REGRESSED and gaze_progression.evidence_ids
    assert first_result.analysis.findings and first_result.analysis.findings == second.analysis.findings
    assert first_result.progression == second.progression
    assert first_result.coaching == second.coaching
    assert all(observation.mechanic_id == "lingering-gaze"
               for observation in first_result.analysis.mechanic_observations)
    assert store.load_verified_registry().for_encounter(
        EncounterIdentity(SYNTHETIC_ENCOUNTER, "Synthetic Gaze Trial"))


def test_legacy_single_file_mechanics_configuration_is_preserved(tmp_path, monkeypatch):
    legacy = tmp_path / "legacy.json"
    legacy.write_text(json.dumps({"schema_version": 1, "registry_version": "legacy", "definitions": [{
        "definition_version": "1", "encounter": {"encounter_id": "880002", "name": "Legacy"},
        "mechanic_id": "legacy-rule", "name": "Legacy rule", "event_types": ["damage"],
        "failure_category": "avoidable_damage", "severity": "medium", "avoidable": True,
        "expected_roles": [], "ability_ids": [777002],
    }]}))
    monkeypatch.setenv("PULL_COACH_MECHANICS_ROOT", "")
    monkeypatch.setenv("PULL_COACH_MECHANICS_FILE", str(legacy))
    registry = configured_mechanics_registry()
    from app.pull_coach.models import EncounterIdentity
    assert registry.for_encounter(EncounterIdentity("880002", "Legacy"))
