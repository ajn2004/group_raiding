from app.web_requests.warcraft_logs.client import WCLClient
from app.web_requests.warcraft_logs.queries import get_encounter_deaths


class WCLController:

    def __init__(self):
        self.client = WCLClient()

    def get_log_data(self, report_id: str):
        """Legacy raw report metadata method retained for casino/table callers."""
        return self.client.report_data(report_id)

    def get_encounter_deaths(self, report_id, start_time, end_time):
        """Legacy deaths query; preserve raw report response shape."""
        from app.web_requests.warcraft_logs.client import parse_report_code
        code = parse_report_code(report_id)
        body = self.client.transport.graphql(get_encounter_deaths, {
            "reportCode": code, "startTime": start_time, "endTime": end_time,
        })
        return body["data"]["reportData"]["report"]
