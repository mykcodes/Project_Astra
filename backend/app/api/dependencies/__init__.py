"""
ASTRA FastAPI Dependencies

Future home for:
- Authentication dependencies (get_current_user)
- Service injection
- Request validation
- Permission checking
"""

from app.database.session import get_db_session

__all__ = ["get_db_session"]
