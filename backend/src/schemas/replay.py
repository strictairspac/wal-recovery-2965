from pydantic import BaseModel, Field
class ReplayInput(BaseModel):
    crash_case_id: int = Field(gt=0)
    label: str = Field(min_length=2, max_length=120)
