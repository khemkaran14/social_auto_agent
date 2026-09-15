from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import get_owned_social_account
from app.database import get_db
from app.models.niche import Niche
from app.models.social_account import SocialAccount

router = APIRouter(prefix="/social-accounts/{social_account_id}/niche", tags=["niches"])


class NicheRequest(BaseModel):
    name: str
    description: str
    tone: str = "professional"
    content_pillars: list[str] = []
    keywords: list[str] = []


class NicheResponse(NicheRequest):
    id: int

    class Config:
        from_attributes = True


@router.get("", response_model=NicheResponse | None)
def get_niche(account: SocialAccount = Depends(get_owned_social_account)) -> Niche | None:
    return account.niche


@router.put("", response_model=NicheResponse)
def upsert_niche(
    payload: NicheRequest,
    account: SocialAccount = Depends(get_owned_social_account),
    db: Session = Depends(get_db),
) -> Niche:
    niche = account.niche
    if niche is None:
        niche = Niche(social_account_id=account.id)
        db.add(niche)

    niche.name = payload.name
    niche.description = payload.description
    niche.tone = payload.tone
    niche.content_pillars = payload.content_pillars
    niche.keywords = payload.keywords
    db.commit()
    db.refresh(niche)
    return niche
