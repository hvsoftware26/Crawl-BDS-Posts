# Scheduler service
from utils.time_utils import caclulate_next_run


class ScheduleService:
    def __init__(self):
        pass

    def build_posts_schedule(self, groups_count: int, cycle_time: int):
        if groups_count == 0:
            raise ValueError("Groups count must be greater than 0")
        delay_minutes = caclulate_next_run(groups_count, cycle_time)

        return {
            "delay_minutes": delay_minutes,
            "groups_count": groups_count,
        }
