import datetime
import uuid

from pydantic import BaseModel, ConfigDict


class BillRead(BaseModel):
    id: uuid.UUID
    title: str
    short_title: str | None = None
    bill_number: str | None = None
    year: int | None = None
    house: str | None = None
    status: str
    introduced_date: datetime.date | None = None
    passed_date: datetime.date | None = None
    assented_date: datetime.date | None = None
    act_number: str | None = None
    source_url: str | None = None
    source_type: str | None = None
    created_at: datetime.datetime
    updated_at: datetime.datetime

    model_config = ConfigDict(from_attributes=True)


class BillEventRead(BaseModel):
    id: uuid.UUID
    bill_id: uuid.UUID
    event_type: str
    event_date: datetime.date | None = None
    description: str | None = None
    committee_id: uuid.UUID | None = None
    document_id: uuid.UUID | None = None
    source_url: str | None = None
    created_at: datetime.datetime

    model_config = ConfigDict(from_attributes=True)


class VoteEventRead(BaseModel):
    id: uuid.UUID
    title: str
    date: datetime.date | None = None
    chamber: str | None = None
    vote_type: str
    result: str | None = None
    bill_id: uuid.UUID | None = None
    committee_id: uuid.UUID | None = None
    source_url: str | None = None
    source_type: str | None = None
    created_at: datetime.datetime
    updated_at: datetime.datetime

    model_config = ConfigDict(from_attributes=True)


class VoteRecordRead(BaseModel):
    id: uuid.UUID
    vote_event_id: uuid.UUID
    politician_id: uuid.UUID | None = None
    party_id: uuid.UUID | None = None
    vote_value: str
    record_level: str
    count: int | None = None
    confidence: str
    source_url: str | None = None
    created_at: datetime.datetime

    model_config = ConfigDict(from_attributes=True)


class CommitteeMeetingRead(BaseModel):
    id: uuid.UUID
    committee_id: uuid.UUID | None = None
    title: str
    date: datetime.date | None = None
    summary: str | None = None
    source_url: str | None = None
    pmg_url: str | None = None
    summary_document_id: uuid.UUID | None = None
    created_at: datetime.datetime
    updated_at: datetime.datetime

    model_config = ConfigDict(from_attributes=True)


class CommitteeAttendanceRead(BaseModel):
    id: uuid.UUID
    meeting_id: uuid.UUID
    politician_id: uuid.UUID | None = None
    name_raw: str
    party_id: uuid.UUID | None = None
    attendance_status: str
    confidence: float | None = None
    source_url: str | None = None
    created_at: datetime.datetime

    model_config = ConfigDict(from_attributes=True)
