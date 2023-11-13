from datetime import datetime, timedelta
from apscheduler.schedulers.background import BackgroundScheduler

from app.db.controller import DBController
from app.web_requests.warcraft_logs.controller import WCLController
from app.casino.books import Deadpool, WipePrediction


class Table:

    def __init__(
            self,
            scheduler: BackgroundScheduler,
            db_controller: DBController,
            wcl_controller: WCLController,
            wcl_report_id: str
    ):
        # Controllers
        self.db_controller = db_controller
        self.wcl_controller = wcl_controller
        # Table Data
        self.wcl_report_id = wcl_report_id
        self.expire_time = datetime.now() + timedelta(hours=1)
        self.wcl_report = None
        self.check_wcl_report()
        # Books. For now just enable wipe predictions and deadpool by default.
        self.books = [Deadpool(), WipePrediction()]
        # Scheduler
        self.report_scheduler = scheduler
        self.report_scheduler.add_job(self.check_wcl_report, "interval", seconds=30)
        print(f"New table created for report: {self.wcl_report_id}")

    def check_wcl_report(self):
        # This function will pull the latest log data and if it detects a valid fight it will resolve bets
        print(F"Pulling report data for: {self.wcl_report_id}")
        new_wcl_report = self.wcl_controller.get_log_data(self.wcl_report_id)
        if not self.wcl_report:
            self.wcl_report = new_wcl_report
            return
        # An updated end time indicates a new fight log.
        if new_wcl_report['endTime'] > self.wcl_report['endTime']:
            self.wcl_report = new_wcl_report
            self.expire_time = datetime.now() + timedelta(hours=1)
            if last_fight := self.__check_valid_fight():
                self.resolve_bets(last_fight)

    def __check_valid_fight(self):
        """
        We don't want to include trash pulls or boss resets
        :return: last fight details if fight is valid
        """
        if len(self.wcl_report['fights']) == 0:
            return False
        last_fight = self.wcl_report['fights'][-1]
        # No difficulty rating = trash pack
        if not last_fight['difficulty']:
            return False
        # Exclude in progress fights
        if last_fight['inProgress']:
            return False
        # Exclude fights < 30sec or over 90%. These are likely resets.
        if (last_fight['startTime'] - last_fight['startTime'] < 30) or last_fight['fightPercentage'] > 90:
            return False
        return last_fight

    def create_book(self, book_type: str):
        # Added to allow specific books to be selected in the future.
        if book_type == 'wipe_prediction':
            self.books.append(WipePrediction())
        elif book_type == 'wipe_prediction':
            self.books.append(Deadpool())

    def delete_book(self, book_id: str):
        pass

    def place_bet(self, book_id: str):
        pass

    def cancel_bet(self, book_id: str):
        pass

    def resolve_bets(self, last_fight: dict):
        for book in self.books:
            book.resolve_book(report_data=self.wcl_report, last_fight=last_fight)


# testing = Table(BackgroundScheduler(), DBController(), WCLController(), "KBv2cyzJn1mAwfbV")
