"""py-cord slash-command adapter for the provider-independent Pull Coach workflow."""
import asyncio
from dataclasses import dataclass
import inspect
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
from app.pull_coach.history import EncounterCatalogDiscovery, HistoricalEncounterCatalog, NoCatalogEncounters
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


def _configured_catalog_discovery():
    path = os.getenv("PULL_COACH_MECHANICS_FILE")
    if not path:
        raise PullCoachConfigurationError("mechanic definitions are not configured")
    try:
        registry = load_mechanic_registry(path)
    except (MechanicSchemaError, OSError) as exc:
        raise PullCoachConfigurationError("configured mechanic definitions could not be loaded") from exc
    return EncounterCatalogDiscovery(WCLClient(), registry)


@dataclass(frozen=True)
class HistoricalEncounterSelection:
    """Minimal stable handoff from the browser to historical analysis."""

    report_code: str
    source_url: str
    encounter_id: str


def _friendly_error(exc):
    if isinstance(exc, NoCatalogEncounters):
        return "That report has no completed boss pulls to browse."
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


class HistoricalEncounterPicker(discord.ui.View):
    PAGE_SIZE = 25

    def __init__(self, catalog: HistoricalEncounterCatalog, owner_id: int, on_selection):
        super().__init__(timeout=300)
        self.catalog = catalog
        self.owner_id = owner_id
        self.on_selection = on_selection
        self.page = 0
        self.completed = False
        self.expired = False
        self.message = None
        self._render()

    async def interaction_check(self, interaction):
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("This encounter browser belongs to another user.", ephemeral=True)
            return False
        if self.completed or self.expired:
            await interaction.response.send_message("This encounter browser has expired.", ephemeral=True)
            return False
        return True

    def _render(self):
        self.clear_items()
        start = self.page * self.PAGE_SIZE
        encounters = self.catalog.encounters[start:start + self.PAGE_SIZE]
        options = []
        for encounter in encounters:
            status = "supported" if encounter.mechanics_supported else "unsupported"
            result = "kill" if encounter.has_kill else "no kill"
            label = encounter.name[:100] or encounter.encounter_id
            description = f"{encounter.pull_count} pulls · {result} · {status}"[:100]
            options.append(discord.SelectOption(label=label, value=encounter.encounter_id, description=description))
        selector = discord.ui.Select(placeholder=f"Choose an encounter · page {self.page + 1}/{self.page_count}",
                                     options=options, min_values=1, max_values=1)
        selector.callback = self._select
        self.add_item(selector)
        previous = discord.ui.Button(label="Previous", style=discord.ButtonStyle.secondary,
                                     disabled=self.page == 0)
        previous.callback = self._previous
        following = discord.ui.Button(label="Next", style=discord.ButtonStyle.secondary,
                                      disabled=self.page >= self.page_count - 1)
        following.callback = self._next
        self.add_item(previous)
        self.add_item(following)

    @property
    def page_count(self):
        return max(1, (len(self.catalog.encounters) + self.PAGE_SIZE - 1) // self.PAGE_SIZE)

    async def _move(self, interaction, delta):
        if self.completed or self.expired:
            return
        self.page = max(0, min(self.page_count - 1, self.page + delta))
        self._render()
        try:
            await interaction.response.edit_message(view=self)
        except (discord.HTTPException, discord.NotFound):
            return

    async def _previous(self, interaction):
        await self._move(interaction, -1)

    async def _next(self, interaction):
        await self._move(interaction, 1)

    async def _select(self, interaction):
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("This encounter browser belongs to another user.", ephemeral=True)
            return
        if self.completed or self.expired:
            await interaction.response.send_message("This encounter browser has expired.", ephemeral=True)
            return
        encounter_id = interaction.data["values"][0]
        summary = next((item for item in self.catalog.encounters if item.encounter_id == encounter_id), None)
        if summary is None:
            await interaction.response.send_message("That encounter is no longer available.", ephemeral=True)
            return
        if not summary.mechanics_supported:
            await interaction.response.send_message(_friendly_error(UnsupportedEncounter()), ephemeral=True)
            return
        self.completed = True
        self.stop()
        self._disable_items()
        # Acknowledge and disable the picker before the downstream handler can do slow work.
        try:
            await interaction.response.edit_message(view=self)
        except (discord.HTTPException, discord.NotFound):
            return
        selection = HistoricalEncounterSelection(self.catalog.report_code, self.catalog.source_url, encounter_id)
        try:
            result = self.on_selection(selection, interaction)
            if inspect.isawaitable(result):
                result = await result
        except Exception:
            # The handoff implementation owns downstream error reporting; never expose its details.
            await interaction.followup.send("I couldn't start Pull Coach for that encounter.", ephemeral=True)
            return
        if result is False:
            return
        await interaction.followup.send(f"Selected {summary.name} ({summary.pull_count} completed pulls).", ephemeral=True)

    def _disable_items(self):
        for item in self.children:
            item.disabled = True

    async def _edit_picker(self, interaction=None, *, content=None):
        try:
            if self.message is not None:
                await self.message.edit(content=content, view=self)
            elif interaction is not None:
                await interaction.edit_original_response(content=content, view=self)
        except (discord.HTTPException, discord.NotFound):
            pass

    async def on_timeout(self):
        self.expired = True
        self._disable_items()
        await self._edit_picker(content="Encounter browser expired.")


class PullCoach(commands.Cog):
    def __init__(self, bot, workflow_factory=None, presenter=None, catalog_factory=None, selection_handler=None):
        self.bot = bot
        self.workflow_factory = workflow_factory or _configured_workflow
        self.presenter = presenter or PullCoachPresenter()
        self.catalog_factory = catalog_factory or _configured_catalog_discovery
        self.selection_handler = selection_handler or self._handle_historical_selection

    async def _handle_historical_selection(self, selection, interaction):
        code = selection.report_code
        try:
            workflow = self.workflow_factory()
            reference = selection.source_url or selection.report_code
            result = await asyncio.to_thread(workflow.run_encounter_sample, reference, selection.encounter_id)
            payload = self.presenter.present(result)
            channel = getattr(interaction, "channel", None)
            if channel is None:
                raise RuntimeError("selection channel unavailable")
            await channel.send(embed=to_discord_embed(payload), view=PullCoachDetailsView(payload.details))
            return True
        except Exception as exc:
            log.error("Pull Coach historical failed report=%s encounter=%s stage=sample error_type=%s",
                      code, selection.encounter_id, type(exc).__name__)
            await interaction.followup.send(_friendly_error(exc), ephemeral=True)
            return False

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

    @discord.slash_command(name="pullcoach-history", description="Browse encounters in a Warcraft Logs report")
    async def pullcoach_history(self, ctx: discord.ApplicationContext,
                                report: discord.Option(str, "Warcraft Logs report URL or code")):
        await ctx.defer(ephemeral=True)
        code = "unknown"
        try:
            from app.web_requests.warcraft_logs import parse_report_code
            code = parse_report_code(report)
            discovery = self.catalog_factory()
            catalog = await asyncio.to_thread(discovery.discover, report)
            view = HistoricalEncounterPicker(catalog, ctx.author.id, self.selection_handler)
            message = await ctx.followup.send("Choose a boss encounter:", view=view, wait=True)
            view.message = message
        except Exception as exc:
            log.error("Pull Coach history failed report=%s stage=catalog error_type=%s", code, type(exc).__name__)
            await ctx.followup.send(_friendly_error(exc))


def setup(bot):
    bot.add_cog(PullCoach(bot))
