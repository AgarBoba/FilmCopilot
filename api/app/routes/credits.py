"""Credits (积分, simulated): balance and recent changes, and a manual top-up for now."""
from fastapi import APIRouter, Request
from pydantic import BaseModel

from ..credits import Credits

router = APIRouter(prefix='/api/credits')


class TopUp(BaseModel):
    amount: int


@router.get('')
def get_credits(request: Request) -> dict:
    return Credits(request.app.state.database).summary()


@router.post('/top-up')
def top_up(body: TopUp, request: Request) -> dict:
    credits = Credits(request.app.state.database)
    credits.top_up(body.amount)
    return credits.summary()
