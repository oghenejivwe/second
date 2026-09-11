"""The HTTP layer. Owned by SURFACES; contains no business logic.

    from second.api.app import app          # uvicorn second.api.app:app

Nine routes, each a thin call into ``second.graphs.service`` plus serialisation.
"""

from second.api.app import create_app

__all__ = ["create_app"]
