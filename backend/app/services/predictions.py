import asyncio
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload, selectinload

from app.core.config import get_settings
from app.integrations.batru_client import BatruClient
from app.integrations.batru_errors import BatruTemporaryError
from app.integrations.batru_hero_mapper import BatruHeroMapper, UnmappedBatruHeroError
from app.integrations.interfaces import (
    BatruClient as BatruClientProtocol,
    Draft as BatruDraft,
    DraftPrediction,
)
from app.models import Draft, DraftPick, Hero, Prediction
from app.services.draft_completion import is_draft_complete


class PredictionServiceError(Exception):
    """Base error for prediction service operations."""


class DraftNotFoundError(PredictionServiceError):
    pass


class InvalidDraftError(PredictionServiceError):
    pass


class HeroMappingError(PredictionServiceError):
    pass


class PredictionResponseError(PredictionServiceError):
    pass


class PredictionService:
    def __init__(
        self,
        session: AsyncSession,
        batru_client: BatruClientProtocol,
        *,
        model_name: str = "default",
        max_retries: int = 2,
        retry_backoff_seconds: float = 0.5,
    ) -> None:
        if not model_name.strip():
            raise ValueError("model_name must not be empty.")
        if not 0 <= max_retries <= 5:
            raise ValueError("max_retries must be between 0 and 5.")
        if retry_backoff_seconds < 0:
            raise ValueError("retry_backoff_seconds must not be negative.")
        self.session = session
        self.batru_client = batru_client
        self.model_name = model_name
        self.max_retries = max_retries
        self.retry_backoff_seconds = retry_backoff_seconds

    @classmethod
    def from_settings(cls, session: AsyncSession) -> "PredictionService":
        settings = get_settings()
        client = BatruClient(
            base_url=settings.batru_base_url,
            timeout_seconds=settings.batru_timeout_seconds,
        )
        return cls(
            session,
            client,
            model_name=settings.prediction_model_name,
            max_retries=settings.batru_max_retries,
            retry_backoff_seconds=settings.batru_retry_backoff_seconds,
        )

    async def predict_draft(self, draft_id: UUID) -> Prediction:
        async with self.session.begin():
            result = await self.session.execute(
                select(Draft)
                .where(Draft.id == draft_id)
                .options(
                    selectinload(Draft.picks)
                    .joinedload(DraftPick.hero)
                    .joinedload(Hero.batru_mapping),
                    joinedload(Draft.match_game),
                )
                .with_for_update(of=Draft)
            )
            draft = result.scalar_one_or_none()
            if draft is None:
                raise DraftNotFoundError("Draft not found.")

            existing = await self.session.scalar(
                select(Prediction).where(
                    Prediction.draft_id == draft.id,
                    Prediction.model_name == self.model_name,
                )
            )
            if existing is not None:
                return existing

            _validate_lineup(draft.picks)
            if not is_draft_complete(draft.picks):
                raise InvalidDraftError(
                    "A complete draft must contain valid canonical heroes."
                )
            try:
                batru_draft = BatruHeroMapper.to_batru_draft(draft.picks)
            except UnmappedBatruHeroError as exc:
                raise HeroMappingError(str(exc)) from exc
            except ValueError as exc:
                raise InvalidDraftError(str(exc)) from exc

        forecast = await self._request_prediction(batru_draft)
        _validate_probabilities(forecast.radiant_probability, forecast.dire_probability)

        async with self.session.begin():
            existing = await self.session.scalar(
                select(Prediction).where(
                    Prediction.draft_id == draft_id,
                    Prediction.model_name == self.model_name,
                )
            )
            if existing is not None:
                return existing
            prediction = Prediction(
                draft_id=draft_id,
                model_name=self.model_name,
                radiant_probability=forecast.radiant_probability,
                dire_probability=forecast.dire_probability,
            )
            self.session.add(prediction)
            await self.session.flush()
            return prediction

    async def _request_prediction(self, draft: BatruDraft) -> DraftPrediction:
        for attempt in range(self.max_retries + 1):
            try:
                return await self.batru_client.predict_draft(draft)
            except BatruTemporaryError as exc:
                if attempt >= self.max_retries:
                    raise
                backoff = self.retry_backoff_seconds * (2**attempt)
                retry_after = getattr(exc, "retry_after", None) or 0.0
                delay = min(max(backoff, retry_after), 30.0)
                await asyncio.sleep(delay)
        raise RuntimeError("Prediction retry loop exited unexpectedly.")


def _validate_lineup(picks: list[DraftPick]) -> None:
    if len(picks) != 10:
        raise InvalidDraftError("A completed draft must contain exactly 10 picks.")

    radiant = [pick for pick in picks if pick.side == "radiant"]
    dire = [pick for pick in picks if pick.side == "dire"]
    if len(radiant) != 5 or len(dire) != 5:
        raise InvalidDraftError("A completed draft must contain exactly five heroes per side.")
    if len({pick.hero_id for pick in picks}) != 10:
        raise InvalidDraftError("A completed draft must contain 10 unique heroes.")
    valid_positions = {"pos_1", "pos_2", "pos_3", "pos_4", "pos_5", "unknown"}
    if any(pick.position not in valid_positions for pick in picks):
        raise InvalidDraftError("A draft pick contains an unsupported position.")


def _validate_probabilities(radiant: Decimal, dire: Decimal) -> None:
    if not radiant.is_finite() or not dire.is_finite():
        raise PredictionResponseError("Batru probabilities must be finite values.")
    if not (Decimal(0) <= radiant <= Decimal(1)):
        raise PredictionResponseError("Radiant probability must be between 0 and 1.")
    if not (Decimal(0) <= dire <= Decimal(1)):
        raise PredictionResponseError("Dire probability must be between 0 and 1.")
    if abs((radiant + dire) - Decimal(1)) > Decimal("0.0002"):
        raise PredictionResponseError("Batru probabilities are inconsistent.")
