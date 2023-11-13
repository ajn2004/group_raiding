import requests
from datetime import datetime, timedelta
from python_graphql_client import GraphqlClient
from app.config import WCL_CLIENT_ID, WCL_CLIENT_SECRET

from app.web_requests.warcraft_logs.queries import get_report_data, get_encounter_deaths


class WCLController:

    def __init__(self):
        self.__wcl_fetch_auth_token()
        self.wcl_client = GraphqlClient(
            endpoint="https://classic.warcraftlogs.com/api/v2/client",
            headers={'Authorization': self.auth_token}
        )

    def __wcl_fetch_auth_token(self):
        results = requests.post(
            url='https://www.warcraftlogs.com/oauth/token',
            data={"grant_type": " client_credentials"},
            auth=(WCL_CLIENT_ID, WCL_CLIENT_SECRET)
        )
        results = results.json()
        self.auth_token = f"Bearer {results['access_token']}"
        self.token_expires = datetime.now() + timedelta(seconds=results['expires_in'])

    def __check_auth_token(self):
        if datetime.now() > self.token_expires - timedelta(seconds=60):
            self.__wcl_fetch_auth_token()

    def get_log_data(self, report_id: str):
        self.__check_auth_token()
        results = self.wcl_client.execute(query=get_report_data, variables={'reportCode': report_id})
        return results['data']['reportData']['report']

    def get_encounter_deaths(self, report_id, start_time, end_time):
        self.__check_auth_token()
        results = self.wcl_client.execute(
            query=get_encounter_deaths, variables={
                'reportCode': report_id,
                'startTime': start_time,
                'endTime': end_time
            }
        )
        return results['data']['reportData']['report']
