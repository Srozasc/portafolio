"""Services layer — orchestrates rag modules around HTTP-shape concerns.

See design.md Module Layout §"Architecture".
"""

from backend.services import chat_service, health_service, ingest_service

__all__ = ["chat_service", "health_service", "ingest_service"]
