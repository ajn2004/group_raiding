"""DAL-52 adapter; translates the runner's causal prefix to the pure comparator."""
from .comparator import ProgressionComparator


class ProgressionReplayStage:
    name = "progression"

    def __init__(self, comparator: ProgressionComparator | None = None):
        self.comparator = comparator or ProgressionComparator()

    def run(self, context):
        current = context.current_stage_outputs["analysis"]
        previous = tuple(result.stages["analysis"] for result in context.prior_pull_results
                         if result.encounter_id == context.encounter_id and "analysis" in result.stages)
        return self.comparator.compare((*previous, current))
