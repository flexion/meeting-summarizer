"""Base class for Zoom page objects."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from playwright.sync_api import ElementHandle, Page


class BasePage:
    """Base class for all Zoom page objects.

    Provides common functionality for page interactions.
    """

    def __init__(self, page: Page, timeout_ms: int = 30000) -> None:
        """Initialize the page object.

        Args:
            page: Playwright page instance
            timeout_ms: Default timeout for element operations
        """
        self.page = page
        self.timeout_ms = timeout_ms

    def query_visible(self, selector: str) -> ElementHandle | None:
        """Query for a visible element.

        Args:
            selector: CSS selector

        Returns:
            Element if found and visible, None otherwise
        """
        try:
            element = self.page.query_selector(selector)
            if element and element.is_visible():
                return element
        except Exception:
            pass
        return None

    def is_element_visible(self, selector: str) -> bool:
        """Check if an element is visible.

        Args:
            selector: CSS selector

        Returns:
            True if element is visible
        """
        return self.query_visible(selector) is not None
