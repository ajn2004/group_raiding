"""DAL-52 adapter for the canonical offline Discord payload."""
from .discord import PullCoachPresenter
from app.pull_coach.workflow import PullCoachReportResult, source_report_url


class DiscordPresentationReplayStage:
    name = "discord"

    def __init__(self, presenter=None):
        self.presenter = presenter or PullCoachPresenter()

    def run(self, context):
        outputs = context.current_stage_outputs
        analysis, progression, coaching = outputs["analysis"], outputs["progression"], outputs["coaching"]
        report = analysis.pull.report.report_code
        result = PullCoachReportResult(report,
            source_report_url(report, report, analysis.pull.fight_id),
            analysis.pull, context.current, analysis, progression, coaching)
        return self.presenter.present(result)
