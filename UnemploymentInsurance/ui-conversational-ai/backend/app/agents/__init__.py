"""
Agent topology for weekly UI eligibility certification.

See docs / README for full diagram. Per-turn pipeline:
  inbound_pii_guard
    → intent_analyzer
    → signal_extractor
    → context_agent
    → strategy_planner          (the brain)
        ├─ fraud_scorer
        ├─ eligibility_evaluator
        └─ document_collector
    → dialog_phraser
    → legal_relevance_guard     (drop → re-plan)
    → outbound_pii_guard
At conversation close:
    → adjudicator_report
"""
