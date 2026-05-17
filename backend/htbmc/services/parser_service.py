import re
from typing import Any


def extract_ipv4(text: str) -> list[str]:
    return sorted(set(re.findall(r"\b(?:\d{1,3}\.){3}\d{1,3}\b", text)))


def summarize_output(output: str, max_len: int = 400) -> str:
    cleaned = " ".join(output.split())
    return cleaned[:max_len]
