get_report_data = """
    query($reportCode: String) {
        reportData {
            report(code:$reportCode) {
                endTime
                startTime
                fights {
                    name
                    difficulty
                    kill
                    startTime
                    endTime
                    friendlyPlayers
                    inProgress
                    fightPercentage
                }
                masterData {
                    actors(type:"player") {
                        id
                        gameID
                        icon
                        name
                        server
                    }
                }
            }
        }
    }
"""

get_encounter_deaths = """
    query($reportCode: String, $startTime: Float, $endTime: Float) {
        reportData {
            report(code:$reportCode) {
                events(dataType:Deaths, startTime:$startTime, endTime:$endTime) {
                    data
                }
            }
        }
    }
"""