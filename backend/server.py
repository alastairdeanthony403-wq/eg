"""ASGI shim that mounts the Flask app — supervisor runs `uvicorn server:app`."""
from a2wsgi import WSGIMiddleware
from flask_app import app as flask_app

app = WSGIMiddleware(flask_app)
