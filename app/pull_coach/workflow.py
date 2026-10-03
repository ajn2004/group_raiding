"""Live report workflow, independent of Discord and presentation."""
from dataclasses import dataclass
from urllib.parse import urlparse

from app.web_requests.warcraft_logs import WCLClient, parse_report_code
from app.pull_coach.analysis import PullAnalyzer
from app.pull_coach.progression import ProgressionComparator
from app.pull_coach.coaching import CoachingSynthesizer


class PullCoachWorkflowError(Exception):
    """Expected, user-displayable workflow failure."""


class NoCompletedPulls(PullCoachWorkflowError): pass
class InvalidFightSelector(PullCoachWorkflowError): pass
class FightNotFound(PullCoachWorkflowError): pass
class FightNotCompleted(PullCoachWorkflowError): pass
class UnsupportedEncounter(PullCoachWorkflowError): pass
class PullCoachConfigurationError(PullCoachWorkflowError): pass


@dataclass(frozen=True)
class PullCoachReportResult:
    report_code: str
    source_url: str
    selected_pull: object
    target_ingestion: object
    analysis: object
    progression: object
    coaching: object


DEFAULT_WCL_HOST = "classic.warcraftlogs.com"
SUPPORTED_WCL_HOSTS = {"warcraftlogs.com", "www.warcraftlogs.com", "classic.warcraftlogs.com",
                       "vanilla.warcraftlogs.com", "sod.warcraftlogs.com"}


def source_report_url(reference: str, report_code: str, fight_id: str) -> str:
    """Build the canonical credential-free WCL link shared by live and replay."""
    parsed = urlparse(reference) if isinstance(reference, str) else None
    host = parsed.hostname if parsed and parsed.hostname in SUPPORTED_WCL_HOSTS else DEFAULT_WCL_HOST
    return f"https://{host}/reports/{report_code}?fight={fight_id}"


class PullCoachWorkflow:
    def __init__(self, wcl_client: WCLClient, analyzer: PullAnalyzer,
                 progression_comparator: ProgressionComparator,
                 coaching_synthesizer: CoachingSynthesizer):
        self.wcl_client = wcl_client
        self.analyzer = analyzer
        self.progression_comparator = progression_comparator
        self.coaching_synthesizer = coaching_synthesizer

    def run(self, report_reference: str, fight_selector: str = "latest") -> PullCoachReportResult:
        code = parse_report_code(report_reference)
        report = self.wcl_client.report_data(code)
        fights = report.get("fights", [])
        selector = str(fight_selector).strip().lower()
        if selector == "latest":
            eligible = [f for f in fights if _is_boss(f) and not f.get("inProgress") and f.get("endTime") is not None]
            if not eligible:
                raise NoCompletedPulls("report has no completed boss encounter fights")
            target = max(eligible, key=lambda f: (f["startTime"], int(f["id"])))
        else:
            if not selector.isdigit():
                raise InvalidFightSelector("fight must be 'latest' or a Warcraft Logs fight ID")
            target = next((f for f in fights if str(f.get("id")) == selector), None)
            if target is None:
                raise FightNotFound(f"fight {selector} was not found")
            if not _is_boss(target):
                raise UnsupportedEncounter(f"fight {selector} is not a boss encounter")
            if target.get("inProgress") or target.get("endTime") is None:
                raise FightNotCompleted(f"fight {selector} is still in progress")

        encounter_id = str(target["encounterID"])
        prefix = sorted((f for f in fights if str(f.get("encounterID")) == encounter_id
                         and _is_boss(f) and not f.get("inProgress") and f.get("endTime") is not None
                         and f["startTime"] <= target["startTime"]),
                        key=lambda f: (f["startTime"], int(f["id"])))
        registry = getattr(self.analyzer, "registry", None)
        definitions = registry.for_encounter(_encounter(target)) if registry is not None else ()
        if not definitions:
            raise UnsupportedEncounter("no configured mechanic definitions")
        analyses, target_ingestion = [], None
        for fight in prefix:
            ingestion = self.wcl_client.ingest_fight(None, code, fight["id"])
            analysis = self.analyzer.analyze(ingestion.pull, ingestion.actors, ingestion.events)
            analyses.append(analysis)
            if str(fight["id"]) == str(target["id"]):
                target_ingestion = ingestion
        if target_ingestion is None:
            raise FightNotFound(f"fight {target['id']} was not found in the selected prefix")
        progression = self.progression_comparator.compare(analyses)
        labels = {item.mechanic_id: item.name for item in definitions}
        coaching = self.coaching_synthesizer.synthesize(analyses[-1], progression,
                                                        tuple(analyses[:-1]), labels)
        selected = target_ingestion.pull
        return PullCoachReportResult(code, source_report_url(report_reference, code, selected.fight_id),
                                     selected, target_ingestion, analyses[-1], progression, coaching)


def _is_boss(fight):
    value = fight.get("encounterID")
    try:
        return value is not None and int(value) > 0
    except (TypeError, ValueError):
        return False


def _encounter(fight):
    from app.pull_coach.models import EncounterIdentity
    return EncounterIdentity(str(fight["encounterID"]), fight.get("name") or "Unknown encounter")
