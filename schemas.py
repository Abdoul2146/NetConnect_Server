from pydantic import BaseModel

class UserOut(BaseModel):
    id: int
    username: str
    name: str

    class Config:
        orm_mode = True

class UserProfile(BaseModel):
    id: int
    name: str
    avatar_url: str | None = None
    job_title: str | None = None
    email: str | None = None
    contact: str | None = None

    class Config:
        orm_mode = True
