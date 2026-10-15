# Test Coverage Map — HiRag15k MVP

> This map is hand-maintained. If a test fails, the REQ is at risk.
> If a REQ has no test, it's a coverage gap.
> Update this file when tests are added or removed.

Total REQs: 17 (7 ING + 7 CHS + 3 HST).

---

## ING — Ingestion Capability

| Spec REQ | Test file | Test function(s) | Status |
|---|---|---|---|
| REQ-ING-001: Read source markdown | `tests/integration/test_ingest_endpoint.py` | `test_ingest_returns_200_and_correct_body` | ✅ |
| REQ-ING-002: Markdown-aware chunking | `tests/unit/test_chunker.py` | `test_faq_entries_individual_chunks`, `test_long_section_split_preserves_heading`, `test_file_smaller_than_chunk_size_one_chunk_equals_input`, `test_empty_string_returns_empty_list` | ✅ |
| REQ-ING-003: Embed each chunk | `tests/unit/test_embedder.py` | `test_embed_single_text`, `test_embed_batch` | ✅ |
| REQ-ING-003: Embed each chunk | `tests/integration/test_ingest_service.py` | `test_happy_path` | ✅ |
| REQ-ING-004: Persist to ChromaDB on disk | `tests/unit/test_vector_store.py` | `test_upsert_single_document`, `test_upsert_multiple_documents`, `test_after_upsert_collection_present` | ✅ |
| REQ-ING-005: Return summary | `tests/integration/test_ingest_endpoint.py` | `test_ingest_returns_200_and_correct_body` | ✅ |
| REQ-ING-006: Reject bad requests | `tests/integration/test_ingest_endpoint.py` | `test_ingest_nonexistent_file_returns_404`, `test_ingest_txt_file_returns_415`, `test_ingest_oversized_file_returns_413`, `test_ingest_path_outside_data_dir_returns_400` | ✅ |
| REQ-ING-007: Idempotent re-ingest | `tests/integration/test_ingest_endpoint.py` | `test_reingest_replaces_chunks` | ✅ |
| REQ-ING-007: Idempotent re-ingest | `tests/integration/test_ingest_service.py` | `test_idempotent_reingest`, `test_delete_called_before_upsert` | ✅ |

---

## CHS — Chat Stream Capability

| Spec REQ | Test file | Test function(s) | Status |
|---|---|---|---|
| REQ-CHS-001: Accept question and optional collection | `tests/integration/test_chat_endpoint.py` | `test_coherent_stream_yields_content_then_done`, `test_unknown_collection_returns_error_event`, `test_ambiguous_collection_returns_error_event` | ✅ |
| REQ-CHS-001: Accept question and optional collection | `tests/integration/test_chat_service.py` | `test_single_collection_auto_resolved`, `test_collection_override_uses_explicit_name`, `test_unknown_collection_explicit`, `test_ambiguous_collection_no_override` | ✅ |
| REQ-CHS-002: Retrieve TOP_K chunks above threshold | `tests/unit/test_retriever.py` | `test_zero_hits_below_threshold_returns_empty`, `test_fewer_than_top_k_above_threshold_returns_all`, `test_exactly_top_k_returns_all_ordered_desc`, `test_more_than_top_k_returns_only_top_k` | ✅ |
| REQ-CHS-002: Retrieve TOP_K chunks above threshold | `tests/integration/test_chat_service.py` | `test_happy_path_with_hits`, `test_deflection_with_empty_retrieval_patched` | ✅ |
| REQ-CHS-003: Build Spanish context-bound system prompt | `tests/unit/test_prompts.py` | `test_template_matches_design_doc`, `test_multiple_chunks_separated_by_blank_line`, `test_single_chunk_formatted_correctly`, `test_retrieved_chunks_marker_replaced` | ✅ |
| REQ-CHS-003: Build Spanish context-bound system prompt | `tests/integration/test_chat_service.py` | `test_happy_path_with_hits` (implicit: prompt built from hits) | ✅ |
| REQ-CHS-004: Canonical deflection when no chunks meet threshold | `tests/integration/test_chat_endpoint.py` | `test_deflection_returns_exact_phrase_and_llm_not_called` | ✅ |
| REQ-CHS-004: Canonical deflection when no chunks meet threshold | `tests/integration/test_chat_service.py` | `test_central_deflection_no_llm_call` | ✅ |
| REQ-CHS-005: Stream LLM response via SSE | `tests/integration/test_chat_endpoint.py` | `test_coherent_stream_yields_content_then_done` | ✅ |
| REQ-CHS-005: Stream LLM response via SSE | `tests/integration/test_chat_endpoint.py` | `test_llm_error_yields_error_then_done` (mid-stream error) | ✅ |
| REQ-CHS-005: Stream LLM response via SSE | `tests/integration/test_chat_service.py` | `test_llm_midstream_error` | ✅ |
| REQ-CHS-005: Stream LLM response via SSE | `tests/integration/test_chat_endpoint.py` | `test_missing_question_returns_400`, `test_malformed_json_returns_400` (malformed body → 4xx) | ✅ |
| REQ-CHS-006: Single-turn, no server-side history | `tests/integration/test_chat_service.py` | `test_happy_path_with_hits` (two consecutive calls, no state consulted) | ✅ |
| REQ-CHS-007: No retrieved chunks in response body | `tests/integration/test_chat_endpoint.py` | `test_coherent_stream_yields_content_then_done` (SSE events checked for `type=content` only) | ✅ |

---

## HST — Health Status Capability

| Spec REQ | Test file | Test function(s) | Status |
|---|---|---|---|
| REQ-HST-001: Return operational status and index statistics | `tests/integration/test_health_endpoint.py` | `test_health_with_one_collection_returns_200` | ✅ |
| REQ-HST-001: Return operational status and index statistics | `tests/integration/test_health_service.py` | `test_healthy_with_one_collection`, `test_healthy_with_multiple_collections` | ✅ |
| REQ-HST-002: Report failure when ChromaDB unreachable | `tests/integration/test_health_endpoint.py` | `test_health_unreachable_returns_503` | ✅ |
| REQ-HST-002: Report failure when ChromaDB unreachable | `tests/integration/test_health_service.py` | `test_503_when_store_raises`, `test_503_when_store_unreachable` | ✅ |
| REQ-HST-003: Read-only endpoint (no mutations) | `tests/integration/test_health_service.py` | `test_no_mutation_on_status_call` | ✅ |

---

## Coverage Summary

| Capability | REQs | Fully Covered | Notes |
|---|---|---|---|
| ingestion | 7 | 7/7 ✅ | All paths tested (happy, errors, idempotency) |
| chat-stream | 7 | 7/7 ✅ | All paths tested (happy, deflection, LLM error, validation, single-turn) |
| health-status | 3 | 3/3 ✅ | All paths tested (200, 503, non-mutating) |
| **Total** | **17** | **17/17 ✅** | Full coverage |

## Notes

- All tests use real ChromaDB in `tmp_path` (function-scoped) for integration tests.
- LLM is fully mocked (`_FakeLLM` in `tests/conftest.py`); no real LLM calls in any test.
- Embedder is mocked via `make_fake_embedder()` in conftest.py.
- There are no network calls in any test.
- The pinning test (`test_template_matches_design_doc`) reads the actual design doc at runtime to verify byte-for-byte equality with `SYSTEM_PROMPT_TEMPLATE`.
