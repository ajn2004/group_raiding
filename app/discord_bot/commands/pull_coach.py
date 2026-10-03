"""py-cord slash-command adapter for the provider-independent Pull Coach workflow."""
import asyncio
import logging
import os

import discord
from discord.ext import commands

from app.pull_coach.analysis import PullAnalyzer
from app.pull_coach.coaching import CoachingSynthesizer
from app.pull_coach.mechanics.loader import MechanicSchemaError, load_mechanic_registry
from app.pull_coach.presentation import PullCoachPresenter, to_discord_embed
from app.pull_coach.progression import ProgressionComparator
from app.pull_coach.workflow import (
    FightNotCompleted, FightNotFound, InvalidFightSelector, NoCompletedPulls,
    PullCoachConfigurationError, PullCoachWorkflow, PullCoachWorkflowError,
    UnsupportedEncounter,
)
from app.web_requests.warcraft_logs import WCLClient
from app.web_requests.warcraft_logs.errors import (
    AuthenticationError, InvalidReportReference, MalformedResponse, PaginationError,
    RateLimitError, ReportUnavailable, TransportError,
)

log = logging.getLogger(__name__)


def _configured_workflow():
    path = os.getenv("PULL_COACH_MECHANICS_FILE")
    if not path:
        raise PullCoachConfigurationError("mechanic definitions are not configured")
    try:
        analyzer = PullAnalyzer(load_mechanic_registry(path))
    except (MechanicSchemaError, OSError) as exc:
        raise PullCoachConfigurationError("configured mechanic definitions could not be loaded") from exc
    return PullCoachWorkflow(WCLClient(), analyzer, ProgressionComparator(), CoachingSynthesizer())


def _friendly_error(exc):
    if isinstance(exc, InvalidReportReference):
        return "That doesn't look like a supported Warcraft Logs report URL or code."
    if isinstance(exc, ReportUnavailable):
        return "I couldn't access that report. It may be private, unavailable, or not visible to the configured Warcraft Logs credentials."
    if isinstance(exc, RateLimitError):
        return "Warcraft Logs is rate-limiting requests right now. Try again shortly."
    if isinstance(exc, AuthenticationError):
        return "Pull Coach's Warcraft Logs connection is not configured correctly."
    if isinstance(exc, (TransportError, MalformedResponse, PaginationError)):
        return "Warcraft Logs returned an error while I was loading that pull."
    if isinstance(exc, (PullCoachConfigurationError, UnsupportedEncounter)):
        return "Pull Coach doesn't have mechanic definitions for that encounter yet."
    if isinstance(exc, NoCompletedPulls):
        return "That report has no completed boss pulls to analyze."
    if isinstance(exc, FightNotFound):
        return "I couldn't find that fight ID in the report."
    if isinstance(exc, FightNotCompleted):
        return "That fight is still in progress; Pull Coach only analyzes completed pulls."
    if isinstance(exc, InvalidFightSelector):
        return "Fight must be `latest` or a Warcraft Logs fight ID."
    if isinstance(exc, PullCoachWorkflowError):
        return "I couldn't select that pull. Check the fight ID and try again."
    return "I loaded the pull, but Pull Coach couldn't analyze it."


class PullCoachDetailsView(discord.ui.View):
    def __init__(self, details):
        super().__init__(timeout=300)
        self.details = details

    @discord.ui.button(label="Details", style=discord.ButtonStyle.secondary)
    async def show_details(self, button, interaction):
        await interaction.response.send_message(self.details or "No additional findings.", ephemeral=True)


class PullCoach(commands.Cog):
    def __init__(self, bot, workflow_factory=None, presenter=None):
        self.bot = bot
        self.workflow_factory = workflow_factory or _configured_workflow
        self.presenter = presenter or PullCoachPresenter()

    @discord.slash_command(name="pullcoach", description="Analyze a Warcraft Logs boss pull")
    async def pullcoach(self, ctx: discord.ApplicationContext,
                        report: discord.Option(str, "Warcraft Logs report URL or code"),
                        fight: discord.Option(str, "latest or Warcraft Logs fight ID", default="latest")):
        await ctx.defer()
        code = "unknown"
        try:
            # Log report and requested selector without exception text, which may contain sensitive data.
            from app.web_requests.warcraft_logs import parse_report_code
            code = parse_report_code(report)
            workflow = self.workflow_factory()
            result = await asyncio.to_thread(workflow.run, report, fight)
            payload = self.presenter.present(result)
            await ctx.followup.send(embed=to_discord_embed(payload),
                                    view=PullCoachDetailsView(payload.details))
        except Exception as exc:
            log.error("Pull Coach command failed report=%s fight=%s stage=command error_type=%s",
                      code, fight, type(exc).__name__)
            await ctx.followup.send(_friendly_error(exc))


def setup(bot):
    bot.add_cog(PullCoach(bot))
