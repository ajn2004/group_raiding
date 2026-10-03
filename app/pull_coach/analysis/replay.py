"""Production replay adapter for deterministic pull analysis."""

from .analyzer import PullAnalyzer


class AnalysisReplayStage:
    name = "analysis"

    def __init__(self, analyzer: PullAnalyzer):
        self.analyzer = analyzer

    def run(self, context):
        ingestion = context.current
        return self.analyzer.analyze(ingestion.pull, ingestion.actors, ingestion.events)
