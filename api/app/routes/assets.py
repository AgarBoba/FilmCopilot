from fastapi import APIRouter, File, Form, Request, UploadFile, status
from fastapi.responses import FileResponse

from ..assets import AssetService
from ..config import resolve_project_path
from ..schemas import AssetRecord


router = APIRouter(prefix='/api')


@router.post('/assets/upload', response_model=AssetRecord, status_code=status.HTTP_201_CREATED)
def upload_asset(
    request: Request,
    canvasId: str = Form(...),
    file: UploadFile = File(...),
) -> AssetRecord:
    service: AssetService = request.app.state.asset_service
    return service.save_upload(canvasId, file.filename or 'upload', file.content_type, file.file)


@router.get('/assets/{asset_id}/file')
def get_asset_file(request: Request, asset_id: str) -> FileResponse:
    service: AssetService = request.app.state.asset_service
    asset = service.get_asset(asset_id)
    return FileResponse(resolve_project_path(asset.path), media_type=asset.mimeType, filename=asset.originalName)
