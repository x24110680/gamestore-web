def calculate_cart_total(cart: dict) -> float:
    """
    Calculate the total value of a cart.
    """
    total = 0.0
    for item in cart.values():
        total += float(item["price"]) * int(item["quantity"])
    return total


def cart_item_count(cart: dict) -> int:
    """
    Count total number of items in a cart.
    """
    return sum(int(item["quantity"]) for item in cart.values())