# Phase4 Eval Report

- total: 9
- passed: 9
- failed: 0

| id | task | scope | skill | rounds | fallback | clarify | guardrails | src_count | dom_ratio | coverage | symmetry | asym | abstained | reason |
|---|---|---|---|---:|---|---|---|---:|---:|---:|---:|---|---|---|
| p4-001 | simple_qa | default_kb_scope | qa_skill | 1 | False | False | - | 1 | 1.00 | 0.34 | - | - | False | phase4_rule_pass |
| p4-002 | collection_scoped_qa | collection_scope | scoped_qa_skill | 1 | False | False | - | 2 | 0.60 | 0.67 | - | - | False | phase4_rule_pass |
| p4-003 | multi_doc_synthesis | default_kb_scope | synthesis_skill | 2 | True | False | - | 2 | 0.60 | 0.67 | - | - | False | phase4_rule_pass |
| p4-004 | clarification_needed | default_kb_scope | clarify_skill | 1 | False | True | - | 0 | 1.00 | 0.00 | - | - | True | phase4_rule_pass |
| p4-005 | compare | default_kb_scope | compare_skill | 1 | False | False | - | 2 | 0.60 | 0.67 | 0.9 | False | False | phase4_rule_pass |
| p4-006 | compare | default_kb_scope | compare_skill | 1 | False | False | - | 2 | 0.90 | 0.67 | 0.4 | True | True | phase4_rule_pass |
| p4-007 | simple_qa | default_kb_scope | qa_skill | 1 | False | False | input_guardrail | 1 | 1.00 | 0.33 | - | - | False | phase4_rule_pass |
| p4-008 | simple_qa | default_kb_scope | qa_skill | 1 | False | False | - | 1 | 1.00 | 0.33 | - | - | False | phase4_rule_pass |
| p4-009 | abstain_or_insufficient_context | default_kb_scope | abstain_skill | 1 | False | False | - | 0 | 1.00 | 0.00 | - | - | True | phase4_rule_pass |
