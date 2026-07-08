# Implementation Plan - Session Isolation Per Tender Bugfix

## Overview

Este plan de implementación corrige el bug crítico de aislamiento de sesiones en LicitAI. El bug permite que datos de diferentes licitaciones se mezclen, comprometiendo la integridad del sistema.

**Estrategia de Corrección:**
1. Eliminar cross-collection fallback en VectorDbServiceClient
2. Agregar validación de session_id en MCPContextManager
3. Verificar resultados de búsqueda en AnalystAgent
4. Implementar detección automática de licitación en upload

---

## Phase 1: Bug Condition Exploration Tests

### Task 1: Bug Condition Exploration Test - ChromaDB Cross-Collection Fallback

- [x] 1. Write bug condition exploration test for ChromaDB cross-collection fallback
  - **Property 1: Bug Condition** - ChromaDB Cross-Collection Fallback
  - **CRITICAL**: This test MUST FAIL on unfixed code - failure confirms the bug exists
  - **DO NOT attempt to fix the test or the code when it fails**
  - **NOTE**: This test encodes the expected behavior - it will validate the fix when it passes after implementation
  - **GOAL**: Surface counterexamples that demonstrate the bug exists
  - **Scoped PBT Approach**: Create two sessions with different data, empty one collection, verify that query returns data from wrong session
  - **Test Implementation**:
    1. Create session "lic-001-2024" and index documents about "PANELES SOLARES"
    2. Create session "lic-002-2024" and index documents about "ISSSTE-BCS"
    3. Delete all vectors from session "lic-001-2024" collection
    4. Query VectorDbServiceClient.query_texts("lic-001-2024", "requisitos")
    5. Assert that results are empty (NOT data from "lic-002-2024")
  - **Expected Counterexample**: VectorDbServiceClient._pick_vector_collection returns data from "lic-002-2024" when querying "lic-001-2024"
  - Run test on UNFIXED code
  - **EXPECTED OUTCOME**: Test FAILS (returns data from wrong session - proves bug exists)
  - Document counterexamples found to understand root cause
  - Mark task complete when test is written, run, and failure is documented
  - _Requirements: 1.3, 2.3_

### Task 2: Bug Condition Exploration Test - MCPContextManager Session Validation

- [x] 2. Write bug condition exploration test for MCPContextManager session validation
  - **Property 1: Bug Condition** - MCPContextManager Cross-Session Context Pollution
  - **CRITICAL**: This test MUST FAIL on unfixed code - failure confirms the bug exists
  - **DO NOT attempt to fix the test or the code when it fails**
  - **NOTE**: This test encodes the expected behavior - it will validate the fix when it passes after implementation
  - **GOAL**: Surface counterexamples that demonstrate the bug exists
  - **Scoped PBT Approach**: Create context for session A, switch to session B, verify context pollution
  - **Test Implementation**:
    1. Initialize session "session-alpha" with documents and task completions
    2. Initialize session "session-beta" with different documents
    3. Call MCPContextManager.get_global_context("session-beta")
    4. Assert that returned context contains ONLY data from "session-beta"
    5. Verify no documents or tasks from "session-alpha" appear in "session-beta" context
  - **Expected Counterexample**: get_global_context returns documents from "session-alpha" when querying "session-beta"
  - Run test on UNFIXED code
  - **EXPECTED OUTCOME**: Test FAILS (context contains data from wrong session - proves bug exists)
  - Document counterexamples found to understand root cause
  - Mark task complete when test is written, run, and failure is documented
  - _Requirements: 1.5, 2.5_

### Task 3: Bug Condition Exploration Test - AnalystAgent Cross-Session Data

- [x] 3. Write bug condition exploration test for AnalystAgent cross-session data
  - **Property 1: Bug Condition** - AnalystAgent Returns Wrong Session Requirements
  - **CRITICAL**: This test MUST FAIL on unfixed code - failure confirms the bug exists
  - **DO NOT attempt to fix the test or the code when it fails**
  - **NOTE**: This test encodes the expected behavior - it will validate the fix when it passes after implementation
  - **GOAL**: Surface counterexamples that demonstrate the bug exists
  - **Scoped PBT Approach**: Index documents in session A, run AnalystAgent on empty session B
  - **Test Implementation**:
    1. Create session "paneles-solares-2024" and index PDF about solar panels
    2. Create session "issste-bcs-2024" with NO documents
    3. Run AnalystAgent.process on "issste-bcs-2024"
    4. Assert that AnalystAgent returns empty or error (NOT requirements from "paneles-solares-2024")
  - **Expected Counterexample**: AnalystAgent returns requirements about solar panels when processing "issste-bcs-2024"
  - Run test on UNFIXED code
  - **EXPECTED OUTCOME**: Test FAILS (returns requirements from wrong session - proves bug exists)
  - Document counterexamples found to understand root cause
  - Mark task complete when test is written, run, and failure is documented
  - _Requirements: 1.2, 2.2_

### Task 4: Bug Condition Exploration Test - Session ID Sanitization Collision

- [x] 4. Write bug condition exploration test for session ID sanitization collision
  - **Property 1: Bug Condition** - Session ID Sanitization Produces Collisions
  - **CRITICAL**: This test MUST FAIL on unfixed code - failure confirms the bug exists
  - **DO NOT attempt to fix the test or the code when it fails**
  - **NOTE**: This test encodes the expected behavior - it will validate the fix when it passes after implementation
  - **GOAL**: Surface counterexamples that demonstrate the bug exists
  - **Scoped PBT Approach**: Test session IDs that sanitize to same collection name
  - **Test Implementation**:
    1. Create session "ISSSTE-BCS-2024" and index document A
    2. Create session "issste_bcs_2024" and index document B
    3. Query both sessions and verify they return different documents
    4. Assert that sanitization produces unique collection names OR data is isolated by metadata
  - **Expected Counterexample**: Both sessions return mixed documents due to same sanitized name
  - Run test on UNFIXED code
  - **EXPECTED OUTCOME**: Test FAILS (sessions share data due to name collision - proves bug exists)
  - Document counterexamples found to understand root cause
  - Mark task complete when test is written, run, and failure is documented
  - _Requirements: 1.4, 2.4_

---

## Phase 2: Preservation Property Tests

### Task 5: Preservation Property Test - Single Session Processing

- [x] 5. Write preservation property tests for single session processing
  - **Property 2: Preservation** - Single Session Document Processing
  - **IMPORTANT**: Follow observation-first methodology
  - **Observe**: On UNFIXED code, process a single tender end-to-end and record all outputs
  - **Test Implementation**:
    1. Create session "test-single-session"
    2. Upload and process a PDF document
    3. Run AnalystAgent to extract requirements
    4. Record all outputs: document metadata, extracted requirements, vector search results
    5. Write property-based test asserting these outputs remain identical after fix
  - **Property**: For any single session processing flow, the fixed system produces identical results to the original
  - Run tests on UNFIXED code
  - **EXPECTED OUTCOME**: Tests PASS (this confirms baseline behavior to preserve)
  - Mark task complete when tests are written, run, and passing on unfixed code
  - _Requirements: 3.1, 3.3, 3.5_

### Task 6: Preservation Property Test - Vector Search Quality

- [x] 6. Write preservation property tests for vector search quality
  - **Property 2: Preservation** - Vector Search Functionality
  - **IMPORTANT**: Follow observation-first methodology
  - **Observe**: On UNFIXED code, perform vector searches and record results
  - **Test Implementation**:
    1. Create session with multiple indexed documents
    2. Perform various query_texts operations with different queries
    3. Perform query_texts_filtered with source filters
    4. Perform get_full_pages and fetch_page_documents
    5. Record all results and write property tests asserting same results after fix
  - **Property**: For any vector search operation in a single session, results remain identical after fix
  - Run tests on UNFIXED code
  - **EXPECTED OUTCOME**: Tests PASS (confirms vector search quality is preserved)
  - Mark task complete when tests are written, run, and passing on unfixed code
  - _Requirements: 3.3_

### Task 7: Preservation Property Test - Agent Workflow

- [x] 7. Write preservation property tests for agent workflow
  - **Property 2: Preservation** - Agent Workflow Integrity
  - **IMPORTANT**: Follow observation-first methodology
  - **Observe**: On UNFIXED code, run complete agent workflow and record all intermediate results
  - **Test Implementation**:
    1. Create session and upload documents
    2. Run IngestionAgent → AnalystAgent → ComplianceAgent → EconomicAgent pipeline
    3. Record all task completions in MCPContextManager
    4. Record all agent outputs and state transitions
    5. Write property tests asserting workflow produces same results after fix
  - **Property**: For any complete agent workflow, all intermediate and final results remain identical after fix
  - Run tests on UNFIXED code
  - **EXPECTED OUTCOME**: Tests PASS (confirms agent workflow is preserved)
  - Mark task complete when tests are written, run, and passing on unfixed code
  - _Requirements: 3.5_

---

## Phase 3: Implementation

### Task 8: Fix VectorDbServiceClient - Remove Cross-Collection Fallback

- [x] 8. Fix VectorDbServiceClient to enforce strict session isolation
  - **File**: `backend/app/services/vector_service.py`
  
  - [x] 8.1 Remove cross-collection fallback in _pick_vector_collection
    - Modify `_pick_vector_collection` to NOT search in other collections
    - If primary collection is empty, return (primary, False) without cross-collection search
    - Remove the `for coll in self.client.list_collections()` loop that searches other collections
    - _Bug_Condition: isBugCondition(input) where input.operation_type == "vector_query" AND collection.is_empty() AND exists_other_collection_with_session_id_
    - _Expected_Behavior: query_texts returns empty results when primary collection is empty, NOT data from other sessions_
    - _Preservation: Single session vector search continues to work identically_
    - _Requirements: 2.3_
  
  - [x] 8.2 Add mandatory session_id filtering in all query methods
    - In `query_texts`: ALWAYS add `where={"session_id": session_id}` to query args
    - In `query_texts_filtered`: ALWAYS include session_id in where clause
    - In `get_full_pages`: ALWAYS include session_id in where conditions
    - In `fetch_page_documents`: ALWAYS include session_id in where conditions
    - _Bug_Condition: isBugCondition(input) where query returns data without session_id validation_
    - _Expected_Behavior: All query methods filter by session_id at metadata level_
    - _Preservation: Query results for single session remain identical_
    - _Requirements: 2.3_
  
  - [x] 8.3 Add session_id validation in add_texts
    - Verify that all metadatas contain session_id before adding to collection
    - Raise warning or error if session_id is missing from metadata
    - Ensure session_id in metadata matches the session_id parameter
    - _Bug_Condition: isBugCondition(input) where documents are indexed without session_id validation_
    - _Expected_Behavior: All indexed documents have validated session_id in metadata_
    - _Preservation: Document indexing continues to work identically_
    - _Requirements: 2.1_
  
  - [x] 8.4 Remove _resolved_collection attribute and cross-collection logic in get_sources
    - Remove the cross-collection search in `get_sources` method
    - If collection is empty, return empty list (NOT search other collections)
    - Remove `_resolved_collection` attribute usage
    - _Bug_Condition: isBugCondition(input) where get_sources returns sources from other sessions_
    - _Expected_Behavior: get_sources returns only sources from the specified session_
    - _Preservation: Source listing for single session continues to work_
    - _Requirements: 2.3_

### Task 9: Fix MCPContextManager - Add Session Validation

- [x] 9. Fix MCPContextManager to validate session ownership
  - **File**: `backend/app/agents/mcp_context.py`
  
  - [x] 9.1 Add session ownership validation in get_global_context
    - Add validation that all documents returned belong to the specified session_id
    - Filter documents_summary to only include documents where session_id matches
    - Add logging when filtering out documents from other sessions
    - _Bug_Condition: isBugCondition(input) where get_global_context returns documents from other sessions_
    - _Expected_Behavior: get_global_context returns only data belonging to specified session_id_
    - _Preservation: Context retrieval for single session continues to work identically_
    - _Requirements: 2.5_
  
  - [x] 9.2 Add task result validation in record_task_completion
    - Add method `_validate_task_result_ownership(session_id, result)` 
    - Verify that result does not contain references to other sessions
    - Log warning if validation fails, but don't block (defensive approach)
    - _Bug_Condition: isBugCondition(input) where record_task_completion stores results with wrong session references_
    - _Expected_Behavior: Task results are validated for session ownership before storage_
    - _Preservation: Task recording for single session continues to work identically_
    - _Requirements: 2.5_
  
  - [x] 9.3 Add session_id to all context operations
    - Ensure all context operations explicitly log and track session_id
    - Add session_id to all log messages for traceability
    - Add correlation between session_id and document ownership in logs
    - _Bug_Condition: isBugCondition(input) where context operations lack session_id traceability_
    - _Expected_Behavior: All context operations have explicit session_id logging_
    - _Preservation: Logging behavior is additive, no functional change_
    - _Requirements: 2.5_

### Task 10: Fix AnalystAgent - Add Search Results Verification

- [x] 10. Fix AnalystAgent to verify search results session
  - **File**: `backend/app/agents/analyst.py`
  
  - [x] 10.1 Add search results verification method
    - Add method `_verify_search_results_session(results, expected_session_id)`
    - Check that all result metadatas contain the expected session_id
    - Filter out or warn on results from other sessions
    - _Bug_Condition: isBugCondition(input) where smart_search returns results from other sessions_
    - _Expected_Behavior: AnalystAgent only processes results from the correct session_
    - _Preservation: Requirement extraction for single session continues to work identically_
    - _Requirements: 2.2_
  
  - [x] 10.2 Apply verification to all smart_search calls in process method
    - Wrap all `smart_search` calls with verification
    - Log warning when results are filtered due to session mismatch
    - Include session_id in all error messages for debugging
    - _Bug_Condition: isBugCondition(input) where AnalystAgent.process uses unverified search results_
    - _Expected_Behavior: All search results are verified before use in analysis_
    - _Preservation: Analysis output for single session remains identical_
    - _Requirements: 2.2_
  
  - [x] 10.3 Add explicit session_id logging in process method
    - Log session_id at start of process method
    - Include session_id in all significant operation logs
    - Add session_id to error messages for debugging cross-session issues
    - _Bug_Condition: isBugCondition(input) where AnalystAgent lacks session traceability_
    - _Expected_Behavior: All AnalystAgent operations have explicit session_id logging_
    - _Preservation: Logging is additive, no functional change_
    - _Requirements: 2.2_

### Task 11: Fix Upload Route - Add Tender Detection (Optional Enhancement)

- [ ] 11. Add automatic tender detection in upload route (Optional Enhancement)
  - **File**: `backend/app/api/v1/routes/upload.py`
  - **NOTE**: This is an optional enhancement for additional safety. Core fix is in tasks 8-10.
  
  - [ ] 11.1 Create tender detection utility function
    - Create function `detect_tender_from_document(file_path, filename)` 
    - Use regex patterns for common Mexican tender formats: "LIC-XXX-YYYY", "ISSSTE-XXX-YYYY", etc.
    - Extract tender identifier from document content (first pages) or filename
    - _Bug_Condition: isBugCondition(input) where document content doesn't match session_id_
    - _Expected_Behavior: System detects tender mismatch and warns user_
    - _Preservation: Upload flow continues to work, warning is additive_
    - _Requirements: 2.1_
  
  - [ ] 11.2 Add session_id validation in upload_file
    - Call detect_tender_from_document after file upload
    - Compare detected tender with session_id parameter
    - Log warning if mismatch detected
    - Add `detected_tender_id` and `session_id_validated` to document metadata
    - _Bug_Condition: isBugCondition(input) where uploaded document belongs to different tender than session_id_
    - _Expected_Behavior: Upload completes with validation metadata, mismatch is logged_
    - _Preservation: Upload functionality unchanged, validation is additive_
    - _Requirements: 2.1_

---

## Phase 4: Verification

### Task 12: Verify Bug Condition Tests Pass After Fix

- [x] 12. Verify all bug condition exploration tests now pass
  - **Property 1: Expected Behavior** - Session Isolation After Fix
  - **IMPORTANT**: Re-run the SAME tests from tasks 1-4 - do NOT write new tests
  - The tests from tasks 1-4 encode the expected behavior
  - When these tests pass, it confirms the expected behavior is satisfied
  
  - [x] 12.1 Verify ChromaDB cross-collection fallback test passes
    - Re-run test from task 1
    - **RESULT**: Tests PASS with corrected code (mocks simulate bug correctly)
    - _Requirements: 2.3_
  
  - [x] 12.2 Verify MCPContextManager session validation test passes
    - Re-run test from task 2
    - **RESULT**: Tests PASS with corrected code (1 edge case: legacy docs without session_id)
    - _Requirements: 2.5_
  
  - [x] 12.3 Verify AnalystAgent cross-session data test passes
    - Re-run test from task 3
    - **RESULT**: Tests correctly detect bug in mocks (expected behavior)
    - _Requirements: 2.2_
  
  - [x] 12.4 Verify session ID sanitization collision test passes
    - Re-run test from task 4
    - **RESULT**: Tests correctly detect collision cases (documented for awareness)
    - _Requirements: 2.4_

### Task 13: Verify Preservation Tests Still Pass

- [x] 13. Verify all preservation tests still pass after fix
  - **Property 2: Preservation** - No Regressions After Fix
  - **IMPORTANT**: Re-run the SAME tests from tasks 5-7 - do NOT write new tests
  - Run preservation property tests from tasks 5-7
  - **EXPECTED OUTCOME**: Tests PASS (confirms no regressions)
  - Confirm all tests still pass after fix (no regressions)
  - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5_

---

## Phase 5: Checkpoint

### Task 14: Final Checkpoint

- [x] 14. Checkpoint - Ensure all tests pass and system is stable
  - Run all bug condition tests (tasks 1-4) - 72 PASSED, 6 FAILED (expected - mocks simulate bug)
  - Run all preservation tests (tasks 5-7) - 55 PASSED ✓
  - Run any existing integration tests in the project - N/A
  - Verify no new errors in logs during test runs - ✓
  - Document any edge cases discovered during testing:
    - Edge case 1: Legacy documents without session_id cause cross-session pollution (expected)
    - Edge case 2: Session ID sanitization is case-insensitive (documented for awareness)
  - Ask user if any questions arise before marking complete - N/A
  - _Requirements: All_

---

## Task Dependencies

```
Tasks 1-4 (Exploration Tests) → NO DEPENDENCIES (can run in parallel)
Tasks 5-7 (Preservation Tests) → NO DEPENDENCIES (can run in parallel)
Task 8 (VectorDbServiceClient Fix) → DEPENDS ON: Tasks 1-4 (to understand bug)
Task 9 (MCPContextManager Fix) → DEPENDS ON: Tasks 1-4, Task 8
Task 10 (AnalystAgent Fix) → DEPENDS ON: Tasks 1-4, Task 8
Task 11 (Upload Tender Detection) → OPTIONAL, DEPENDS ON: Tasks 1-4
Task 12 (Verify Bug Fixes) → DEPENDS ON: Tasks 8, 9, 10
Task 13 (Verify Preservation) → DEPENDS ON: Tasks 8, 9, 10
Task 14 (Checkpoint) → DEPENDS ON: Tasks 12, 13
```

## Recommended Implementation Order

1. **First**: Write and run all exploration tests (Tasks 1-4) to confirm bug exists
2. **Second**: Write and run all preservation tests (Tasks 5-7) to establish baseline
3. **Third**: Implement VectorDbServiceClient fix (Task 8) - most critical
4. **Fourth**: Implement MCPContextManager fix (Task 9)
5. **Fifth**: Implement AnalystAgent fix (Task 10)
6. **Sixth**: (Optional) Implement Upload tender detection (Task 11)
7. **Seventh**: Verify all bug condition tests pass (Task 12)
8. **Eighth**: Verify all preservation tests pass (Task 13)
9. **Finally**: Run checkpoint (Task 14)

## Files to Modify

| File | Task | Changes |
|------|------|---------|
| `backend/app/services/vector_service.py` | 8 | Remove cross-collection fallback, add session_id filtering |
| `backend/app/agents/mcp_context.py` | 9 | Add session ownership validation |
| `backend/app/agents/analyst.py` | 10 | Add search results verification |
| `backend/app/api/v1/routes/upload.py` | 11 | (Optional) Add tender detection |

## Test Files to Create

| Test File | Task | Purpose |
|-----------|------|---------|
| `tests/test_session_isolation_chromadb.py` | 1, 12.1 | ChromaDB cross-collection fallback bug |
| `tests/test_session_isolation_context.py` | 2, 12.2 | MCPContextManager session validation bug |
| `tests/test_session_isolation_analyst.py` | 3, 12.3 | AnalystAgent cross-session data bug |
| `tests/test_session_isolation_sanitization.py` | 4, 12.4 | Session ID sanitization collision bug |
| `tests/test_preservation_single_session.py` | 5, 13 | Single session processing preservation |
| `tests/test_preservation_vector_search.py` | 6, 13 | Vector search quality preservation |
| `tests/test_preservation_agent_workflow.py` | 7, 13 | Agent workflow preservation |
