"""The model registry for the canvas: which models exist, their parameters, and whether their
provider key is set (names of missing settings only, never values). Also each model's guide
(models/<id>.md) for the read-only viewer next to the credits button."""
from fastapi import APIRouter, HTTPException, Request

from ..models_registry import registry
from ..providers import errors as provider_errors
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


@router.get('/models/capabilities')
def capabilities() -> dict:
    """The capability word list (models/_capabilities.md)."""
    models = registry()
    return {
        'markdown': models.capabilities_text(),
        'capabilities': [
            {'name': item.name, 'meaning': item.meaning, 'tips': item.tips}
            for item in models.capabilities().values()
        ],
    }


@router.get('/models/{model_id}/guide')
def model_guide(model_id: str, request: Request) -> dict:
    models = registry()
    spec = models.get(model_id)
    if spec is None:
        raise HTTPException(status_code=404, detail=f'没有叫 {model_id} 的模型')
    vocabulary = models.capabilities()
    prefix = f'models/{spec.id}.'
    return {
        'id': spec.id,
        'label': spec.label,
        'kind': spec.kind,
        'family': spec.family or spec.id,
        'siblings': [other.id for other in models.family_of(spec)],
        'capabilities': [
            {'name': word, 'meaning': vocabulary[word].meaning if word in vocabulary else ''}
            for word in spec.capabilities
        ],
        'checks': spec.checks_text(),
        'markdown': spec.guide.text if spec.guide else None,
        'skill': spec.guide.skill if spec.guide else None,
        'files': {'json': f'models/{spec.id}.json', 'guide': f'models/{spec.id}.md'},
        'errors': [error for error in models.errors if error.startswith(prefix)],
        'rejections': provider_errors.recent(request.app.state.database, spec.id),
    }
