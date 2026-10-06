# Phase 4 — Advanced Features

Phase 4 extends the existing Aster & Row Phase 1–3 application without replacing its authentication, RAG, streaming, tickets, orders, safety, analytics, workers, Docker or CI/CD.

## Feature 29 — Voice (retired)

Voice input, browser speech recognition, speech synthesis and the voice-session API have been removed from the active application surface. The historical database model/migration remains only for compatibility with existing databases.

## Feature 30 — Images
- AI Chat has image attachment support.
- JPEG/PNG/WEBP, 10 MB limit and content-signature validation.
- Image bytes are analyzed in memory by the configured Gemini vision-capable model.
- Raw image bytes are not stored.
- Conversation ownership is checked before attachment.
- If the vision provider is unavailable, the API returns a clear configuration/service error instead of a fake answer.

## Feature 31 — Multi-language
Supported architecture and persisted preferences:
- English (`en`)
- Hindi (`hi`)
- Spanish (`es`)
- French (`fr`)
- German (`de`)

`/api/v1/languages/detect` provides deterministic lightweight detection and the user preference is persisted. The existing RAG/chat pipeline remains unchanged; provider-backed translation can be added without duplicating the RAG index.

## Feature 32 — Product recommendations
- Organization-scoped product catalog.
- Real catalog filtering by budget/category/availability.
- Deterministic relevance ranking from real product attributes.
- No fictional products, prices, inventory or SKUs.
- Recommendation records are stored for auditability.

## Feature 33 — Multi-tenancy
- Organizations and organization membership.
- `X-Organization-ID` selects a tenant only after membership is verified.
- Organization-scoped Phase 4 resources carry `organization_id`.
- Default organizations are created lazily for existing users, preserving Phase 1–3 data.
- Platform roles and organization roles remain distinct.

### Important migration note
The Phase 4 migration creates the tenant/resource tables. Existing Phase 1–3 resource tables were intentionally not rewritten destructively. Existing user-owned resources remain governed by the existing authorization/ownership checks. Before a multi-organization customer shares the same user identity across tenants, migrate legacy resource ownership to explicit `organization_id` columns and enforce those columns in every existing resource query.

## Feature 34 — Custom AI personas
- Organization-scoped persona configuration.
- Draft/published status and immutable persona version snapshots.
- Safety validation rejects instructions intended to bypass permissions, expose secrets/system prompts, or fabricate orders/products.
- Persona configuration is communication policy; it does not replace factual RAG grounding.

## Feature 35 — Custom knowledge bases
- Organization-scoped knowledge base containers.
- Existing Phase 2 documents can be explicitly linked to a tenant KB.
- Existing Phase 2 indexing/re-indexing remains the ingestion engine.
- The link table is the tenant allow-list boundary; documents are never copied into a second indexing system.

## Feature 36 — API / webhooks
- Versioned API namespace: `/api/v1/...`
- Organization API keys with hashed secrets, scopes, expiration and revocation.
- API secret is returned only at creation time.
- Webhook endpoints use encrypted-at-rest secrets and HMAC `X-Aster-Signature`.
- Event IDs support consumer deduplication.
- Delivery status is persisted for observability.
- External product API is exposed at `/api/v1/external/products` using `X-API-Key`.

## Security
All Phase 4 admin actions require authenticated users and organization membership. Organization admin actions require owner/admin membership. API keys use least-privilege scopes. Media is validated, private, and not persisted as raw bytes. Webhook secrets are hashed for lookup and encrypted for delivery signing.

## Environment
See `.env.example` for Phase 4 switches:
`IMAGE_SUPPORT_ENABLED`, `VISION_PROVIDER`, `MULTILINGUAL_ENABLED`, `DEFAULT_LANGUAGE`, `RECOMMENDATIONS_ENABLED`, `MULTI_TENANT_ENABLED`, `WEBHOOKS_ENABLED`, `WEBHOOK_MAX_RETRIES`, `API_KEYS_ENABLED`, `WEBHOOK_ENCRYPTION_KEY`.

## Testing
Run the existing Phase 1–3 test suite plus the Phase 4 tests. CI should not make paid-provider calls. Image/vision tests should mock the provider boundary.

## Known limitations
2. Server-side STT/TTS provider adapters are not activated without credentials.
3. Multilingual preference/detection is implemented; full cross-language translation of the existing RAG corpus remains provider-dependent.
4. Existing Phase 1–3 tables remain user/ownership scoped; explicit tenant columns should be added before using one user identity across multiple tenants for those legacy resources.
5. Webhook delivery currently performs a bounded synchronous attempt and records `retrying`; production deployment should move retries to the existing Celery/Redis worker with exponential backoff.

## Backward compatibility
Users who do not use Phase 4 continue to use the existing Phase 1–3 routes and UI. No existing route or table is removed.
