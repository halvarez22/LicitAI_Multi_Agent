# Implementation Plan: Enhanced Analyst Agent

## Overview

This implementation plan adds enhanced extraction capabilities to the AnalystAgent for extracting technical solvency (solvencia técnica) and contractual conditions (condiciones contractuales) from Mexican bidding documents. The implementation uses Python with Pydantic for data validation and follows the existing AnalystAgent architecture.

## Tasks

- [x] 1. Set up project structure and core data models
  - Create directory structure for new modules
  - Define Pydantic models for Solvencia Técnica
  - Define Pydantic models for Condiciones Contractuales
  - Define Pydantic models for Checklist Consolidado
  - _Requirements: 16.1, 16.2, 17.1, 17.2, 18.1, 18.2_

- [x] 2. Implement normalization layer
  - [x] 2.1 Create normalization functions for solvencia técnica
    - Implement `normalize_experiencia_minima()` function
    - Implement `normalize_curriculum_empresa()` function
    - Implement `normalize_plantilla_personal()` function
    - Implement `normalize_equipamiento()` function
    - Implement `normalize_infraestructura()` function
    - Implement `normalize_normas_certificaciones()` function
    - Implement `normalize_referencias()` function
    - _Requirements: 1.4, 2.5, 3.4, 4.4, 5.5, 6.5_

  - [x] 2.2 Create normalization functions for condiciones contractuales
    - Implement `normalize_tipo_contrato()` function
    - Implement `normalize_penalizaciones()` function
    - Implement `normalize_pagos()` function
    - Implement `normalize_garantia_cumplimiento()` function
    - Implement `normalize_garantia_vicios_ocultos()` function
    - _Requirements: 7.4, 8.5, 9.5, 10.5, 11.4_

  - [x] 2.3 Create main normalization orchestrator
    - Implement `normalize_solvencia_tecnica()` main function
    - Implement `normalize_condiciones_contractuales()` main function
    - _Requirements: 16.1, 16.2, 17.1, 17.2_

- [x] 3. Implement classification engine
  - [x] 3.1 Create requirement classifier
    - Implement keyword-based classification logic
    - Add detection for "deberá", "es obligatorio", "es requisito" → obligatorio
    - Add detection for "deseable", "preferible", "se valorará" → deseable
    - Add detection for "cuando", "si ", "en caso de" → condicional
    - Implement default fallback to "obligatorio" with uncertainty flag
    - _Requirements: 12.1, 12.2, 12.3, 12.4_

  - [x] 3.2 Create page and clause association logic
    - Implement extraction of page numbers from context
    - Implement extraction of clause/inciso numbers
    - Handle "No especificado" fallback
    - _Requirements: 13.1, 13.2, 13.3, 13.4, 13.5_

- [x] 4. Implement consolidation engine
  - [x] 4.1 Create checklist consolidation logic
    - Implement merge of solvencia técnica and condiciones contractuales
    - Add classification metadata to each requirement
    - Add source location (page, clause) to each requirement
    - _Requirements: 18.1, 18.2_

  - [x] 4.2 Implement priority ordering
    - Implement ordering by classification (obligatorio → deseable → condicional)
    - Implement category priority (garantías, documentación legal, solvencia técnica, propuesta económica)
    - Add `orden_entrega` field to each requirement
    - _Requirements: 14.1, 14.2, 14.3, 14.4_

- [x] 5. Integrate with existing AnalystAgent
  - [x] 5.1 Add new search patterns
    - Add SOLVENCIA_KEYWORDS for semantic search
    - Add CONTRACTUAL_KEYWORDS for semantic search
    - _Requirements: 15.1_

  - [x] 5.2 Add enhanced extraction prompts
    - Create ENHANCED_EXTRACTION_PROMPT template
    - Add prompt for solvencia técnica extraction
    - Add prompt for condiciones contractuales extraction
    - _Requirements: 15.1, 15.3_

  - [x] 5.3 Modify AnalystAgent.process() method
    - Add calls to new extraction pipelines
    - Integrate normalization layer output
    - Add checklist_consolidado to AgentOutput
    - _Requirements: 16.1, 16.2, 17.1, 17.2, 18.1, 18.2, 18.3, 18.4_

  - [x] 5.4 Add configuration settings
    - Add ENHANCED_EXTRACTION_ENABLED setting
    - Add EXTRACTION_CONFIDENCE_THRESHOLD setting
    - Add DEFAULT_CLASSIFICATION setting
    - _Requirements: 15.1_

- [x] 6. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 7. Write unit tests for classification engine
  - [x]* 7.1 Write property test for classification keyword detection
    - **Property 14: Requisito classification by keyword**
    - **Validates: Requirements 12.1, 12.2**

  - [x]* 7.2 Write property test for ambiguous classification fallback
    - **Property 15: Ambiguous classification fallback**
    - **Validates: Requirements 12.4**

  - [x] 7.3 Write unit tests for classify_requirement function
    - Test obligatory keywords detection
    - Test desirable keywords detection
    - Test conditional keywords detection
    - Test default fallback behavior
    - _Requirements: 12.1, 12.2, 12.3, 12.4_

- [x] 8. Write unit tests for normalization functions
  - [x]* 8.1 Write property test for experiencia mínima extraction
    - **Property 1: Experiencia mínima extraction**
    - **Validates: Requirements 1.1, 1.2, 1.3, 1.4**

  - [x]* 8.2 Write property test for missing experience requirements fallback
    - **Property 2: Missing experience requirements fallback**
    - **Validates: Requirements 1.5**

  - [x]* 8.3 Write property test for empty plantilla fallback
    - **Property 5: Empty plantilla fallback**
    - **Validates: Requirements 3.5**

  - [x] 8.4 Write unit tests for normalize_solvencia_tecnica
    - Test complete normalization flow
    - Test fallback values for missing fields
    - _Requirements: 16.1, 16.2, 16.3_

  - [x] 8.5 Write unit tests for normalize_condiciones_contractuales
    - Test complete normalization flow
    - Test fallback values for missing fields
    - _Requirements: 17.1, 17.2, 17.3_

- [x] 9. Write unit tests for consolidation engine
  - [x]* 9.1 Write property test for checklist ordering by classification
    - **Property 17: Checklist ordering by classification**
    - **Validates: Requirements 14.1, 14.2**

  - [x]* 9.2 Write property test for consolidated checklist structure and ordering
    - **Property 21: Consolidated checklist structure and ordering**
    - **Validates: Requirements 18.1, 18.2, 18.3, 18.4**

  - [x] 9.3 Write unit tests for consolidate_checklist function
    - Test merge of solvencia and condiciones
    - Test ordering by priority
    - Test orden_entrega field assignment
    - _Requirements: 14.1, 14.2, 14.3, 18.1, 18.2_

- [x] 10. Write integration tests for extraction pipeline
  - [x] 10.1 Create test fixtures
    - Create sample OCR text with solvencia requirements
    - Create sample OCR text with contractual terms
    - Create edge case test data (empty sections, ambiguous language)
    - _Requirements: 15.4, 15.5_

  - [x] 10.2 Write integration test for full extraction pipeline
    - Test complete flow from document to output
    - Verify solvencia_tecnica structure
    - Verify condiciones_contractuales structure
    - Verify checklist_consolidado structure and ordering
    - _Requirements: 16.1, 16.2, 17.1, 17.2, 18.1, 18.2, 18.3, 18.4_

  - [x] 10.3 Write integration tests for different document types
    - Test with Licitación pública format
    - Test with Invitación restringida format
    - Test with Adjudicación directa format
    - _Requirements: 15.2, 15.3, 18.1_

- [x] 11. Final checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests validate universal correctness properties
- Unit tests validate specific examples and edge cases
- Implementation uses Python with Pydantic for data validation
- Backward compatibility with existing AnalystAgent output is maintained