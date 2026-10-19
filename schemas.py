import re
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


CONTACT_PATTERN = re.compile(r"^(?:[^\s@]+@[^\s@]+\.[^\s@]+|[+()\d][+()\d\s-]{6,24})$")


class RFPPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    company_name: str = Field(min_length=2, max_length=120)
    contact_name: str = Field(min_length=2, max_length=100)
    contact_info: str = Field(min_length=7, max_length=254)
    destination: str = Field(default="General Inquiry", min_length=2, max_length=120)
    pax_count: int = Field(default=100, ge=10, le=5000)
    notes: Optional[str] = Field(default=None, max_length=2000)

    # Qualifying fields added with the Phase 1 form upgrade. All optional, so an
    # older client that omits them still submits successfully — `extra="forbid"`
    # above means anything NOT declared here is rejected with a 422, which is
    # why new form inputs must be registered in this model.
    organisation_type: Optional[str] = Field(default=None, max_length=60)
    event_type: Optional[str] = Field(default=None, max_length=60)
    travel_window: Optional[str] = Field(default=None, max_length=120)

    @field_validator("company_name", "contact_name", "destination")
    @classmethod
    def reject_blank_or_control_text(cls, value: str):
        if not value.strip() or any(ord(character) < 32 for character in value):
            raise ValueError("must contain printable text")
        return value.strip()

    @field_validator("contact_info")
    @classmethod
    def validate_contact(cls, value: str):
        value = value.strip()
        if not CONTACT_PATTERN.fullmatch(value):
            raise ValueError("must be a valid email address or phone number")
        return value
