import hashlib
from pathlib import Path
from typing import BinaryIO
from uuid import uuid4

from .config import Settings
from .db import Database
from .domain import DomainError
from .media_metadata import MediaMetadata, read_image_metadata, read_video_metadata
from .repositories import CanvasRepository
from .schemas import AssetRecord


_MEDIA_TYPES: dict[str, tuple[str, set[str]]] = {
    'image/png': ('image', {'.png'}),
    'image/jpeg': ('image', {'.jpg', '.jpeg'}),
    'image/webp': ('image', {'.webp'}),
    'video/mp4': ('video', {'.mp4'}),
    'video/webm': ('video', {'.webm'}),
    'video/quicktime': ('video', {'.mov'}),
}


class AssetService:
    def __init__(self, settings: Settings, database: Database, repository: CanvasRepository) -> None:
        self.settings = settings
        self.database = database
        self.repository = repository

    def save_upload(
        self,
        canvas_id: str,
        filename: str,
        content_type: str | None,
        stream: BinaryIO,
    ) -> AssetRecord:
        self.repository.assert_canvas(canvas_id)
        media_type = _MEDIA_TYPES.get(content_type or '')
        extension = Path(filename).suffix.lower()
        if media_type is None or extension not in media_type[1]:
            raise DomainError(
                'UNSUPPORTED_MEDIA_TYPE',
                'Supported uploads are PNG, JPEG, WebP, MP4, WebM and MOV',
            )

        asset_id = str(uuid4())
        asset_directory = self.settings.data_dir / 'assets' / asset_id
        asset_directory.mkdir(parents=True, exist_ok=False)
        path = asset_directory / f'original{extension}'
        checksum = hashlib.sha256()
        with path.open('wb') as output:
            while chunk := stream.read(1024 * 1024):
                checksum.update(chunk)
                output.write(chunk)

        try:
            metadata = (
                read_image_metadata(path)
                if media_type[0] == 'image'
                else read_video_metadata(path)
            )
        except Exception:
            path.unlink(missing_ok=True)
            asset_directory.rmdir()
            raise

        record = AssetRecord(
            id=asset_id,
            canvasId=canvas_id,
            kind=media_type[0],
            path=str(path),
            originalName=Path(filename).name,
            mimeType=metadata.mime_type if media_type[0] == 'image' else content_type or metadata.mime_type,
            width=metadata.width,
            height=metadata.height,
            durationSeconds=metadata.duration_seconds,
            checksum=checksum.hexdigest(),
        )
        with self.database.transaction() as connection:
            connection.execute(
                '''
                INSERT INTO assets (
                    id, canvas_id, kind, path, original_name, mime_type, width, height,
                    duration_seconds, checksum, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''',
                (
                    record.id,
                    record.canvasId,
                    record.kind,
                    record.path,
                    record.originalName,
                    record.mimeType,
                    record.width,
                    record.height,
                    record.durationSeconds,
                    record.checksum,
                    '{}',
                ),
            )
        return record

    def get_asset(self, asset_id: str) -> AssetRecord:
        with self.database.connection() as connection:
            row = connection.execute(
                '''
                SELECT id, canvas_id, kind, path, original_name, mime_type, width, height,
                       duration_seconds, checksum
                FROM assets WHERE id = ?
                ''',
                (asset_id,),
            ).fetchone()
        if row is None:
            raise DomainError('NOT_FOUND', f'Asset {asset_id} was not found')
        return AssetRecord(
            id=row['id'],
            canvasId=row['canvas_id'],
            kind=row['kind'],
            path=row['path'],
            originalName=row['original_name'],
            mimeType=row['mime_type'],
            width=row['width'],
            height=row['height'],
            durationSeconds=row['duration_seconds'],
            checksum=row['checksum'],
        )
