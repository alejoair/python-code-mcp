"""Utilidades compartidas."""

import re


def validate_email(email: str) -> bool:
    """Valida que un string tenga formato de email."""
    pattern = r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$"
    return bool(re.match(pattern, email))


def format_currency(amount: float) -> str:
    """Formatea un número como moneda."""
    return f"${amount:,.2f}"


def slugify(text: str) -> str:
    """Convierte texto en slug."""
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
