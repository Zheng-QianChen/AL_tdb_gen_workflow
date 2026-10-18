"""Compatibility entry point for the unified application server."""
from app import app, serve

if __name__ == "__main__":
    serve()
