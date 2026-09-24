"""The model registry for the canvas: which models exist, their parameters, and whether their
provider key is set (names of missing settings only, never values)."""
from fastapi import APIRouter

from ..models_registry import registry
from ..providers import has_adapter, missing_env

router = APIRouter(prefix='/api')


@router.get('/models')
def list_models() -> dict:
    models = registry()
    return {
        'models': [
            {**spec.public(), 'providerReady': has_adapter(spec.provider), 'missingEnv': missing_env(spec.provider)}
            for spec in models.all()
        ],
        # Problems in models/*.json, so a broken file doesn't silently disappear.
        'errors': models.errors,
    }
