"""Forge extension entry point; the host's Python modules are left untouched."""
import sys
from pathlib import Path
from urllib.parse import urlparse

from fastapi import Depends, HTTPException, Request
from pydantic import BaseModel, Field
from modules import script_callbacks

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from lora_facets_core import Catalog


def provider():
    import networks
    return [(name, item.filename) for name, item in list(networks.available_networks.items())]


catalog = Catalog(ROOT / 'data' / 'catalog.json', provider)


class Edit(BaseModel):
    id: str
    genres: list[str] = Field(default_factory=list, max_length=30)
    tags: list[str] = Field(default_factory=list, max_length=1000)
    reset: bool = False


class Sync(BaseModel):
    ids: list[str] | None = None


def guard(request: Request):
    # A custom header prevents cross-site form/image requests, including reads.
    if request.headers.get('x-lora-facets') != '1':
        raise HTTPException(403, 'LoRA Facets header required')
    origin = request.headers.get('origin')
    if origin and urlparse(origin).netloc != request.headers.get('host'):
        raise HTTPException(403, 'Same-origin requests only')


def register(_demo, app):
    kwargs = {'dependencies': [Depends(guard)]}

    @app.get('/lora-facets/catalog', **kwargs)
    def get_catalog():
        return catalog.snapshot() if catalog.records else catalog.scan()

    @app.post('/lora-facets/rescan', **kwargs)
    def rescan():
        return catalog.scan()

    @app.post('/lora-facets/edit', **kwargs)
    def edit(body: Edit):
        try:
            return catalog.edit(body.id, body.genres, body.tags, body.reset)
        except KeyError:
            raise HTTPException(404, 'LoRAが見つかりません。再読込してください')
        except ValueError as exc:
            raise HTTPException(400, str(exc))

    @app.post('/lora-facets/sync', **kwargs)
    def sync(body: Sync):
        try:
            return catalog.start(body.ids)
        except ValueError as exc:
            raise HTTPException(400, str(exc))

    @app.post('/lora-facets/stop', **kwargs)
    def stop():
        catalog.stop.set()
        return {'ok': True}


script_callbacks.on_app_started(register)
