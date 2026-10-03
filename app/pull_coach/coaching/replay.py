"""DAL-52 stage adapter; core synthesis remains ReplayContext-independent."""
from .synthesizer import CoachingSynthesizer


class CoachingReplayStage:
    name = "coaching"

    def __init__(self, synthesizer=None, mechanic_labels=None):
        self.synthesizer = synthesizer or CoachingSynthesizer()
        self.mechanic_labels = mechanic_labels

    def run(self, context):
        analysis = context.current_stage_outputs["analysis"]
        progression = context.current_stage_outputs["progression"]
        prior = tuple(result.stages["analysis"] for result in context.prior_pull_results
                      if result.encounter_id == context.encounter_id and "analysis" in result.stages)
        return self.synthesizer.synthesize(analysis, progression, prior, self.mechanic_labels)
