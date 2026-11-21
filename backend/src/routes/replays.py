import json
from fastapi import APIRouter, Depends
from fastapi.responses import Response
from src.config.database import get_db
from src.middlewares.auth import current_user, writable
from src.schemas.replay import ReplayInput
from src.services.replay_service import (
    list_replays, get_replay, create_replay, pause_lane, resume_lane, retry_replay,
    record_with_shards,
)
from src.controllers.actions import audit
router = APIRouter()

@router.get('/replays')
def listing(db=Depends(get_db), user=Depends(current_user)):
    return list_replays(db)

@router.post('/replays', status_code=202)
def create(data: ReplayInput, db=Depends(get_db), user=Depends(writable)):
    obj = create_replay(db, data)
    audit(db, user, f'replay:enqueue:{obj.id}')
    db.commit()
    return record_with_shards(obj)

@router.get('/replays/{ident}')
def detail(ident: int, db=Depends(get_db), user=Depends(current_user)):
    return record_with_shards(get_replay(db, ident))

@router.post('/replays/{ident}/lanes/{lane}/pause', status_code=200)
def pause(ident: int, lane: str, db=Depends(get_db), user=Depends(writable)):
    obj = pause_lane(db, ident, lane)
    audit(db, user, f'replay:pause:{ident}:{lane}')
    db.commit()
    return record_with_shards(obj)

@router.post('/replays/{ident}/lanes/{lane}/resume', status_code=200)
def resume(ident: int, lane: str, db=Depends(get_db), user=Depends(writable)):
    obj = resume_lane(db, ident, lane)
    audit(db, user, f'replay:resume:{ident}:{lane}')
    db.commit()
    return record_with_shards(obj)

@router.post('/replays/{ident}/retry', status_code=200)
def retry(ident: int, db=Depends(get_db), user=Depends(writable)):
    obj = retry_replay(db, ident)
    audit(db, user, f'replay:retry:{ident}')
    db.commit()
    return record_with_shards(obj)

@router.get('/replays/{ident}/export')
def export(ident: int, db=Depends(get_db), user=Depends(current_user)):
    obj = record_with_shards(get_replay(db, ident))
    return Response(json.dumps(obj, ensure_ascii=False, indent=2), media_type='application/json',
                    headers={'Content-Disposition': f'attachment; filename="replay-{ident}.json"'})
