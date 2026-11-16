"""Mixin that lets a device publish update notifications to subscribers."""

from collections.abc import Callable
import logging

_LOGGER = logging.getLogger(__name__)


class CallbacksMixin:
    """Adds subscribe/unsubscribe/publish support for update callbacks."""

    __slots__ = ["_callbacks"]

    def _setup_callbacks(self) -> None:
        """Initialize the set of registered callbacks."""
        self._callbacks: set[Callable[[], None]] = set()

    def register_callback(self, callback: Callable[[], None]) -> None:
        """Register a callback to be invoked on each update."""
        if not hasattr(self, "_callbacks"):
            self._setup_callbacks()
        self._callbacks.add(callback)

    def remove_callback(self, callback: Callable[[], None]) -> None:
        """Remove a previously registered callback."""
        if not hasattr(self, "_callbacks"):
            self._setup_callbacks()
        self._callbacks.discard(callback)

    def publish_updates(self) -> None:
        """Invoke every registered callback."""
        if not hasattr(self, "_callbacks"):
            self._setup_callbacks()
        _LOGGER.debug("%s publishing updates", id(self))
        for callback in self._callbacks:
            callback()
