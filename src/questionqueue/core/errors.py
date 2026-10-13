class QuestionQueueError(Exception):
    """Base for every error the core raises."""


class QuestionNotFound(QuestionQueueError, KeyError):
    def __init__(self, question_id: str) -> None:
        super().__init__(question_id)
        self.question_id = question_id

    def __str__(self) -> str:
        return f"no question with id {self.question_id!r}"


class InvalidMove(QuestionQueueError, ValueError):
    """A move that would put a question inside itself, or has nowhere to go."""


class ExternalChange(QuestionQueueError):
    """The file changed on disk since it was last loaded or saved."""
