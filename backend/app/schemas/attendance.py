import uuid
from datetime import date

from pydantic import BaseModel


class AttendanceTotals(BaseModel):
    present: int = 0
    absent: int = 0
    apology: int = 0
    unknown: int = 0


class AttendanceCommitteeBreakdown(BaseModel):
    committee_id: uuid.UUID | None = None
    committee_name: str | None = None
    present: int = 0
    absent: int = 0
    apology: int = 0
    unknown: int = 0
    total: int = 0


class AttendanceRecentMeeting(BaseModel):
    meeting_id: uuid.UUID
    meeting_title: str
    meeting_date: date | None = None
    committee_name: str | None = None
    attendance_status: str
    source_url: str | None = None


class PoliticianAttendanceRead(BaseModel):
    totals: AttendanceTotals
    recorded_meetings: int
    by_committee: list[AttendanceCommitteeBreakdown]
    recent: list[AttendanceRecentMeeting]
