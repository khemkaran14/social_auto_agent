from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.user import User

router = APIRouter(prefix="/users", tags=["users"])


class CreateUserRequest(BaseModel):
    email: EmailStr


class UserResponse(BaseModel):
    id: int
    email: str
    api_key: str

    class Config:
        from_attributes = True


@router.post("", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def create_user(payload: CreateUserRequest, db: Session = Depends(get_db)) -> User:
    if db.query(User).filter(User.email == payload.email).first():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered")
    user = User(email=payload.email)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user
