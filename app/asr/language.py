from .config import ASRConfig
from .types import RATE
from app.languages import SOURCE_LANGUAGES


class LanguagePolicy:
    """Fixed language or session lock after spaced, consistent auto detections.

    Once locked it does not flip due to a short foreign term. Restart to reset.
    Language scores are model outputs, not calibrated correctness probabilities.
    """
    def __init__(self, config: ASRConfig):
        self.config = config
        self.locked = None if config.language == "auto" else config.language
        self.candidate = None
        self.votes = 0
        self.last_vote_end = -RATE

    def observe(self, language: str, probability: float, end: int) -> bool:
        if self.locked or end - self.last_vote_end < RATE:
            return False
        self.last_vote_end = end
        if language not in SOURCE_LANGUAGES or probability < self.config.language_probability_min:
            self.votes = 0
            self.candidate = None
            return False
        if language == self.candidate:
            self.votes += 1
        else:
            self.candidate, self.votes = language, 1
        if self.votes >= self.config.language_lock_votes:
            self.locked = language
            return True
        return False
