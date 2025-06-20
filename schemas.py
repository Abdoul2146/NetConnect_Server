from pydantic import BaseModel

class UserOut(BaseModel):
    id: int
    username: str
    name: str

    class Config:
        orm_mode = True
