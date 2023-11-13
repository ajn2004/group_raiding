from datetime import datetime
from apscheduler.schedulers.background import BackgroundScheduler

from app.db.controller import DBController
from app.web_requests.warcraft_logs.controller import WCLController
from app.casino.table import Table


class Casino:

    def __init__(self):
        self.db_controller = DBController()
        self.wcl_controller = WCLController()
        self.report_scheduler = BackgroundScheduler()
        self.report_scheduler.add_job(self.check_tables, 'interval', minutes=10)
        self.report_scheduler.start()
        self.tables = []

    def create_table(self, wcl_report):
        for table in self.tables:
            if table.wcl_report_id == wcl_report:
                return {'success': False, 'message': f"Table for report: {wcl_report} already exists."}
        new_table = Table(self.report_scheduler, self.db_controller, self.wcl_controller, wcl_report)
        self.tables.append(new_table)
        return {
            'success': True,
            'message': f"Table for report: {wcl_report} created.",
            'table': new_table
        }

    def check_tables(self):
        for table in self.tables:
            if table.expire_time < datetime.now():
                del table

