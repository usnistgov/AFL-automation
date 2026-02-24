"""Mock EIC client for testing and mock_mode."""
import warnings


class MockEICClient:
    """Minimal mock EIC client for testing and mock_mode."""

    def __init__(self, *args, **kwargs):
        warnings.warn("EICClient not available - using mock client", stacklevel=2)

    def get_pv(self, *args, **kwargs):
        return True, None, "mock"

    def set_pv(self, *args, **kwargs):
        return True, "mock"

    def submit_table_scan(self, *args, **kwargs):
        return True, "mock_scan", "mock"

    def get_scan_status(self, *args, **kwargs):
        return True, True, "done", "mock"
