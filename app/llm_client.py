"""Wraps the Gemini API calls the agent needs, behind a small interface so

`agent.py` doesn't care whether it's talking to the real API or the offline
mock used by tests / `evaluation/run_eval.py --mock`.

Two-call-per-turn design
------------------------

1. `decide_tool_call(...)` -- the model sees the conversation + the
   order_lookup tool declaration and either calls the tool or not. No
   structured-output schema is requested on this call.

2. `generate_structured_answer(...)` -- a second call, now with any tool
   result already folded into the contents and with `tools` removed, asking
   for the `AgentAnswer` JSON schema.

Production resilience
---------------------

- Transient provider failures are retried with bounded exponential backoff.
- Model-not-found/unavailable responses (including HTTP 404) can fail over
  to the next configured model.
- Primary model -> configured fallback model is deterministic.
- Routed model -> primary model -> configured fallback is deterministic.
- Automatic Function Calling (AFC) is explicitly disabled when supported by
  the installed Google GenAI SDK.
- Lightweight test doubles that do not expose AFC configuration remain
  supported.
- If every configured model is exhausted, `LLMAvailabilityError` is raised.
"""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass
from typing import Any, Protocol

from app import config
from app.orders import ORDER_LOOKUP_TOOL_SCHEMA
from app.schemas import AgentAnswer

logger = logging.getLogger("aster_row.llm")


# ============================================================
# Tool-call models
# ============================================================


@dataclass
class ToolCallRequest:
    name: str
    arguments: dict[str, Any]


@dataclass
class ToolDecision:
    tool_calls: list[ToolCallRequest]
    raw_text: str | None


# ============================================================
# Safe provider availability error
# ============================================================


class LLMAvailabilityError(RuntimeError):
    """Raised only after all configured provider attempts are exhausted.

    status_code=503 lets the web layer / agent recognize this as a
    temporary provider-availability problem without treating programming,
    authentication, validation, or other non-transient errors as transient.

    The message intentionally contains no API key and no provider response
    body.
    """

    status_code = 503

    def __init__(
        self,
        *,
        attempted_models: list[str],
        attempts: int,
        last_error: Exception | None = None,
    ):
        self.attempted_models = attempted_models
        self.attempts = attempts
        self.last_error = last_error

        super().__init__(
            "All configured LLM provider attempts were exhausted "
            f"after {attempts} attempt(s)."
        )


# ============================================================
# LLM interface
# ============================================================


class LLMClient(Protocol):
    def decide_tool_call(
        self,
        system_instruction: str,
        contents: list[dict],
    ) -> ToolDecision:
        ...

    def generate_structured_answer(
        self,
        system_instruction: str,
        contents: list[dict],
    ) -> AgentAnswer:
        ...


# ============================================================
# Gemini client
# ============================================================


class GeminiLLMClient:
    def __init__(
        self,
        api_key: str | None = None,
        model: str = config.CHAT_MODEL,
        fallback_model: str = config.CHAT_FALLBACK_MODEL,
    ):
        from google import genai

        self._client = genai.Client(
            api_key=api_key or config.GEMINI_API_KEY
        )

        self._model = model

        self._fallback_model = (
            fallback_model
            if fallback_model and fallback_model != model
            else None
        )

    # ========================================================
    # Error classification
    # ========================================================

    @staticmethod
    def _status_code_from_exception(
        exc: Exception,
    ) -> int | None:
        """Extract a provider HTTP/status code from SDK exceptions.

        Different Google SDK versions can expose the status in different
        attributes, so check the common locations defensively.
        """

        candidates = [
            getattr(exc, "status_code", None),
            getattr(exc, "code", None),
            getattr(exc, "http_status", None),
        ]

        response = getattr(exc, "response", None)

        if response is not None:
            candidates.extend(
                [
                    getattr(response, "status_code", None),
                    getattr(response, "code", None),
                ]
            )

        for value in candidates:
            try:
                if value is not None:
                    return int(value)
            except (TypeError, ValueError):
                continue

        return None

    @classmethod
    def _is_transient(
        cls,
        exc: Exception,
    ) -> bool:
        """Return whether an exception should trigger retry/failover.

        Supported retry/failover conditions:

        - 404: configured model unavailable / model not found
        - 408: request timeout
        - 429: rate limit / quota
        - 500: provider internal error
        - 502: bad gateway
        - 503: service unavailable
        - 504: gateway timeout

        Authentication, malformed requests, schema errors, programming
        errors, etc. remain non-transient and are not retried.
        """

        status = cls._status_code_from_exception(exc)

        return status in {
            404,
            408,
            429,
            500,
            502,
            503,
            504,
        }

    # ========================================================
    # Retry backoff
    # ========================================================

    @staticmethod
    def _sleep_before_retry(
        retry_number: int,
    ) -> None:
        delay = min(
            config.LLM_RETRY_MAX_DELAY_SECONDS,
            config.LLM_RETRY_INITIAL_DELAY_SECONDS
            * (2 ** max(0, retry_number - 1)),
        )

        if delay > 0:
            time.sleep(delay)

    # ========================================================
    # Model failover chain
    # ========================================================

    def _model_chain(
        self,
        requested_model: str,
    ) -> list[tuple[str, bool]]:
        """Build a deterministic, duplicate-free model failover chain.

        Normal configuration:

            primary -> fallback

        When the Model Router selects a different model:

            routed model -> primary -> fallback

        `is_fallback` is True for models reached after the first selected
        model. This information is used by the usage collector.
        """

        candidates: list[tuple[str, bool]] = []

        def add(
            model: str | None,
            is_fallback: bool,
        ) -> None:
            if not model:
                return

            existing_models = {
                existing_model
                for existing_model, _ in candidates
            }

            if model not in existing_models:
                candidates.append(
                    (
                        model,
                        is_fallback,
                    )
                )

        # First try the model selected by the router/configuration.
        add(
            requested_model,
            False,
        )

        # If the router selected a different model, preserve the configured
        # primary model as the next fallback.
        if requested_model != self._model:
            add(
                self._model,
                True,
            )

        # Finally try the configured secondary fallback model.
        add(
            self._fallback_model,
            True,
        )

        return candidates

    # ========================================================
    # Central Gemini request method
    # ========================================================

    def _generate_content(
        self,
        *,
        contents,
        config_kwargs,
    ):
        """Generate content with bounded retry + model failover.

        Resilience contract:

        1. Retry transient 404/408/429/5xx provider failures.
        2. Use bounded exponential backoff.
        3. After one model is exhausted, fail over to the next model.
        4. A routed model may fail non-transiently and still fall back to
           the configured primary model.
        5. The configured primary/fallback models fail fast on non-transient
           errors.
        6. If every configured model is exhausted, raise
           `LLMAvailabilityError`.

        AFC contract:

        Automatic Function Calling is explicitly disabled for every Gemini
        request when the installed SDK exposes
        `AutomaticFunctionCallingConfig`.

        The application executes tools itself. Gemini only returns
        tool-call decisions.

        Test compatibility:

        Some unit tests replace `google.genai.types` with a minimal
        test double. Such test doubles may not expose
        `AutomaticFunctionCallingConfig`.

        In that situation AFC configuration is omitted rather than causing
        the test itself to fail.
        """

        from google.genai import types

        from app.llm_usage import (
            model_override_var,
            usage_collector_var,
        )

        # Never mutate the caller's dictionary.
        request_config_kwargs = dict(config_kwargs)

        # ----------------------------------------------------
        # Disable Automatic Function Calling when available.
        # ----------------------------------------------------

        afc_config_cls = getattr(
            types,
            "AutomaticFunctionCallingConfig",
            None,
        )

        if afc_config_cls is not None:
            request_config_kwargs.setdefault(
                "automatic_function_calling",
                afc_config_cls(
                    disable=True,
                ),
            )

        request_config = types.GenerateContentConfig(
            **request_config_kwargs
        )

        # ----------------------------------------------------
        # Determine requested model.
        # ----------------------------------------------------

        requested = (
            model_override_var.get()
            or self._model
        )

        # A router override is any requested model different from the
        # configured primary model.
        #
        # This distinction is important:
        #
        #     routed model fails
        #          -> configured primary
        #
        # while:
        #
        #     configured primary fails with a non-transient error
        #          -> fail immediately
        #
        is_routed_request = requested != self._model

        collector = usage_collector_var.get()

        attempted_models: list[str] = []
        total_attempts = 0
        last_error: Exception | None = None

        model_chain = self._model_chain(
            requested,
        )

        # ----------------------------------------------------
        # Model loop
        # ----------------------------------------------------

        for index, (
            model,
            is_fallback,
        ) in enumerate(model_chain):

            attempted_models.append(model)

            # ------------------------------------------------
            # Retry loop for each model
            # ------------------------------------------------

            for attempt in range(
                1,
                config.LLM_MAX_ATTEMPTS_PER_MODEL + 1,
            ):
                total_attempts += 1

                if collector is not None:
                    collector.record_attempt(
                        model,
                        retry=attempt > 1,
                        fallback=is_fallback,
                    )

                try:
                    response = (
                        self._client.models.generate_content(
                            model=model,
                            contents=contents,
                            config=request_config,
                        )
                    )

                    if collector is not None:
                        collector.add(
                            model,
                            response,
                        )

                    return response

                except Exception as exc:
                    last_error = exc

                    status = (
                        self._status_code_from_exception(
                            exc,
                        )
                    )

                    # ----------------------------------------
                    # Non-transient error.
                    #
                    # Normally a non-transient error should fail
                    # immediately.
                    #
                    # EXCEPTION:
                    #
                    # A model selected by the router is an
                    # optimization, not a hard dependency.
                    #
                    # If that routed model fails, continue to the
                    # configured primary model.
                    #
                    # This gives us:
                    #
                    # routed model
                    #       ↓ failure
                    # configured primary
                    #       ↓ failure
                    # configured fallback
                    # ----------------------------------------

                    if not self._is_transient(exc):

                        if (
                            is_routed_request
                            and model == requested
                            and requested != self._model
                        ):
                            logger.warning(
                                "Non-transient routed LLM failure; "
                                "falling back to configured primary "
                                "model=%s configured_model=%s "
                                "status=%s error=%s",
                                model,
                                self._model,
                                status,
                                type(exc).__name__,
                            )

                            # Stop retrying this routed model and move
                            # directly to the next model in the chain.
                            break

                        # Non-transient failure on the configured model:
                        # preserve fail-fast behavior.
                        raise

                    # ----------------------------------------
                    # Transient error.
                    # ----------------------------------------

                    if collector is not None:
                        collector.transient_errors += 1

                    logger.warning(
                        "Transient LLM failure "
                        "model=%s attempt=%d/%d "
                        "fallback=%s status=%s error=%s",
                        model,
                        attempt,
                        config.LLM_MAX_ATTEMPTS_PER_MODEL,
                        is_fallback,
                        status,
                        type(exc).__name__,
                    )

                    # ----------------------------------------
                    # Retry same model if attempts remain.
                    # ----------------------------------------

                    if attempt < config.LLM_MAX_ATTEMPTS_PER_MODEL:
                        self._sleep_before_retry(
                            attempt,
                        )

            # ------------------------------------------------
            # Current model exhausted or intentionally skipped.
            # ------------------------------------------------

            if index < len(model_chain) - 1:
                next_model = model_chain[index + 1][0]

                logger.warning(
                    "LLM model exhausted "
                    "model=%s; attempting next "
                    "configured failover model=%s.",
                    model,
                    next_model,
                )

        # ----------------------------------------------------
        # Every configured model exhausted.
        # ----------------------------------------------------

        raise LLMAvailabilityError(
            attempted_models=attempted_models,
            attempts=total_attempts,
            last_error=last_error,
        )

    # ========================================================
    # Gemini content conversion
    # ========================================================

    def _to_genai_contents(
        self,
        contents: list[dict],
    ):
        """Convert internal conversation contents to Gemini Content objects.

        Gemini Content.role accepts `user` or `model`.

        Internal application roles such as:

        - assistant
        - tool
        - system_context

        are converted into application-side text content as appropriate.
        """

        from google.genai import types

        out = []

        for turn in contents:
            role = turn["role"]

            genai_role = (
                "model"
                if role in (
                    "assistant",
                    "model",
                )
                else "user"
            )

            out.append(
                types.Content(
                    role=genai_role,
                    parts=[
                        types.Part.from_text(
                            text=turn["text"]
                        )
                    ],
                )
            )

        return out

    # ========================================================
    # Tool decision
    # ========================================================

    def decide_tool_call(
        self,
        system_instruction: str,
        contents: list[dict],
    ) -> ToolDecision:
        """Ask Gemini whether an application-side tool should be called.

        AFC is centrally disabled inside `_generate_content`.

        Gemini only decides whether a tool call should be made. The
        application executes the returned ToolCallRequest.
        """

        from google.genai import types

        tool = types.Tool(
            function_declarations=[
                types.FunctionDeclaration(
                    **ORDER_LOOKUP_TOOL_SCHEMA
                )
            ]
        )

        response = self._generate_content(
            contents=self._to_genai_contents(
                contents
            ),
            config_kwargs={
                "system_instruction": system_instruction,
                "tools": [tool],
                "temperature": 0.1,
            },
        )

        calls = response.function_calls or []

        tool_calls = [
            ToolCallRequest(
                name=c.name,
                arguments=dict(
                    c.args or {}
                ),
            )
            for c in calls
        ]

        return ToolDecision(
            tool_calls=tool_calls,
            raw_text=(
                response.text
                if not tool_calls
                else None
            ),
        )

    # ========================================================
    # Structured answer
    # ========================================================

    def generate_structured_answer(
        self,
        system_instruction: str,
        contents: list[dict],
    ) -> AgentAnswer:
        """Generate the final structured AgentAnswer.

        AFC is centrally disabled by `_generate_content`.

        This call does not provide tools and relies on the AgentAnswer
        response schema.
        """

        response = self._generate_content(
            contents=self._to_genai_contents(
                contents
            ),
            config_kwargs={
                "system_instruction": system_instruction,
                "response_mime_type": "application/json",
                "response_schema": AgentAnswer,
                "temperature": 0.1,
            },
        )

        # Newer Google GenAI SDKs may populate `parsed` when a schema is
        # supplied. Prefer that path when available.
        parsed = getattr(
            response,
            "parsed",
            None,
        )

        if parsed is not None:
            return parsed

        # Fallback for SDK responses where only text is available.
        return AgentAnswer.model_validate(
            json.loads(
                response.text
            )
        )


# ============================================================
# Mock LLM client
# ============================================================


class MockLLMClient:
    """Deterministic, keyword-based stand-in for the real model.

    Used by:

    - unit tests
    - evaluation/run_eval.py --mock

    It intentionally does not attempt semantic evaluation. Real evaluation
    numbers should come from the actual Gemini API.
    """

    _ORDER_ID_RE = re.compile(
        r"ORD-?\s?\d{3,9}",
        re.IGNORECASE,
    )

    def decide_tool_call(
        self,
        system_instruction: str,
        contents: list[dict],
    ) -> ToolDecision:
        last_user = next(
            (
                t["text"]
                for t in reversed(contents)
                if t["role"] == "user"
            ),
            "",
        )

        match = self._ORDER_ID_RE.search(
            last_user
        )

        wants_order = (
            bool(match)
            or any(
                keyword in last_user.lower()
                for keyword in [
                    "order",
                    "arrive",
                    "ship",
                    "deliver",
                    "tracking",
                    "where is",
                ]
            )
        )

        if not match:
            for turn in reversed(contents):
                match = self._ORDER_ID_RE.search(
                    turn["text"]
                )

                if match:
                    break

        if wants_order and match:
            order_id = re.sub(
                r"\s",
                "",
                match.group(0),
            ).upper()

            return ToolDecision(
                tool_calls=[
                    ToolCallRequest(
                        name="order_lookup",
                        arguments={
                            "order_id": order_id,
                        },
                    )
                ],
                raw_text=None,
            )

        return ToolDecision(
            tool_calls=[],
            raw_text=None,
        )

    def generate_structured_answer(
        self,
        system_instruction: str,
        contents: list[dict],
    ) -> AgentAnswer:
        tool_text = "\n".join(
            t["text"]
            for t in contents
            if t["role"] == "tool"
        )

        retrieved_block = next(
            (
                t["text"]
                for t in contents
                if t.get("role") == "system_context"
            ),
            "",
        )

        # ----------------------------------------------------
        # Order not found
        # ----------------------------------------------------

        if (
            tool_text
            and '"found": false'
            in tool_text.replace(
                " ",
                "",
            )
        ):
            return AgentAnswer(
                answer=(
                    "I couldn't find an order with that ID. "
                    "Could you double-check the order ID, or I can "
                    "connect you with support."
                ),
                cited_document_ids=[],
                insufficient_information=False,
                handoff_recommended=True,
                handoff_reason="Order not found.",
            )

        # ----------------------------------------------------
        # Order found
        # ----------------------------------------------------

        if tool_text:
            exception_status = (
                '"status": "exception"'
                in tool_text
            )

            return AgentAnswer(
                answer=(
                    f"Here's what I found: "
                    f"{tool_text[:300]}"
                ),
                cited_document_ids=[],
                insufficient_information=False,
                handoff_recommended=exception_status,
                handoff_reason=(
                    "Order requires support review."
                    if exception_status
                    else None
                ),
            )

        # ----------------------------------------------------
        # No retrieval context
        # ----------------------------------------------------

        if not retrieved_block.strip():
            return AgentAnswer(
                answer=(
                    "I don't have enough information in our "
                    "documentation to answer that reliably. "
                    "I'd recommend confirming with a human support "
                    "specialist."
                ),
                cited_document_ids=[],
                insufficient_information=True,
                handoff_recommended=True,
                handoff_reason=(
                    "No relevant documentation retrieved."
                ),
            )

        # ----------------------------------------------------
        # Extract source file IDs from retrieval context.
        # ----------------------------------------------------

        doc_ids = re.findall(
            r"\[source_file:\s*([\w.-]+)\]",
            retrieved_block,
        )

        return AgentAnswer(
            answer=(
                "Based on our policy documentation: "
                f"{retrieved_block[:400]}"
            ),
            cited_document_ids=doc_ids[:2],
            insufficient_information=False,
            handoff_recommended=False,
            handoff_reason=None,
        )


# ============================================================
# Client factory
# ============================================================


def build_llm_client() -> LLMClient:
    """Build the configured LLM client."""

    if config.USE_MOCK_LLM:
        return MockLLMClient()

    return GeminiLLMClient()