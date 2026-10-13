class QuestionQueueError(Exception):
    """Base for every error the core raises."""


class ItemNotFound(QuestionQueueError, KeyError):
    def __init__(self, item_id: str) -> None:
        super().__init__(item_id)
        self.item_id = item_id

    def __str__(self) -> str:
        return f"no item with id {self.item_id!r}"


class InvalidMove(QuestionQueueError, ValueError):
    """A move that would put an item inside itself, or has nowhere to go."""


class ExternalChange(QuestionQueueError):
    """The file changed on disk since it was last loaded or saved."""
