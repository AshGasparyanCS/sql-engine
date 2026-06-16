"""Small demo dataset used by the CLI and tests."""
from .engine import Database


def load_demo(db: Database) -> None:
    db.create_table("users", ["id", "name", "age"], [
        {"id": 1, "name": "ada", "age": 36},
        {"id": 2, "name": "linus", "age": 54},
        {"id": 3, "name": "grace", "age": 41},
        {"id": 4, "name": "alan", "age": 41},
    ])
    db.create_table("orders", ["id", "user_id", "amount"], [
        {"id": 10, "user_id": 1, "amount": 50},
        {"id": 11, "user_id": 1, "amount": 20},
        {"id": 12, "user_id": 2, "amount": 99},
        {"id": 13, "user_id": 3, "amount": 5},
        {"id": 14, "user_id": 1, "amount": 30},
    ])
