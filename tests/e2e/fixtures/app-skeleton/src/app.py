"""Minimal backend the harness lets Claude extend."""


def health() -> dict:
    return {"status": "ok"}
