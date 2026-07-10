import pytest
from pydantic import ValidationError

from pprouter.schemas import ChatRequest, MAX_MESSAGES, MAX_TOTAL_MESSAGE_CHARS


def test_chat_request_requires_exactly_one_input_shape() -> None:
    with pytest.raises(ValidationError):
        ChatRequest()
    with pytest.raises(ValidationError):
        ChatRequest(query="hi", messages=[{"role": "user", "content": "hi"}])


def test_chat_request_requires_user_message() -> None:
    with pytest.raises(ValidationError):
        ChatRequest(messages=[{"role": "system", "content": "system"}])


def test_chat_request_limits_count_and_total_content() -> None:
    with pytest.raises(ValidationError):
        ChatRequest(
            messages=[{"role": "user", "content": "x"}] * (MAX_MESSAGES + 1)
        )
    with pytest.raises(ValidationError):
        ChatRequest(
            messages=[
                {"role": "user", "content": "x" * 20_000},
                {"role": "assistant", "content": "x" * 20_000},
                {"role": "user", "content": "x" * 20_000},
                {"role": "assistant", "content": "x"},
            ]
        )
    assert MAX_TOTAL_MESSAGE_CHARS == 60_000
