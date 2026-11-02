def join(a, b):
    """Relative paths with /, either part may be empty."""
    return f"{a}/{b}" if a and b else a or b


def human(n):
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
