import asyncio
import os
from types import SimpleNamespace

for key, value in {
    "SQLALCHEMY_DATABASE_USER": "test", "SQLALCHEMY_DATABASE_PASSWORD": "test",
    "SQLALCHEMY_DATABASE_HOST": "localhost", "SQLALCHEMY_DATABASE_PORT": "5432",
    "SQLALCHEMY_DATABASE_DB": "test",
}.items():
    os.environ[key] = value

from app.discord_bot.commands.pull_coach import FightPicker
from app.pull_coach.service import PullCoachService


def fight(index, *, boss=True, progress=False, end=100, start=None, kill=False, pct=32.4):
    return {"id": index, "encounterID": 42 if boss else 0, "name": f"Boss {index}",
            "startTime": start if start is not None else index, "endTime": end,
            "inProgress": progress, "kill": kill, "bossPercentage": pct,
            "encounterID": 42 if boss else None}


def test_listing_filters_and_orders_using_wcl_fight_ids_without_coaching():
    class WCL:
        def report_data(self, code):
            assert code == "ABC123"
            return {"fights": [fight(3), fight(1), fight(4, boss=False),
                               fight(5, progress=True, end=None), fight(6, end=None)]}

    class Orchestrator:
        legacy = SimpleNamespace()
        def coach(self, *args):
            raise AssertionError("listing must not coach")

    result = PullCoachService(WCL(), Orchestrator()).list_completed_fights("ABC123")
    assert [item.fight_id for item in result] == ["1", "3"]
    assert result[0].encounter_name == "Boss 1"
    assert result[0].boss_percentage == 32.4


def test_fight_picker_paginates_displays_fight_ids_and_hands_off_exact_id():
    fights = tuple(SimpleNamespace(fight_id=str(i), encounter_name=f"Boss {i}", is_kill=i == 1,
                                   boss_percentage=32.4) for i in range(1, 28))
    received = []
    async def run():
        view = FightPicker(fights, 7, lambda selection, _: received.append(selection))
        assert len(view.children[0].options) == 25
        assert view.children[0].options[0].label == "Fight 1 · Boss 1"
        assert view.children[0].options[0].description == "Kill"
        assert view.children[0].options[1].description == "Wipe · 32.4% remaining"
        class Interaction:
            user = SimpleNamespace(id=7)
            data = {"values": ["27"]}
            async def edit_message(self, **kwargs): pass
            async def send_message(self, *args, **kwargs): pass
        interaction = Interaction()
        interaction.response = interaction
        await view._next(interaction)
        assert view.page == 1 and len(view.children[0].options) == 2
        await view._previous(interaction)
        assert view.page == 0
        await view._next(interaction)
        await view._select(interaction)
        assert received[0].fight_id == "27"
        assert view.completed and all(item.disabled for item in view.children)
    asyncio.run(run())


def test_fight_picker_rejects_other_users_and_disables_controls_on_timeout():
    fight_item = SimpleNamespace(fight_id="14", encounter_name="Boss", is_kill=False, boss_percentage=None)
    async def run():
        view = FightPicker([fight_item], 7, lambda *_: None)
        class Interaction:
            user = SimpleNamespace(id=8)
            async def send_message(self, *args, **kwargs): self.sent = args
        interaction = Interaction()
        interaction.response = interaction
        assert await view.interaction_check(interaction) is False
        assert "another user" in interaction.sent[0]
        await view.on_timeout()
        assert view.expired and all(item.disabled for item in view.children)
    asyncio.run(run())
