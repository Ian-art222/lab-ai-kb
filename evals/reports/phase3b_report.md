# Phase3B Eval Report

- total: 9
- passed: 9
- failed: 0

| id | task | skill | scope | strategy | rounds | fallback | clarify | src_count | dom_ratio | coverage | citations | abstained | reason |
|---|---|---|---|---|---:|---|---|---:|---:|---:|---:|---|---|
| p3b-001 | simple_qa | qa_skill | default_kb_scope | single_pass_qa | 1 | False | False | 1 | 1.00 | 0.33 | 1 | False | phase3b_rule_pass |
| p3b-002 | collection_scoped_qa | scoped_qa_skill | collection_scope | scoped_retrieval | 1 | False | False | 2 | 0.60 | 0.67 | 2 | False | phase3b_rule_pass |
| p3b-003 | multi_doc_synthesis | synthesis_skill | default_kb_scope | coverage_oriented_synthesis | 2 | True | False | 3 | 0.60 | 1.00 | 3 | False | phase3b_rule_pass |
| p3b-004 | clarification_needed | clarify_skill | default_kb_scope | clarify_before_retrieval | 1 | False | True | 0 | 1.00 | 0.00 | 0 | True | phase3b_rule_pass |
| p3b-005 | compare | compare_skill | default_kb_scope | side_by_side_compare_retrieval | 1 | False | False | 2 | 0.60 | 0.67 | 3 | False | phase3b_rule_pass |
| p3b-006 | multi_doc_synthesis | synthesis_skill | default_kb_scope | coverage_oriented_synthesis | 1 | False | False | 3 | 0.50 | 1.00 | 4 | False | phase3b_rule_pass |
| p3b-007 | simple_qa | qa_skill | default_kb_scope | single_pass_qa | 1 | False | False | 2 | 0.85 | 0.67 | 2 | False | phase3b_rule_pass |
| p3b-008 | simple_qa | qa_skill | default_kb_scope | single_pass_qa | 1 | False | False | 1 | 1.00 | 0.33 | 1 | False | phase3b_rule_pass |
| p3b-009 | abstain_or_insufficient_context | abstain_skill | default_kb_scope | conservative_abstain | 1 | False | False | 0 | 1.00 | 0.00 | 0 | True | phase3b_rule_pass |
