"""
ASTRA Repository Pattern Base

Provides a base generic class for data access repositories, ensuring
all CRUD operations share a consistent interface.
"""

from typing import Generic, TypeVar, Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, delete
from sqlalchemy.engine.result import Result

from app.models.base import Base

ModelType = TypeVar("ModelType", bound=Base)


class BaseRepository(Generic[ModelType]):
    """Generic base repository for basic CRUD operations."""

    def __init__(self, model: type[ModelType], session: AsyncSession):
        self.model = model
        self.session = session

    async def get(self, id: Any) -> ModelType | None:
        """Get a single record by ID."""
        result: Result = await self.session.execute(
            select(self.model).filter(self.model.id == id)
        )
        return result.scalars().first()

    async def get_all(self, skip: int = 0, limit: int = 100) -> list[ModelType]:
        """Get a list of records with pagination."""
        result: Result = await self.session.execute(
            select(self.model).offset(skip).limit(limit)
        )
        return list(result.scalars().all())

    async def create(self, obj_in: dict[str, Any] | ModelType) -> ModelType:
        """Create a new record."""
        obj_data = obj_in if isinstance(obj_in, dict) else obj_in.__dict__
        # Clean up SQLAlchemy internal state if passing an object directly
        obj_data = {k: v for k, v in obj_data.items() if not k.startswith("_")}
        
        db_obj = self.model(**obj_data)
        self.session.add(db_obj)
        await self.session.flush()
        await self.session.refresh(db_obj)
        return db_obj

    async def update(self, db_obj: ModelType, obj_in: dict[str, Any]) -> ModelType:
        """Update an existing record."""
        for field in obj_in:
            if hasattr(db_obj, field):
                setattr(db_obj, field, obj_in[field])
        
        self.session.add(db_obj)
        await self.session.flush()
        await self.session.refresh(db_obj)
        return db_obj

    async def delete(self, id: Any) -> bool:
        """Delete a record by ID."""
        result = await self.session.execute(
            delete(self.model).filter(self.model.id == id)
        )
        await self.session.flush()
        return result.rowcount > 0
