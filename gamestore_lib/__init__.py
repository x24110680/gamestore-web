"""
gamestore_lib package

This package acts as a reusable utility library for the Game Store project.
It contains helper functions for cart logic, currency formatting, and can be
expanded later to include logging, validation, AWS integrations, etc.

The purpose of this __init__.py file is to expose selected functions so they
can be imported directly from gamestore_lib without referencing submodules.
Example:
    from gamestore_lib import calculate_cart_total, format_eur
"""

# Expose cart helper functions
from .cart_utils import calculate_cart_total, cart_item_count

# Expose currency formatting helpers
from .currency import format_eur

from .storage_s3 import upload_game_image

from .aws_events import send_order_event_to_sqs, notify_order_via_sns