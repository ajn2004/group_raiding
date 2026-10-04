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
from app.pull_coach.mechanics.store import (
    DirectoryMechanicsStore,
    MechanicsStoreError,
    configured_mechanics_registry,
)
from app.pull_coach.presentation import PullCoachPresenter, to_discord_embed
from app.pull_coach.progression import ProgressionComparator
from app.pull_coach.workflow import (
    FightNotCompleted, FightNotFound, InvalidFightSelector, NoCompletedPulls,
    PullCoachConfigurationError, PullCoachWorkflow, PullCoachWorkflowError,
    UnsupportedEncounter,
)
from app.pull_coach.orchestration import CoachingOrchestrator, CoachingSourceError, SourceMode
from app.pull_coach.service import PullCoachService, source_selection_from_env
from app.pull_coach.sources import LazyLegacyWCLCoachingSource, WipefestCoachingSource
from app.pull_coach.history import (
    EncounterCatalogDiscovery,
    EncounterDiscoveryService,
    HistoricalEncounterCatalog,
    NoCatalogEncounters,
    NoCompletedEncounterPulls,
    discovery_source_fingerprint,
)
from app.web_requests.warcraft_logs import WCLClient
from app.web_requests.warcraft_logs.errors import (
    AuthenticationError, InvalidReportReference, MalformedResponse, PaginationError,
    RateLimitError, ReportUnavailable, TransportError,
)

log = logging.getLogger(__name__)


def _configured_workflow():
    client = WCLClient()
    selection = source_selection_from_env()
    def legacy_workflow():
        return PullCoachWorkflow(client, PullAnalyzer(configured_mechanics_registry()),
                                 ProgressionComparator(), CoachingSynthesizer())
    wipefest = WipefestCoachingSource() if selection.mode is SourceMode.WIPEFEST_PRIMARY else None
    legacy = LazyLegacyWCLCoachingSource(legacy_workflow)
    if wipefest is None:
        wipefest = legacy
    return PullCoachService(client, CoachingOrchestrator(wipefest, legacy, selection))


def _configured_catalog_discovery():
    return EncounterCatalogDiscovery(WCLClient(), configured_mechanics_registry())


@dataclass(frozen=True)
class HistoricalEncounterSelection:
    """Minimal stable handoff from the browser to historical analysis."""

    report_code: str
    source_url: str
    encounter_id: str


@dataclass(frozen=True)
class FightSelection:
    fight_id: str
    encounter_name: str


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
    if isinstance(exc, PullCoachConfigurationError):
        return "Pull Coach is not configured to load mechanic definitions. Contact a bot administrator."
    if isinstance(exc, UnsupportedEncounter):
        return "Pull Coach doesn't have mechanic definitions for that encounter yet."
    if isinstance(exc, NoCompletedEncounterPulls):
        return "That encounter has no completed pulls to inspect in this report."
    if isinstance(exc, MechanicsStoreError):
        return "Pull Coach discovery storage is unavailable. Contact a bot administrator."
    if isinstance(exc, NoCompletedPulls):
        return "That report has no completed boss pulls to analyze."
    if isinstance(exc, FightNotFound):
        return "I couldn't find that fight ID in the report."
    if isinstance(exc, FightNotCompleted):
        return "That fight is still in progress; Pull Coach only analyzes completed pulls."
    if isinstance(exc, InvalidFightSelector):
        return "Fight must be `latest` or a Warcraft Logs fight ID."
    if isinstance(exc, CoachingSourceError):
        return "Coaching is temporarily unavailable or not configured. Please try again later."
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

    def __init__(self, catalog: HistoricalEncounterCatalog, owner_id: int, on_selection,
                 on_unsupported_selection=None):
        super().__init__(timeout=300)
        self.catalog = catalog
        self.owner_id = owner_id
        self.on_selection = on_selection
        self.on_unsupported_selection = on_unsupported_selection
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
        self.completed = True
        self.stop()
        self._disable_items()
        # Acknowledge and disable the picker before the downstream handler can do slow work.
        try:
            await interaction.response.edit_message(view=self)
        except (discord.HTTPException, discord.NotFound):
            return
        selection = HistoricalEncounterSelection(self.catalog.report_code, self.catalog.source_url, encounter_id)
        if not summary.mechanics_supported and source_selection_from_env().mode is SourceMode.LEGACY_ONLY:
            try:
                if self.on_unsupported_selection is None:
                    await interaction.followup.send(
                        "Pull Coach discovery is not configured. Contact a bot administrator.", ephemeral=True)
                    return
                result = self.on_unsupported_selection(selection, summary, interaction)
                if inspect.isawaitable(result):
                    await result
            except Exception:
                await interaction.followup.send("I couldn't inspect that encounter. Please try again later.", ephemeral=True)
            return
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


class FightPicker(discord.ui.View):
    """Owner-scoped paginated selector for completed WCL report fights."""
    PAGE_SIZE = 25

    def __init__(self, fights, owner_id: int, on_selection):
        super().__init__(timeout=300)
        self.fights, self.owner_id, self.on_selection = tuple(fights), owner_id, on_selection
        self.page = 0
        self.completed = False
        self.expired = False
        self.message = None
        self._render()

    @property
    def page_count(self):
        return max(1, (len(self.fights) + self.PAGE_SIZE - 1) // self.PAGE_SIZE)

    def _render(self):
        self.clear_items()
        page_fights = self.fights[self.page * self.PAGE_SIZE:(self.page + 1) * self.PAGE_SIZE]
        options = []
        for fight in page_fights:
            label = f"Fight {fight.fight_id} · {fight.encounter_name}"[:100]
            result = "Kill" if fight.is_kill else "Wipe"
            percent = f" · {fight.boss_percentage:.1f}% remaining" if fight.boss_percentage is not None and not fight.is_kill else ""
            options.append(discord.SelectOption(label=label, value=fight.fight_id,
                                                description=f"{result}{percent}"[:100]))
        selector = discord.ui.Select(placeholder=f"Choose a fight · page {self.page + 1}/{self.page_count}",
                                     options=options, min_values=1, max_values=1)
        selector.callback = self._select
        self.add_item(selector)
        previous = discord.ui.Button(label="Previous", style=discord.ButtonStyle.secondary, disabled=self.page == 0)
        previous.callback = self._previous
        following = discord.ui.Button(label="Next", style=discord.ButtonStyle.secondary,
                                      disabled=self.page >= self.page_count - 1)
        following.callback = self._next
        self.add_item(previous)
        self.add_item(following)

    async def interaction_check(self, interaction):
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("This fight browser belongs to another user.", ephemeral=True)
            return False
        if self.completed or self.expired:
            await interaction.response.send_message("This fight browser has expired.", ephemeral=True)
            return False
        return True

    async def _move(self, interaction, delta):
        self.page = max(0, min(self.page_count - 1, self.page + delta))
        self._render()
        await interaction.response.edit_message(view=self)

    async def _previous(self, interaction):
        await self._move(interaction, -1)

    async def _next(self, interaction):
        await self._move(interaction, 1)

    async def _select(self, interaction):
        if not await self.interaction_check(interaction):
            return
        fight_id = interaction.data["values"][0]
        fight = next((fight for fight in self.fights if fight.fight_id == fight_id), None)
        if fight is None:
            await interaction.response.send_message("That fight is no longer available.", ephemeral=True)
            return
        self.completed = True
        self.stop()
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(view=self)
        result = self.on_selection(FightSelection(fight.fight_id, fight.encounter_name), interaction)
        if inspect.isawaitable(result):
            await result

    async def on_timeout(self):
        self.expired = True
        for item in self.children:
            item.disabled = True
        try:
            if self.message is not None:
                await self.message.edit(content="Fight browser expired.", view=self)
        except (discord.HTTPException, discord.NotFound):
            pass


class PullCoach(commands.Cog):
    def __init__(self, bot, workflow_factory=None, presenter=None, catalog_factory=None, selection_handler=None,
                 discovery_factory=None, mechanics_store_factory=None):
        self.bot = bot
        self.workflow_factory = workflow_factory or _configured_workflow
        self.presenter = presenter or PullCoachPresenter()
        self.catalog_factory = catalog_factory or _configured_catalog_discovery
        self.selection_handler = selection_handler or self._handle_historical_selection
        self.discovery_factory = discovery_factory or (
            lambda writer: EncounterDiscoveryService(WCLClient(), writer))
        self.mechanics_store_factory = mechanics_store_factory or self._configured_discovery_store

    async def _browse_fights(self, ctx, report, *, character=None):
        service = self.workflow_factory()
        listing = getattr(service, "list_completed_fights", None)
        if listing is None:
            raise CoachingSourceError("completed fight browsing is not configured")
        fights = await asyncio.to_thread(listing, report)
        if not fights:
            raise NoCompletedPulls("report has no completed boss encounter fights")
        async def selected(selection, interaction):
            try:
                if character is None:
                    result = await asyncio.to_thread(service.run, report, selection.fight_id)
                else:
                    result = await asyncio.to_thread(service.run_player, report, selection.fight_id, character)
                result = getattr(result, "legacy_result", None) or result
                if character is not None:
                    result.coaching["_character"] = character
                payload = self.presenter.present(result)
                await interaction.followup.send(embed=to_discord_embed(payload),
                    view=PullCoachDetailsView(payload.details), ephemeral=character is not None)
            except Exception as exc:
                await interaction.followup.send(_friendly_error(exc), ephemeral=True)
        view = FightPicker(fights, ctx.author.id, selected)
        message = await ctx.followup.send("Choose a completed boss fight:", view=view, wait=True, ephemeral=True)
        view.message = message

    @staticmethod
    def _configured_discovery_store():
        root = os.getenv("PULL_COACH_MECHANICS_ROOT")
        if not root:
            raise PullCoachConfigurationError("directory-backed mechanics storage is required for discovery")
        store = DirectoryMechanicsStore(root)
        if not store.root.is_dir() or not os.access(store.root, os.W_OK | os.X_OK):
            raise PullCoachConfigurationError("configured mechanics storage is not writable")
        return store

    async def _handle_unsupported_selection(self, selection, summary, interaction):
        try:
            store = self.mechanics_store_factory()
            fingerprint = discovery_source_fingerprint(selection.source_url or selection.report_code)
            artifact = await asyncio.to_thread(store.read_discovery, selection.encounter_id)
            expected_fights = tuple(sorted(summary.fight_ids))
            provenance = artifact.provenance if artifact else ()
            existing_fights = tuple(sorted(item.fight_id for item in provenance))
            reused = (artifact is not None and bool(provenance)
                      and all(item.source_fingerprint == fingerprint for item in provenance)
                      and existing_fights == expected_fights)
            if not reused:
                service = self.discovery_factory(store)
                artifact = await asyncio.to_thread(service.discover,
                    selection.source_url or selection.report_code, selection.encounter_id)
            message = (
                f"Pull Coach hasn't verified {summary.name} yet.\n"
                f"I inspected {len(artifact.provenance)} completed pulls and found "
                f"{len(artifact.candidates)} mechanic/ability candidates.\n"
                "The encounter has been queued for mechanic review.")
            await interaction.followup.send(message, ephemeral=True)
        except Exception as exc:
            log.error("Pull Coach discovery failed encounter=%s stage=discovery error_type=%s",
                      selection.encounter_id, type(exc).__name__)
            message = ("Pull Coach discovery storage is not configured correctly. Contact a bot administrator."
                       if isinstance(exc, PullCoachConfigurationError) else _friendly_error(exc))
            await interaction.followup.send(message, ephemeral=True)

    async def _handle_historical_selection(self, selection, interaction):
        code = selection.report_code
        try:
            workflow = self.workflow_factory()
            reference = selection.source_url or selection.report_code
            result = await asyncio.to_thread(workflow.run_encounter_sample, reference, selection.encounter_id)
            result = getattr(result, "legacy_result", None) or result
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
                        fight: discord.Option(str, "latest, browse, or Warcraft Logs fight ID", default="latest")):
        await ctx.defer()
        code = "unknown"
        try:
            # Log report and requested selector without exception text, which may contain sensitive data.
            from app.web_requests.warcraft_logs import parse_report_code
            code = parse_report_code(report)
            if str(fight).strip().lower() == "browse":
                await self._browse_fights(ctx, report)
                return
            workflow = self.workflow_factory()
            result = await asyncio.to_thread(workflow.run, report, fight)
            result = getattr(result, "legacy_result", None) or result
            payload = self.presenter.present(result)
            await ctx.followup.send(embed=to_discord_embed(payload),
                                    view=PullCoachDetailsView(payload.details))
        except Exception as exc:
            log.error("Pull Coach command failed report=%s fight=%s stage=command error_type=%s",
                      code, fight, type(exc).__name__)
            await ctx.followup.send(_friendly_error(exc))

    @discord.slash_command(name="how-did-i-do", description="Get private coaching for a character in a fight")
    async def how_did_i_do(self, ctx: discord.ApplicationContext,
                           report: discord.Option(str, "Warcraft Logs report URL or code"),
                           character: discord.Option(str, "Wipefest character name or player ID"),
                           fight: discord.Option(str, "latest, browse, or Warcraft Logs fight ID", default="latest")):
        await ctx.defer(ephemeral=True)
        try:
            if str(fight).strip().lower() == "browse":
                await self._browse_fights(ctx, report, character=character)
                return
            service = self.workflow_factory()
            run_player = getattr(service, "run_player", None)
            if run_player is None:
                raise CoachingSourceError("individual coaching is not configured")
            result = await asyncio.to_thread(run_player, report, fight, character)
            result.coaching["_character"] = character
            payload = self.presenter.present(result)
            await ctx.followup.send(embed=to_discord_embed(payload),
                                    view=PullCoachDetailsView(payload.details), ephemeral=True)
        except Exception as exc:
            log.error("Individual Pull Coach failed stage=command error_type=%s", type(exc).__name__)
            await ctx.followup.send(_friendly_error(exc), ephemeral=True)

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
            view = HistoricalEncounterPicker(
                catalog, ctx.author.id, self.selection_handler, self._handle_unsupported_selection)
            message = await ctx.followup.send("Choose a boss encounter:", view=view, wait=True)
            view.message = message
        except Exception as exc:
            log.error("Pull Coach history failed report=%s stage=catalog error_type=%s", code, type(exc).__name__)
            await ctx.followup.send(_friendly_error(exc))


def setup(bot):
    bot.add_cog(PullCoach(bot))
