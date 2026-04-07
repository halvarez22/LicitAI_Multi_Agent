from typing import List, Optional, Dict
from app.api.schemas.feedback import FeedbackCreate, FeedbackRead
from app.memory.factory import MemoryAdapterFactory
import logging

logger = logging.getLogger(__name__)

class FeedbackService:
    def __init__(self):
        self.repo = None

    async def _get_repo(self):
        if not self.repo:
            self.repo = MemoryAdapterFactory.create_adapter()
            await self.repo.connect()
        return self.repo

    async def submit_feedback(self, entry: FeedbackCreate) -> Dict:
        repo = await self._get_repo()
        try:
            data = entry.model_dump()
            success = await repo.save_feedback(data)
            if success:
                logger.info(f"feedback_submitted: session_id={entry.session_id}, agent_id={entry.agent_id}")
                return {"success": True, "message": "Feedback enviado exitosamente"}
            return {"success": False, "message": "Error al persistir feedback"}
        except Exception as e:
            logger.error(f"error_submitting_feedback: {e}")
            raise

    async def list_feedback_for_session(self, session_id: str) -> List[Dict]:
        repo = await self._get_repo()
        try:
            return await repo.get_feedback(session_id=session_id)
        except Exception as e:
            logger.error(f"error_listing_feedback: {e}")
            return []

    async def list_feedback_for_company(self, company_id: str) -> List[Dict]:
        repo = await self._get_repo()
        try:
            return await repo.get_feedback(company_id=company_id)
        except Exception as e:
            logger.error(f"error_listing_feedback_company: {e}")
            return []

    async def disconnect(self):
        if self.repo:
            await self.repo.disconnect()
            self.repo = None
