"""Services layer — orchestrates rag modules around HTTP-shape concerns.

See design.md Module Layout §"Architecture".
"""

from backend.services import ingest_service, chat_service, health_service

__all__ = ["ingest_service", "chat_service", "health_service"]
