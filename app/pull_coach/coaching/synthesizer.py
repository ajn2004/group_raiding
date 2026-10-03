from dataclasses import dataclass

from app.pull_coach.models import ProgressionStatus
from .candidates import generate
from .input import build_input
from .models import (CoachingResult, CoachingSelection, GeneratorMetadata, PrivatePlayerFeedback,
                     PublicCoaching, ValidationMetadata)
from .prompt import PROMPT_VERSION, build_prompt
from .provider import CoachingProviderError
from .renderer import render


@dataclass(frozen=True)
class CoachingConfig:
    max_improvements: int = 2
    max_actions_per_role: int = 1
    max_raid_actions: int = 1
    max_priorities: int = 3
    max_rendered_characters: int = 1800
    template_version: str = "1"


class CoachingSynthesizer:
    def __init__(self, provider=None, config: CoachingConfig | None = None):
        self.provider = provider
        self.config = config or CoachingConfig()

    def synthesize(self, analysis, progression, history=(), mechanic_labels=None):
        value = build_input(analysis, progression, history, mechanic_labels)
        candidates = generate(value)
        by_id = {c.candidate_id: c for c in candidates}
        limits = {"improvements": self.config.max_improvements, "actions_per_role": self.config.max_actions_per_role,
                  "raid_actions": self.config.max_raid_actions, "priorities": self.config.max_priorities}
        selection = self._fallback(candidates, progression)
        status, provider_name, model, rejected = "fallback_no_provider", "deterministic-fallback", None, ()
        if self.provider is not None:
            try:
                response = self.provider.select(value, build_prompt(value, candidates, limits))
            except CoachingProviderError:
                status = "fallback_provider_error"
            else:
                provider_selection, rejected = self._validate(response, by_id)
                provider_name = getattr(self.provider, "provider_name", "provider")
                model = getattr(self.provider, "model_name", None)
                if provider_selection is None:
                    selection = self._fallback(candidates, progression)
                    status = "fallback_invalid_provider"
                    provider_name = "deterministic-fallback"
                    model = None
                else:
                    selection = self._merge_selection(selection, provider_selection)
                    status = "provider_partial" if rejected or selection != provider_selection else "provider"
        public = self._public(selection, by_id)
        text = render(public, self.config.max_rendered_characters)
        private = self._private(value, candidates)
        return CoachingResult(value, candidates, public, private, text,
            GeneratorMetadata(provider_name, model, f"{self.config.template_version}/prompt-{PROMPT_VERSION}", status),
            ValidationMetadata(tuple(rejected), status.startswith("fallback")))

    def _fallback(self, candidates, progression):
        blocker_subject = (progression.newly_exposed_blocker.subject.subject_id
                           if progression.newly_exposed_blocker else None)
        def ordered(kind, audience=None):
            values = [c for c in candidates if c.kind == kind and (audience is None or c.audience == audience)]
            return sorted(values, key=lambda c: (
                c.progression_subject_ids[0] != blocker_subject
                if blocker_subject and c.progression_subject_ids else False,
                -{"critical": 4, "high": 3, "medium": 2, "low": 1, "info": 0}[c.severity],
                c.progression_subject_ids, c.finding_ids, c.candidate_id))
        primary = ordered("primary_failure")
        improvements = [c for c in candidates if c.kind == "improvement"]
        # Candidate sequence from generator already prioritizes stabilized, resolved, improved.
        improvements = sorted(improvements, key=lambda c: (0 if "stabilized" in c.text else 1 if "resolved" in c.text else 2,
                                                               -{"critical": 4, "high": 3, "medium": 2, "low": 1, "info": 0}[c.severity],
                                                               c.progression_subject_ids))
        dps, healer, tank, raid = ordered("role_action", "dps"), ordered("role_action", "healer"), ordered("role_action", "tank"), ordered("raid_action", "raid")
        subjects = {subject.subject_id: subject for subject in progression.subjects}
        actions = sorted([*dps, *healer, *tank, *raid], key=lambda c: (
            not (blocker_subject and blocker_subject in c.progression_subject_ids),
            -{"critical": 4, "high": 3, "medium": 2, "low": 1, "info": 0}[c.severity],
            -int(subjects.get(c.progression_subject_ids[0]).repeated)
            if c.progression_subject_ids and c.progression_subject_ids[0] in subjects else 0,
            -int(subjects.get(c.progression_subject_ids[0]).death_linked)
            if c.progression_subject_ids and c.progression_subject_ids[0] in subjects else 0,
            -subjects[c.progression_subject_ids[0]].occurrence_count
            if c.progression_subject_ids and c.progression_subject_ids[0] in subjects else 0,
            c.progression_subject_ids, c.finding_ids, c.candidate_id))
        priorities = []
        priority_subjects = set()
        for candidate in actions:
            subject = candidate.progression_subject_ids[0] if candidate.progression_subject_ids else candidate.candidate_id
            if subject not in priority_subjects:
                priorities.append(candidate)
                priority_subjects.add(subject)
        return CoachingSelection(primary[0].candidate_id if primary else None,
            tuple(c.candidate_id for c in improvements[:self.config.max_improvements]),
            tuple(c.candidate_id for c in dps[:self.config.max_actions_per_role]),
            tuple(c.candidate_id for c in healer[:self.config.max_actions_per_role]),
            tuple(c.candidate_id for c in tank[:self.config.max_actions_per_role]),
            tuple(c.candidate_id for c in raid[:self.config.max_raid_actions]),
            tuple(c.candidate_id for c in priorities[:self.config.max_priorities]))

    def _validate(self, result, by_id):
        if not isinstance(result, CoachingSelection):
            return None, ("invalid-selection-type",)
        rejected = []
        def valid(ids, kinds, audiences, limit):
            accepted = []
            for cid in ids:
                candidate = by_id.get(cid) if isinstance(cid, str) else None
                if (candidate is None or candidate.kind not in kinds or candidate.audience not in audiences or
                        cid in accepted or len(accepted) >= limit):
                    rejected.append(str(cid))
                    continue
                accepted.append(cid)
            return tuple(accepted)
        primary = valid((result.primary_failure_id,) if result.primary_failure_id else (),
                        {"primary_failure"}, {"raid"}, 1)
        selection = CoachingSelection(primary[0] if primary else None,
            valid(result.improvement_ids, {"improvement"}, {"raid"}, self.config.max_improvements),
            valid(result.dps_action_ids, {"role_action"}, {"dps"}, self.config.max_actions_per_role),
            valid(result.healer_action_ids, {"role_action"}, {"healer"}, self.config.max_actions_per_role),
            valid(result.tank_action_ids, {"role_action"}, {"tank"}, self.config.max_actions_per_role),
            valid(result.raid_action_ids, {"raid_action"}, {"raid"}, self.config.max_raid_actions),
            valid(result.priority_ids, {"role_action", "raid_action"},
                  {"raid", "dps", "healer", "tank"}, self.config.max_priorities))
        if not any((selection.primary_failure_id, selection.improvement_ids, selection.dps_action_ids,
                    selection.healer_action_ids, selection.tank_action_ids, selection.raid_action_ids,
                    selection.priority_ids)):
            return None, tuple(rejected)
        return selection, tuple(rejected)

    @staticmethod
    def _merge_selection(fallback, chosen):
        """Provider may refine the baseline, but omitted sections retain deterministic choices."""
        from dataclasses import fields
        values = {}
        for field in fields(CoachingSelection):
            provider_value = getattr(chosen, field.name)
            fallback_value = getattr(fallback, field.name)
            values[field.name] = provider_value if provider_value else fallback_value
        return CoachingSelection(**values)

    def _public(self, selection, by_id):
        get = lambda cid: by_id[cid]
        improvements = tuple(get(cid) for cid in selection.improvement_ids)
        return PublicCoaching(get(selection.primary_failure_id) if selection.primary_failure_id else None,
            improvements, tuple(get(x) for x in selection.dps_action_ids),
            tuple(get(x) for x in selection.healer_action_ids), tuple(get(x) for x in selection.tank_action_ids),
            tuple(get(x) for x in selection.raid_action_ids),
            tuple(get(x) for x in selection.priority_ids))

    @staticmethod
    def _private(value, candidates):
        by_finding = {f.finding_id: f for f in value.findings if f.pull_number == value.pull_number}
        grouped = {}
        for candidate in candidates:
            for fid in candidate.finding_ids:
                finding = by_finding.get(fid)
                if finding:
                    for actor in finding.actor_ids:
                        grouped.setdefault(actor, [set(), set()])[0].add(fid)
                        grouped[actor][1].add(candidate.candidate_id)
        return tuple(PrivatePlayerFeedback(actor, tuple(sorted(ids)), tuple(sorted(cids)))
                     for actor, (ids, cids) in sorted(grouped.items()))
