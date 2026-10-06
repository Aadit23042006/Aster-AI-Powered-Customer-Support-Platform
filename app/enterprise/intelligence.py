from __future__ import annotations

import re
from dataclasses import dataclass


INTENTS = [
    "order_status",
    "order_delay",
    "shipping",
    "return",
    "refund",
    "damaged_product",
    "product_question",
    "payment",
    "account",
    "human_handoff",
    "general_question",
    "unknown",
]

SENTIMENTS = [
    "positive",
    "neutral",
    "frustrated",
    "angry",
    "confused",
    "negative",
    "unknown",
]


CLASSIFIER_MODEL = "deterministic-support-classifier"
CLASSIFIER_VERSION = "rules-v1"
CLASSIFIER_SOURCE = "rule"


@dataclass
class Classification:
    intent: str
    sentiment: str
    priority: str
    topic: str
    risk_level: str
    confidence: float

    def as_structured(self) -> dict:
        """Structured output contract (customer_risk == risk_level)."""
        return {
            "intent": self.intent,
            "sentiment": self.sentiment,
            "priority": self.priority,
            "topic": self.topic,
            "customer_risk": self.risk_level,
            "confidence": self.confidence,
        }


def classify_message(text: str) -> Classification:
    """
    Deterministic support-message classifier.

    Classification order is intentional:

    1. Human handoff
    2. Refund
    3. Return
    4. Damaged product
    5. Payment
    6. Account
    7. Order delay
    8. Order status
    9. General shipping
    10. Product question
    11. General question

    Important distinctions:

        "Where is my order?"
            -> order_status

        "What is my order status?"
            -> order_status

        "Track my order"
            -> order_status

        "My order is late"
            -> order_delay

        "My order is delayed"
            -> order_delay

        "My order has not arrived"
            -> order_delay

        "I am furious about this delay"
            -> order_delay

        "The delivery is delayed"
            -> order_delay

        "What shipping options do you offer?"
            -> shipping
    """

    # ------------------------------------------------------------------
    # NORMALIZE INPUT
    # ------------------------------------------------------------------

    t = (text or "").lower().strip()

    # Normalize curly apostrophes.
    t = t.replace("’", "'")

    # Normalize whitespace.
    t = re.sub(r"\s+", " ", t)

    def has(*phrases: str) -> bool:
        """
        Return True when any phrase exists in the normalized message.

        This classifier intentionally uses deterministic substring matching
        so the same input produces the same classification every time.
        """
        return any(phrase in t for phrase in phrases)

    # ------------------------------------------------------------------
    # INTENT CLASSIFICATION
    # ------------------------------------------------------------------

    # 1. HUMAN HANDOFF
    #
    # Explicit requests to speak with a human should take priority over
    # other possible interpretations.

    if has(
        "talk to a human",
        "speak to a human",
        "talk to human",
        "speak to human",
        "human agent",
        "human representative",
        "real person",
        "real agent",
        "customer service representative",
        "support representative",
        "support agent",
        "talk to an agent",
        "speak to an agent",
        "talk with an agent",
        "speak with an agent",
        "talk to someone",
        "speak to someone",
        "human",
        "agent",
        "representative",
    ):
        intent = "human_handoff"

    # 2. REFUND

    elif has(
        "want a refund",
        "need a refund",
        "request a refund",
        "get a refund",
        "ask for a refund",
        "refund",
        "money back",
        "reimburse",
        "reimbursement",
    ):
        intent = "refund"

    # 3. RETURN

    elif has(
        "want to return",
        "need to return",
        "request a return",
        "return this",
        "return the product",
        "return the item",
        "send back",
        "send it back",
        "return",
    ):
        intent = "return"

    # 4. DAMAGED PRODUCT

    elif has(
        "product arrived broken",
        "item arrived broken",
        "arrived broken",
        "arrived damaged",
        "product is broken",
        "product is damaged",
        "item is broken",
        "item is damaged",
        "broken product",
        "damaged product",
        "broken item",
        "damaged item",
        "defective product",
        "defective item",
        "defective",
        "damaged",
        "broken",
    ):
        intent = "damaged_product"

    # 5. PAYMENT

    elif has(
        "payment",
        "payment failed",
        "payment issue",
        "payment problem",
        "payment was declined",
        "payment declined",
        "charged",
        "wrong charge",
        "incorrect charge",
        "unexpected charge",
        "charge",
        "card",
        "credit card",
        "debit card",
    ):
        intent = "payment"

    # 6. ACCOUNT

    elif has(
        "account",
        "my account",
        "account issue",
        "account problem",
        "login",
        "log in",
        "sign in",
        "password",
        "forgot password",
        "reset password",
        "email address",
    ):
        intent = "account"

    # 7. ORDER DELAY
    #
    # IMPORTANT:
    #
    # This MUST be checked before generic shipping/delivery conditions
    # and before generic order-status conditions.
    #
    # This specifically fixes:
    #
    #   "I am furious about this delay"
    #
    # which previously became:
    #
    #   general_question
    #
    # It should become:
    #
    #   order_delay
    #
    # We intentionally support both:
    #
    #   delay
    #   delays
    #   delayed
    #
    # as well as explicit order/delivery delay phrases.

    elif has(
        # Explicit order delay
        "order is late",
        "order was late",
        "order arrived late",
        "my order is late",
        "my order was late",
        "my order arrived late",
        "order is delayed",
        "order was delayed",
        "my order is delayed",
        "my order was delayed",
        "order has been delayed",
        "my order has been delayed",
        "order has a delay",
        "my order has a delay",

        # Explicit delivery delay
        "delivery is late",
        "delivery was late",
        "delivery arrived late",
        "delivery is delayed",
        "delivery was delayed",
        "delivery has been delayed",
        "delivery has a delay",
        "delivery delay",
        "delivery delays",

        # Explicit shipment delay
        "shipment is delayed",
        "shipment was delayed",
        "shipment has been delayed",
        "shipment delay",
        "shipment delays",

        # General delay wording
        "there is a delay",
        "there's a delay",
        "there is a delay with my order",
        "there's a delay with my order",
        "delay with my order",
        "delays with my order",
        "delay in my order",
        "delays in my order",
        "delay with delivery",
        "delays with delivery",

        # Standalone delay words.
        #
        # These are intentionally included so:
        #
        #   "I am furious about this delay"
        #
        # becomes order_delay.
        "delay",
        "delays",
        "delayed",
        "late",

        # Not-arrived / not-received patterns
        "not arrived",
        "hasn't arrived",
        "hasnt arrived",
        "has not arrived",
        "still hasn't arrived",
        "still hasnt arrived",
        "still not arrived",
        "not received",
        "haven't received",
        "havent received",
        "have not received",
        "still haven't received",
        "still havent received",
        "still have not received",

        # Explicit delayed-order wording
        "where is my delayed order",
        "where's my delayed order",
        "where is the delayed order",
        "where's the delayed order",
    ):
        intent = "order_delay"

    # 8. ORDER STATUS
    #
    # These checks come BEFORE broad shipping/delivery checks.
    #
    # Examples:
    #
    #   "Where is my order?"
    #       -> order_status
    #
    #   "What is my order status?"
    #       -> order_status
    #
    #   "Track my order"
    #       -> order_status

    elif has(
        "where is my order",
        "where's my order",
        "wheres my order",
        "where is the order",
        "where's the order",
        "wheres the order",
        "where is my package",
        "where's my package",
        "wheres my package",
        "where is the package",
        "where's the package",
        "wheres the package",
        "where is my parcel",
        "where's my parcel",
        "wheres my parcel",
        "where is the parcel",
        "where's the parcel",
        "wheres the parcel",
        "track my order",
        "track the order",
        "track my package",
        "track the package",
        "track my parcel",
        "track the parcel",
        "order status",
        "status of my order",
        "status of the order",
        "what is the status of my order",
        "what's the status of my order",
        "whats the status of my order",
        "what is my order status",
        "what's my order status",
        "whats my order status",
        "check my order status",
        "check the order status",
        "order tracking",
        "tracking my order",
        "tracking information for my order",
        "tracking information about my order",
        "tracking number for my order",
    ):
        intent = "order_status"

    # 9. GENERAL SHIPPING
    #
    # This is for general shipping/delivery questions that are NOT
    # specifically asking about the status of a delayed order.

    elif has(
        "shipping",
        "shipping options",
        "shipping option",
        "shipping method",
        "shipping methods",
        "shipping cost",
        "shipping fee",
        "shipping fees",
        "delivery options",
        "delivery option",
        "delivery method",
        "delivery methods",
        "delivery time",
        "delivery times",
        "how long does delivery take",
        "how long is delivery",
        "how long does shipping take",
        "how long is shipping",
        "international delivery",
        "international shipping",
        "do you deliver",
        "do you ship",
        "delivery",
        "deliver",
    ):
        intent = "shipping"

    # 10. PRODUCT QUESTION

    elif has(
        "bag",
        "tumbler",
        "bottle",
        "product",
        "size",
        "color",
        "colour",
        "available in",
        "product information",
        "product details",
        "product question",
    ):
        intent = "product_question"

    # 11. GENERAL QUESTION

    else:
        intent = "general_question"

    # ------------------------------------------------------------------
    # SENTIMENT CLASSIFICATION
    # ------------------------------------------------------------------

    # Positive

    if has(
        "thank",
        "thanks",
        "thank you",
        "great",
        "perfect",
        "excellent",
        "amazing",
        "awesome",
        "happy",
        "love it",
        "love this",
        "very happy",
        "really happy",
    ):
        sentiment = "positive"

    # Angry

    elif has(
        "angry",
        "furious",
        "extremely angry",
        "very angry",
        "so angry",
        "terrible",
        "ridiculous",
        "outraged",
        "unacceptable",
        "absolutely unacceptable",
        "this is unacceptable",
    ):
        sentiment = "angry"

    # Confused

    elif has(
        "confused",
        "confusing",
        "don't understand",
        "dont understand",
        "do not understand",
        "not sure what happened",
        "don't know what happened",
        "dont know what happened",
        "do not know what happened",
        "i am confused",
        "i'm confused",
    ):
        sentiment = "confused"

    # Frustrated

    elif has(
        "frustrated",
        "frustrating",
        "annoyed",
        "annoying",
        "upset",
        "late",
        "delayed",
        "not arrived",
        "hasn't arrived",
        "hasnt arrived",
        "still waiting",
        "waiting for my order",
        "waiting for my package",
    ):
        sentiment = "frustrated"

    # Negative

    elif has(
        "bad",
        "awful",
        "hate",
        "disappointed",
        "disappointing",
        "worst",
        "poor experience",
        "horrible",
        "terrible experience",
    ):
        sentiment = "negative"

    # Neutral

    else:
        sentiment = "neutral"

    # ------------------------------------------------------------------
    # PRIORITY
    # ------------------------------------------------------------------

    if has(
        "urgent",
        "emergency",
        "asap",
        "immediately",
        "right now",
        "as soon as possible",
    ):
        priority = "urgent"

    elif (
        intent
        in {
            "refund",
            "damaged_product",
            "human_handoff",
            "order_delay",
        }
        or sentiment == "angry"
    ):
        priority = "high"

    elif intent != "general_question":
        priority = "medium"

    else:
        priority = "low"

    # ------------------------------------------------------------------
    # TOPIC
    # ------------------------------------------------------------------

    topic = {
        "order_status": "orders",
        "order_delay": "shipping",
        "shipping": "shipping",
        "return": "returns",
        "refund": "returns",
        "damaged_product": "products",
        "product_question": "products",
        "payment": "payments",
        "account": "account",
        "human_handoff": "general",
        "general_question": "general",
        "unknown": "general",
    }.get(intent, "general")

    # ------------------------------------------------------------------
    # RISK LEVEL
    # ------------------------------------------------------------------

    if has(
        "password",
        "card number",
        "credit card number",
        "debit card number",
        "ssn",
        "social security",
        "address",
    ):
        risk_level = "high"

    elif intent in {
        "refund",
        "payment",
        "human_handoff",
    }:
        risk_level = "medium"

    else:
        risk_level = "low"

    # ------------------------------------------------------------------
    # CONFIDENCE
    # ------------------------------------------------------------------
    #
    # All recognized intents receive the deterministic classifier's
    # high confidence value.
    #
    # General questions receive lower confidence because they do not
    # match a specific support intent.

    confidence = (
        0.88
        if intent != "general_question"
        else 0.62
    )

    # ------------------------------------------------------------------
    # RETURN CLASSIFICATION
    # ------------------------------------------------------------------

    return Classification(
        intent=intent,
        sentiment=sentiment,
        priority=priority,
        topic=topic,
        risk_level=risk_level,
        confidence=confidence,
    )