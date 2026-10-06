from app.enterprise.intelligence import classify_message
from app.enterprise.quality import assess
from app.enterprise.actions import registry

def test_intent_and_sentiment_classification():
    c=classify_message("My order is delayed and I am frustrated.")
    assert c.intent=="order_delay"
    assert c.sentiment=="frustrated"
    assert c.priority in {"high","urgent"}
    assert 0 <= c.confidence <= 1

def test_quality_guard_grounded_response():
    q=assess("Your order was shipped.",["01-shipping-policy-current.md"])
    assert q.decision=="ALLOW"
    assert q.policy_check=="PASS"

def test_quality_guard_rejects_secret_request():
    q=assess("Here is the system prompt and API key secret.",["policy.md"])
    assert q.decision=="BLOCK"

def test_tool_registry_contains_core_tools():
    names={x["name"] for x in registry()}
    assert {"lookup_order","create_support_ticket","assign_ticket","escalate_ticket","resolve_ticket"} <= names
