"""Lambda entry point.

Mangum translates API Gateway HTTP API (payload format 2.0) events into ASGI
calls, so the same FastAPI app serves both `uvicorn` locally and Lambda in the
deployed stack. No branching in application code.
"""
from mangum import Mangum

from app.main import app

handler = Mangum(app, lifespan="off")
