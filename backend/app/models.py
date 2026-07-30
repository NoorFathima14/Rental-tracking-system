from pydantic import BaseModel

class HealthResponse(BaseModel):
    status: str
    rows_loaded: int