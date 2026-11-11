"""Approval channels: how a proposal reaches the operator and how an authenticated decision comes back."""
from .base import ApprovalChannel  # noqa: F401
from .cli import CliChannel  # noqa: F401
from .telegram import TelegramChannel  # noqa: F401
