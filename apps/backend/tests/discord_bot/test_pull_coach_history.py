import asyncio
import os
import threading
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

from app.discord_bot.commands import pull_coach as module
from app.discord_bot.commands.pull_coach import HistoricalEncounterPicker, HistoricalEncounterSelection, PullCoach
from app.pull_coach.history import HistoricalEncounterCatalog, HistoricalEncounterSummary


def encounter(index, supported=True, kill=False):
    return HistoricalEncounterSummary(str(index), f"Boss {index}", (f"{index}a", f"{index}b"),
                                      2, kill, f"{index}b", None, 1, 2, supported)


def catalog(encounters):
    return HistoricalEncounterCatalog("REPORT", "https://www.warcraftlogs.com/reports/REPORT", tuple(encounters))


def make_view(*args):
    async def create():
        return HistoricalEncounterPicker(*args)
    return asyncio.run(create())


class Interaction:
    def __init__(self, user_id=7, values=()):
        self.user = SimpleNamespace(id=user_id)
        self.data = {"values": list(values)}
        self.response = self
        self.sent = []
        self.followup = self

    async def send_message(self, message, **kwargs):
        self.sent.append((message, kwargs))

    async def edit_message(self, **kwargs):
        self.sent.append(("edit", kwargs))

    async def send(self, message, **kwargs):
        self.sent.append((message, kwargs))

    async def edit_original_response(self, **kwargs):
        self.sent.append(("edit original", kwargs))


def test_history_command_defers_then_offloads_dal57_catalog_discovery(monkeypatch):
    calls = []

    class Discovery:
        def discover(self, reference):
            calls.append(("discover", reference))
            return catalog([encounter(1)])

    class Followup:
        async def send(self, *args, **kwargs):
            calls.append(("send", args, kwargs))
            return SimpleNamespace()

    class Context:
        author = SimpleNamespace(id=7)
        followup = Followup()

        async def defer(self, **kwargs):
            calls.append(("defer", kwargs))

    async def to_thread(fn, *args):
        calls.append(("thread",))
        return fn(*args)

    monkeypatch.setattr(module.asyncio, "to_thread", to_thread)
    cog = PullCoach(None, catalog_factory=Discovery)
    asyncio.run(PullCoach.pullcoach_history.callback(cog, Context(), "https://www.warcraftlogs.com/reports/REPORT?fight=4"))
    assert calls[0] == ("defer", {"ephemeral": True})
    assert calls[1] == ("thread",)
    assert calls[2] == ("discover", "https://www.warcraftlogs.com/reports/REPORT?fight=4")
    assert calls[3][0] == "send"
    assert calls[3][2]["view"].catalog.report_code == "REPORT"


@pytest.mark.parametrize("reference", ["REPORT", "https://www.warcraftlogs.com/reports/REPORT"])
def test_catalog_discovery_receives_bare_code_or_url(monkeypatch, reference):
    seen = []

    class Discovery:
        def discover(self, value):
            seen.append(value)
            return catalog([encounter(10)])

    class Context:
        author = SimpleNamespace(id=1)
        followup = SimpleNamespace(send=lambda *a, **k: asyncio.sleep(0))

        async def defer(self, **kwargs):
            pass

    monkeypatch.setattr(module.asyncio, "to_thread", lambda fn, *args: _thread(fn, *args))
    async def run():
        await PullCoach.pullcoach_history.callback(PullCoach(None, catalog_factory=Discovery), Context(), reference)
    asyncio.run(run())
    assert seen == [reference]


async def _thread(fn, *args):
    return fn(*args)


def test_picker_options_use_encounter_ids_and_summarize_catalog():
    view = make_view(catalog([encounter(42, True, True), encounter(43, False)]), 7, lambda _: None)
    options = view.children[0].options
    assert [option.value for option in options] == ["42", "43"]
    assert all(option.value != option.label for option in options)
    assert "2 pulls · kill · supported" == options[0].description
    assert "2 pulls · no kill · unsupported" == options[1].description


def test_unsupported_selection_uses_discovery_handoff_and_completes_picker():
    called = []
    view = make_view(catalog([encounter(1, False)]), 7, lambda *_: None,
                     lambda selection, summary, interaction: called.append((selection, summary)))
    interaction = Interaction(values=["1"])
    asyncio.run(view._select(interaction))
    assert len(called) == 1
    assert called[0][0].encounter_id == "1"
    assert view.completed and all(child.disabled for child in view.children)
    asyncio.run(view._select(interaction))
    assert len(called) == 1


def test_supported_selection_acknowledges_before_handoff_and_passes_interaction_once():
    received = []
    order = []

    def handoff(selection, interaction):
        order.append("handoff")
        received.append((selection, interaction))

    view = make_view(catalog([encounter(42)]), 7, handoff)
    interaction = Interaction(values=["42"])
    original_edit = interaction.edit_message

    async def acknowledge(**kwargs):
        order.append("acknowledge")
        await original_edit(**kwargs)

    interaction.edit_message = acknowledge
    asyncio.run(view._select(interaction))
    assert order == ["acknowledge", "handoff"]
    assert received == [(HistoricalEncounterSelection("REPORT", "https://www.warcraftlogs.com/reports/REPORT", "42"), interaction)]
    assert interaction.sent[-1][0].startswith("Selected Boss 42")
    assert view.completed and all(child.disabled for child in view.children)
    asyncio.run(view._select(Interaction(values=["42"])))
    assert len(received) == 1


def test_default_handoff_runs_workflow_in_thread_and_posts_report_publicly(monkeypatch):
    calls = []
    payload = SimpleNamespace(details="finding · evidence: ev-1", embed=SimpleNamespace(
        title="Historical Pull Coach — Boss", description="3 completed pulls", url="https://wcl/fight=3",
        fields=(), footer="Pull Coach"))
    class Workflow:
        def run_encounter_sample(self, reference, encounter_id):
            calls.append(("workflow", reference, encounter_id))
            return object()
    class Presenter:
        def present(self, result):
            calls.append(("present",))
            return payload
    class Channel:
        async def send(self, **kwargs):
            calls.append(("public", kwargs))
    interaction = Interaction(values=["42"])
    interaction.channel = Channel()
    async def to_thread(fn, *args):
        calls.append(("thread",))
        return fn(*args)
    monkeypatch.setattr(module.asyncio, "to_thread", to_thread)
    cog = PullCoach(None, workflow_factory=Workflow, presenter=Presenter())
    view = make_view(catalog([encounter(42)]), 7, cog.selection_handler)
    asyncio.run(view._select(interaction))
    assert calls[0] == ("thread",)
    assert calls[1] == ("workflow", "https://www.warcraftlogs.com/reports/REPORT", "42")
    public = next(item[1] for item in calls if item[0] == "public")
    assert public["embed"].title.startswith("Historical Pull Coach")
    assert isinstance(public["view"], module.PullCoachDetailsView)
    assert public["view"].details == payload.details
    assert sum(item[0] == "public" for item in calls) == 1


def test_default_handoff_sanitizes_expected_failure_without_public_post(monkeypatch):
    class Workflow:
        def run_encounter_sample(self, reference, encounter_id):
            raise module.UnsupportedEncounter("secret details")
    async def to_thread(fn, *args):
        return fn(*args)
    monkeypatch.setattr(module.asyncio, "to_thread", to_thread)
    interaction = Interaction(values=["42"])
    interaction.channel = SimpleNamespace(send=lambda **kwargs: asyncio.sleep(0))
    cog = PullCoach(None, workflow_factory=Workflow)
    view = make_view(catalog([encounter(42)]), 7, cog.selection_handler)
    asyncio.run(view._select(interaction))
    assert any("doesn't have mechanic definitions" in message for message, _ in interaction.sent if isinstance(message, str))
    assert not any("Selected Boss" in message for message, _ in interaction.sent if isinstance(message, str))


def test_discovery_is_ephemeral_off_thread_and_persists_only_selected_encounter(monkeypatch, tmp_path):
    from app.pull_coach.mechanics.store import DirectoryMechanicsStore
    from app.pull_coach.models import DiscoveryProvenance, EncounterDiscovery, CandidateMechanic
    from app.pull_coach.models import EventType
    root = tmp_path / "mechanics"
    store = DirectoryMechanicsStore(root)
    candidate = CandidateMechanic("ability:9", "Ability", (EventType.CAST,), (), (), (("1a", 2),), None, 1, 2, 0)
    artifact = EncounterDiscovery("1", "Boss 1", (DiscoveryProvenance("warcraftlogs",
        module.discovery_source_fingerprint("REPORT"), "1a"), DiscoveryProvenance("warcraftlogs",
        module.discovery_source_fingerprint("REPORT"), "1b")), (candidate,))
    calls = []
    main_thread = threading.get_ident()
    class Service:
        def discover(self, reference, encounter_id):
            calls.append(("discover", reference, encounter_id, threading.get_ident()))
            store.write_discovery(artifact)
            return artifact
    cog = PullCoach(None, mechanics_store_factory=lambda: store, discovery_factory=lambda writer: Service())
    view = make_view(catalog([encounter(1, False)]), 7, lambda *_: pytest.fail("analysis ran"),
                     cog._handle_unsupported_selection)
    interaction = Interaction(values=["1"])
    original_edit = interaction.edit_message
    order = []
    async def acknowledge(**kwargs):
        order.append("ack")
        await original_edit(**kwargs)
    interaction.edit_message = acknowledge
    async def thread(fn, *args):
        order.append("work")
        return await asyncio.get_running_loop().run_in_executor(None, lambda: fn(*args))
    monkeypatch.setattr(module.asyncio, "to_thread", thread)
    asyncio.run(view._select(interaction))
    assert order == ["ack", "work", "work"]  # artifact lookup then discovery
    assert calls[0][1:3] == ("https://www.warcraftlogs.com/reports/REPORT", "1")
    assert calls[0][3] != main_thread
    assert store.read_discovery("1") == artifact
    message, kwargs = interaction.sent[-1]
    assert kwargs["ephemeral"] is True
    assert "2 completed pulls" in message and "1 mechanic/ability candidates" in message
    assert "hasn't verified Boss 1" in message and "queued for mechanic review" in message
    assert "REPORT" not in message and "Ability" not in message


def test_matching_artifact_reused_but_fight_set_or_report_mismatch_rediscover(tmp_path, monkeypatch):
    from app.pull_coach.mechanics.store import DirectoryMechanicsStore
    from app.pull_coach.models import DiscoveryProvenance, EncounterDiscovery
    store = DirectoryMechanicsStore(tmp_path)
    fp = module.discovery_source_fingerprint("REPORT")
    def artifact(fights, fingerprint=fp):
        return EncounterDiscovery("1", "Boss", tuple(DiscoveryProvenance("warcraftlogs", fingerprint, i) for i in fights), ())
    store.write_discovery(artifact(["1a", "1b"]))
    calls = []
    class Service:
        def discover(self, *_):
            calls.append("discover")
            value = artifact(["1a", "1b"])
            store.write_discovery(value)
            return value
    cog = PullCoach(None, mechanics_store_factory=lambda: store, discovery_factory=lambda _: Service())
    async def thread(fn, *args):
        return fn(*args)
    monkeypatch.setattr(module.asyncio, "to_thread", thread)
    async def run(summary):
        i = Interaction(values=["1"])
        v = HistoricalEncounterPicker(catalog([summary]), 7, lambda *_: None, cog._handle_unsupported_selection)
        await v._select(i)
    asyncio.run(run(encounter(1, False)))
    assert calls == []
    changed = HistoricalEncounterSummary("1", "Boss 1", ("1a", "1c"), 2, False, "1c", None, 1, 2, False)
    asyncio.run(run(changed))
    assert calls == ["discover"]
    store.write_discovery(artifact(["1a", "1b"], "0" * 64))
    asyncio.run(run(encounter(1, False)))
    assert calls == ["discover", "discover"]


def test_missing_writable_root_is_sanitized_ephemerally(monkeypatch):
    monkeypatch.delenv("PULL_COACH_MECHANICS_ROOT", raising=False)
    cog = PullCoach(None)
    interaction = Interaction()
    summary = encounter(1, False)
    asyncio.run(cog._handle_unsupported_selection(HistoricalEncounterSelection("REPORT", "https://www.warcraftlogs.com/reports/REPORT", "1"), summary, interaction))
    assert "storage" in interaction.sent[-1][0] and interaction.sent[-1][1]["ephemeral"]
    assert "REPORT" not in interaction.sent[-1][0]


def test_direct_outsider_selection_cannot_reach_handoff():
    called = []
    view = make_view(catalog([encounter(42)]), 7, lambda selection, interaction: called.append(selection))
    outsider = Interaction(user_id=8, values=["42"])
    asyncio.run(view._select(outsider))
    assert not called
    assert "another user" in outsider.sent[0][0]


def test_picker_user_scope_and_navigation_pagination_boundaries():
    view = make_view(catalog([encounter(i) for i in range(51)]), 7, lambda _: None)
    assert len(view.children[0].options) == 25
    assert view.children[1].disabled and not view.children[2].disabled
    outsider = Interaction(user_id=8)
    assert not asyncio.run(view.interaction_check(outsider))
    assert outsider.sent and view.page == 0
    asyncio.run(view._next(Interaction()))
    assert view.page == 1 and len(view.children[0].options) == 25
    asyncio.run(view._next(Interaction()))
    assert view.page == 2 and [o.value for o in view.children[0].options] == ["50"]
    asyncio.run(view._next(Interaction()))
    assert view.page == 2
    asyncio.run(view._previous(Interaction()))
    assert view.page == 1
    values = [option.value for page in range(view.page_count) for option in _page_options(view, page)]
    assert values == [str(i) for i in range(51)]


def _page_options(view, page):
    view.page = page
    view._render()
    return view.children[0].options


def test_timeout_disables_picker_and_tolerates_deleted_message():
    view = make_view(catalog([encounter(1)]), 7, lambda _: None)

    class Deleted:
        async def edit(self, **kwargs):
            assert kwargs["content"] == "Encounter browser expired."
            raise module.discord.NotFound(SimpleNamespace(status=404, reason="Not Found"), "deleted")

    view.message = Deleted()
    asyncio.run(view.on_timeout())
    assert view.expired and all(child.disabled for child in view.children)


def test_no_catalog_encounters_has_specific_message_and_errors_are_sanitized():
    from app.pull_coach.history import NoCatalogEncounters
    assert module._friendly_error(NoCatalogEncounters("secret raw response")) == "That report has no completed boss pulls to browse."
    assert "secret" not in module._friendly_error(module.TransportError("secret token"))


def test_catalog_discovery_uses_metadata_query_without_event_endpoint():
    from app.pull_coach.history import EncounterCatalogDiscovery
    from app.web_requests.warcraft_logs import WCLClient
    queries = []

    class Transport:
        def graphql(self, query, variables):
            queries.append(query)
            return {"data": {"reportData": {"report": {"fights": [
                {"id": 1, "encounterID": 42, "name": "Boss", "startTime": 1,
                 "endTime": 2, "inProgress": False, "kill": False}
            ]}}}}

    result = EncounterCatalogDiscovery(WCLClient(transport=Transport())).discover("REPORT")
    assert result.encounters[0].encounter_id == "42"
    assert len(queries) == 1
    assert "events(" not in queries[0]


def test_bot_registers_both_pullcoach_commands():
    async def get_bot():
        from app.discord_bot.bot import bot
        return bot
    bot = asyncio.run(get_bot())
    assert {"pullcoach", "pullcoach-history"}.issubset({c.name for c in bot.pending_application_commands})
