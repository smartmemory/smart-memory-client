import pytest
from unittest.mock import patch
from smartmemory_client.client import SmartMemoryClient


@pytest.fixture
def client():
    return SmartMemoryClient(api_key="test-key", base_url="http://test-url")


@pytest.fixture
def mock_request(client):
    with patch.object(client, "_request") as mock:
        yield mock


class TestClientFullCoverage:
    # ============================================================================
    # Admin
    # ============================================================================
    def test_admin_methods(self, client, mock_request):
        client.orphaned_notes()
        mock_request.assert_called_with("GET", "/memory/admin/orphaned-notes")

        client.prune(dry_run=True)
        mock_request.assert_called_with(
            "POST",
            "/memory/admin/prune",
            params={"strategy": "old", "days": 365, "dry_run": True},
        )

        client.find_old_notes(days=30)
        mock_request.assert_called_with(
            "GET", "/memory/admin/old-notes", params={"days": 30}
        )

        client.self_monitor()
        mock_request.assert_called_with("GET", "/memory/admin/self-monitor")

        client.get_system_stats()
        mock_request.assert_called_with("GET", "/memory/admin/stats")

    # ============================================================================
    # Agents
    # ============================================================================
    def test_agent_methods(self, client, mock_request):
        client.create_agent("Agent 007", "Spy agent", roles=["read", "write"])
        mock_request.assert_called_with(
            "POST",
            "/memory/agents",
            json_body={
                "name": "Agent 007",
                "description": "Spy agent",
                "agent_config": {},
                "roles": ["read", "write"],
            },
        )

        client.list_agents()
        mock_request.assert_called_with("GET", "/memory/agents")

        client.get_agent("agent-123")
        mock_request.assert_called_with("GET", "/memory/agents/agent-123")

        client.delete_agent("agent-123")
        mock_request.assert_called_with("DELETE", "/memory/agents/agent-123")

    # ============================================================================
    # Analytics
    # ============================================================================
    def test_analytics_methods(self, client, mock_request):
        client.get_analytics_status()
        mock_request.assert_called_with("GET", "/memory/analytics/status")

        client.detect_drift()
        mock_request.assert_called_with(
            "GET", "/memory/analytics/drift", params={"time_window_days": 30}
        )

        client.detect_bias(["age"], sentiment_analysis=True)
        mock_request.assert_called_with(
            "POST",
            "/memory/analytics/bias",
            json_body={
                "protected_attributes": ["age"],
                "sentiment_analysis": True,
                "topic_analysis": None,
            },
        )

    # ============================================================================
    # API Keys
    # ============================================================================
    def test_api_key_methods(self, client, mock_request):
        client.create_api_key("New Key", ["read"])
        mock_request.assert_called_with(
            "POST",
            "/memory/api-keys",
            json_body={"name": "New Key", "scopes": ["read"], "expires_in_days": None},
        )

        client.list_api_keys()
        mock_request.assert_called_with("GET", "/memory/api-keys")

        client.revoke_api_key("key-123")
        mock_request.assert_called_with("DELETE", "/memory/api-keys/key-123")

    # ============================================================================
    # Auth
    # ============================================================================
    def test_auth_methods(self, client, mock_request):
        # signup/login/password-reset removed — those routes are deleted; Clerk handles auth.
        client.refresh_token("refresh-token")
        mock_request.assert_called_with(
            "POST", "/auth/refresh", json_body={"refresh_token": "refresh-token"}
        )

        client.logout()
        mock_request.assert_called_with("POST", "/auth/logout")

        client.get_me()
        mock_request.assert_called_with("GET", "/auth/me")

        client.logout_all()
        mock_request.assert_called_with("POST", "/auth/logout-all")

        client.update_llm_keys(openai_key="key")
        mock_request.assert_called_with(
            "PATCH",
            "/auth/llm-keys",
            json_body={
                "openai_key": "key",
                "anthropic_key": None,
                "groq_key": None,
                "gemini_key": None,
            },
        )

        client.update_llm_keys(gemini_key="gk")
        mock_request.assert_called_with(
            "PATCH",
            "/auth/llm-keys",
            json_body={
                "openai_key": None,
                "anthropic_key": None,
                "groq_key": None,
                "gemini_key": "gk",
            },
        )

        client.get_llm_keys()
        mock_request.assert_called_with("GET", "/auth/llm-keys")

    # ============================================================================
    # Evolve
    # ============================================================================
    def test_evolve_methods(self, client, mock_request):
        client.trigger_evolution()
        mock_request.assert_called_with("POST", "/memory/evolution/trigger")

        client.run_dream_phase()
        mock_request.assert_called_with("POST", "/memory/evolution/dream")

        client.get_evolution_status()
        mock_request.assert_called_with("GET", "/memory/evolution/status")

    # ============================================================================
    # Governance
    # ============================================================================
    def test_governance_methods(self, client, mock_request):
        client.run_governance_analysis(query="test", top_k=50)
        mock_request.assert_called_with(
            "POST",
            "/memory/governance/run-analysis",
            json_body={"query": "test", "top_k": 50, "memory_items": []},
        )

        client.list_violations(severity="high")
        mock_request.assert_called_with(
            "GET",
            "/memory/governance/violations",
            params={"severity": "high", "auto_fixable_only": False},
        )

        client.get_violation("v-123")
        mock_request.assert_called_with("GET", "/memory/governance/violations/v-123")

        client.apply_governance_decision("v-123", action="reject")
        mock_request.assert_called_with(
            "POST",
            "/memory/governance/apply-decision",
            json_body={
                "violation_id": "v-123",
                "action": "reject",
                "rationale": "",
                "decided_by": "human",
            },
        )

        client.auto_fix_violations(confidence_threshold=0.9)
        mock_request.assert_called_with(
            "POST",
            "/memory/governance/auto-fix",
            json_body={"confidence_threshold": 0.9},
        )

        client.get_governance_summary()
        mock_request.assert_called_with("GET", "/memory/governance/summary")

    # ============================================================================
    # Ontology
    # ============================================================================
    def test_ontology_methods(self, client, mock_request):
        client.run_inference([{"text": "chunk"}])
        mock_request.assert_called_with(
            "POST",
            "/memory/ontology/inference/run",
            json_body={
                "registry_id": "default",
                "raw_chunks": [{"text": "chunk"}],
                "params": {},
            },
        )

        client.list_registries()
        mock_request.assert_called_with("GET", "/memory/ontology/registries")

        client.create_registry("My Registry")
        mock_request.assert_called_with(
            "POST",
            "/memory/ontology/registries",
            json_body={"name": "My Registry", "description": "", "domain": "general"},
        )

        client.get_registry_snapshot("reg-1")
        mock_request.assert_called_with(
            "GET", "/memory/ontology/registry/reg-1/snapshot", params=None
        )

        client.apply_changeset("reg-1", {"add": []})
        mock_request.assert_called_with(
            "POST",
            "/memory/ontology/registry/reg-1/apply",
            json_body={"base_version": "", "changeset": {"add": []}, "message": ""},
        )

        client.list_registry_snapshots("reg-1")
        mock_request.assert_called_with(
            "GET", "/memory/ontology/registry/reg-1/snapshots", params={"limit": 50}
        )

        client.get_registry_changelog("reg-1")
        mock_request.assert_called_with(
            "GET", "/memory/ontology/registry/reg-1/changelog", params={"limit": 50}
        )

        client.rollback_registry("reg-1", target_version="v1")
        mock_request.assert_called_with(
            "POST",
            "/memory/ontology/registry/reg-1/rollback",
            json_body={"target_version": "v1", "message": ""},
        )

        client.export_registry("reg-1")
        mock_request.assert_called_with(
            "GET", "/memory/ontology/registry/reg-1/export", params={}
        )

        client.import_registry("reg-1", {"data": "test"})
        mock_request.assert_called_with(
            "POST",
            "/memory/ontology/registry/reg-1/import",
            json_body={"data": {"data": "test"}, "message": ""},
        )

        client.list_enrichment_providers()
        mock_request.assert_called_with("GET", "/memory/ontology/enrichment/providers")

        client.run_enrichment(["entity1"])
        mock_request.assert_called_with(
            "POST",
            "/memory/ontology/enrichment/run",
            json_body={
                "provider": "wikipedia",
                "entities": ["entity1"],
                "user_id": None,
            },
        )

        client.run_grounding_ontology("item-1", ["cand1"])
        mock_request.assert_called_with(
            "POST",
            "/memory/ontology/grounding/run",
            json_body={
                "grounder": "wikipedia",
                "item_id": "item-1",
                "candidates": ["cand1"],
                "user_id": None,
            },
        )

    # ============================================================================
    # Pipeline
    # ============================================================================
    def test_pipeline_methods(self, client, mock_request):
        client.run_extraction_stage("content")
        mock_request.assert_called_with(
            "POST",
            "/memory/pipeline/extraction",
            json_body={"content": "content", "extractor_name": "llm"},
        )

        client.run_storage_stage({"data": "extracted"})
        mock_request.assert_called_with(
            "POST",
            "/memory/pipeline/storage",
            json_body={
                "extracted_data": {"data": "extracted"},
                "storage_strategy": "standard",
            },
        )

        client.run_linking_stage([{"entity": "e1"}])
        mock_request.assert_called_with(
            "POST",
            "/memory/pipeline/linking",
            json_body={
                "stored_entities": [{"entity": "e1"}],
                "linking_algorithm": "exact",
            },
        )

        client.run_enrichment_stage([{"entity": "e1"}])
        mock_request.assert_called_with(
            "POST",
            "/memory/pipeline/enrichment",
            json_body={
                "linked_entities": [{"entity": "e1"}],
                "enrichment_types": ["sentiment", "topics"],
            },
        )

        client.run_grounding_stage([{"entity": "e1"}])
        mock_request.assert_called_with(
            "POST",
            "/memory/pipeline/grounding",
            json_body={
                "enriched_entities": [{"entity": "e1"}],
                "grounding_sources": ["wikipedia"],
            },
        )

        client.get_pipeline_state("pipe-1")
        mock_request.assert_called_with(
            "GET", "/memory/pipeline/pipe-1/state", params=None
        )

        client.reset_pipeline("pipe-1")
        mock_request.assert_called_with("DELETE", "/memory/pipeline/pipe-1")

        client.clear_run_state("pipe-1", "run-1")
        mock_request.assert_called_with("DELETE", "/memory/pipeline/pipe-1/run/run-1")

    # ============================================================================
    # Subscription
    # ============================================================================
    def test_subscription_methods(self, client, mock_request):
        client.create_checkout_session("pro")
        mock_request.assert_called_with(
            "POST",
            "/subscription/checkout",
            json_body={"tier": "pro", "billing_period": "monthly", "trial_days": None},
        )

        client.upgrade_subscription("pro")
        mock_request.assert_called_with(
            "POST",
            "/subscription/upgrade",
            json_body={
                "tier": "pro",
                "billing_period": "monthly",
                "payment_method_id": None,
                "use_checkout": False,
            },
        )

        client.get_subscription()
        mock_request.assert_called_with("GET", "/subscription/current")

        client.cancel_subscription(immediately=True)
        mock_request.assert_called_with(
            "POST", "/subscription/cancel", params={"immediately": True}
        )

    # ============================================================================
    # Teams
    # ============================================================================
    def test_teams_methods(self, client, mock_request):
        client.create_team("Team A")
        mock_request.assert_called_with(
            "POST",
            "/memory/teams",
            json_body={
                "name": "Team A",
                "description": None,
                "data_classification": "internal",
                "cost_center": None,
            },
        )

        client.list_teams()
        mock_request.assert_called_with("GET", "/memory/teams")

        client.get_team("team-1")
        mock_request.assert_called_with("GET", "/memory/teams/team-1")

        client.update_team("team-1", name="Team B")
        mock_request.assert_called_with(
            "PATCH", "/memory/teams/team-1", json_body={"name": "Team B"}
        )

        client.delete_team("team-1")
        mock_request.assert_called_with("DELETE", "/memory/teams/team-1")

        client.list_team_members("team-1")
        mock_request.assert_called_with("GET", "/memory/teams/team-1/members")

        client.add_team_member("team-1", "user-1")
        mock_request.assert_called_with(
            "POST",
            "/memory/teams/team-1/members",
            json_body={"user_id": "user-1", "role": "member"},
        )

        client.update_team_member("team-1", "user-1", "admin")
        mock_request.assert_called_with(
            "PATCH", "/memory/teams/team-1/members/user-1", json_body={"role": "admin"}
        )

        client.remove_team_member("team-1", "user-1")
        mock_request.assert_called_with("DELETE", "/memory/teams/team-1/members/user-1")

        client.get_team_permissions("team-1")
        mock_request.assert_called_with("GET", "/memory/teams/team-1/permissions")

    # ============================================================================
    # Temporal
    # ============================================================================
    def test_temporal_methods(self, client, mock_request):
        client.get_history("item-1")
        mock_request.assert_called_with(
            "GET", "/memory/temporal/item-1/history", params={"limit": 100}
        )

        client.time_travel("2023-01-01T00:00:00Z")
        mock_request.assert_called_with(
            "GET", "/memory/temporal/at/2023-01-01T00:00:00Z", params={"limit": 100}
        )

        client.get_item_at_time("item-1", "2023-01-01T00:00:00Z")
        mock_request.assert_called_with(
            "GET", "/memory/temporal/item-1/at/2023-01-01T00:00:00Z"
        )

        client.get_changes("item-1")
        mock_request.assert_called_with(
            "GET", "/memory/temporal/item-1/changes", params={}
        )

        client.compare_versions("item-1", 1, 2)
        mock_request.assert_called_with(
            "POST", "/memory/temporal/item-1/compare", params={"v1": 1, "v2": 2}
        )

        client.rollback("item-1", to_version=1)
        mock_request.assert_called_with(
            "POST", "/memory/temporal/item-1/rollback", params={"to_version": 1}
        )

        client.get_audit_trail("item-1")
        mock_request.assert_called_with(
            "GET", "/memory/temporal/item-1/audit", params={}
        )

        client.search_during_range("query", "start", "end")
        mock_request.assert_called_with(
            "GET",
            "/memory/temporal/search/during",
            params={
                "query": "query",
                "start_time": "start",
                "end_time": "end",
                "limit": 100,
            },
        )

        client.generate_compliance_report("start", "end")
        mock_request.assert_called_with(
            "GET",
            "/memory/temporal/compliance/report",
            params={"start_date": "start", "end_date": "end", "report_type": "HIPAA"},
        )

        client.get_relationship_history("rel-1")
        mock_request.assert_called_with(
            "GET", "/memory/temporal/relationships/rel-1/history"
        )

        client.get_relationships_at_time("time")
        mock_request.assert_called_with(
            "GET", "/memory/temporal/relationships/at/time", params={"limit": 100}
        )

        client.get_relationship_valid_periods("rel-1")
        mock_request.assert_called_with(
            "GET", "/memory/temporal/relationships/rel-1/valid-periods"
        )

    # ============================================================================
    # Usage
    # ============================================================================
    def test_usage_methods(self, client, mock_request):
        client.get_usage_dashboard()
        mock_request.assert_called_with("GET", "/usage/dashboard")

        client.get_usage_limits()
        mock_request.assert_called_with("GET", "/usage/limits")

        client.get_current_usage()
        mock_request.assert_called_with("GET", "/usage/current")

        client.get_available_tiers()
        mock_request.assert_called_with("GET", "/usage/tiers")

    # ============================================================================
    # Webhooks
    # ============================================================================
    def test_webhooks_methods(self, client, mock_request):
        client.trigger_stripe_webhook({"id": "evt_1"}, "sig")
        mock_request.assert_called_with(
            "POST",
            "/webhooks/stripe",
            json_body={"id": "evt_1"},
            headers={"stripe-signature": "sig"},
        )

    # ============================================================================
    # Zettelkasten
    # ============================================================================
    def test_zettelkasten_methods(self, client, mock_request):
        client.get_backlinks("note-1")
        mock_request.assert_called_with("GET", "/memory/zettel/note-1/backlinks")

        client.get_forward_links("note-1")
        mock_request.assert_called_with("GET", "/memory/zettel/note-1/forward-links")

        client.get_connections("note-1")
        mock_request.assert_called_with("GET", "/memory/zettel/note-1/connections")

        client.get_clusters()
        mock_request.assert_called_with(
            "GET",
            "/memory/zettel/clusters",
            params={"min_size": 3, "algorithm": "louvain"},
        )

        client.get_hubs()
        mock_request.assert_called_with(
            "GET", "/memory/zettel/hubs", params={"min_connections": 5, "limit": 20}
        )

        client.get_bridges()
        mock_request.assert_called_with(
            "GET", "/memory/zettel/bridges", params={"limit": 20}
        )

        client.get_discoveries("note-1")
        mock_request.assert_called_with(
            "GET",
            "/memory/zettel/note-1/discoveries",
            params={"max_distance": 3, "min_surprise": 0.5},
        )

        client.get_path("note-1", "note-2")
        mock_request.assert_called_with(
            "GET", "/memory/zettel/note-1/path/note-2", params={"max_paths": 5}
        )

        client.parse_wikilinks("content")
        mock_request.assert_called_with(
            "POST",
            "/memory/zettel/wikilink/parse",
            params={"content": "content", "auto_create": True},
        )

        client.resolve_wikilink("link")
        mock_request.assert_called_with(
            "GET", "/memory/zettel/wikilink/resolve", params={"link": "link"}
        )

        client.get_subgraph("note-1")
        mock_request.assert_called_with(
            "GET",
            "/memory/zettel/note-1/graph",
            params={"depth": 2, "include_metadata": True},
        )

        client.detect_concept_emergence()
        mock_request.assert_called_with(
            "GET", "/memory/zettel/concept-emergence", params={"limit": 20}
        )

        client.suggest_related_notes("note-1")
        mock_request.assert_called_with(
            "GET", "/memory/zettel/note-1/suggestions", params={"count": 5}
        )

        client.random_walk_discovery("note-1")
        mock_request.assert_called_with(
            "GET", "/memory/zettel/note-1/random-walk", params={"length": 5}
        )

        client.find_notes_by_tag("tag")
        mock_request.assert_called_with(
            "GET", "/memory/zettel/by-tag/tag", params={"limit": 100}
        )

        client.find_notes_by_property("key", "val")
        mock_request.assert_called_with(
            "GET",
            "/memory/zettel/by-property",
            params={"key": "key", "value": "val", "limit": 100},
        )

        client.find_notes_mentioning("entity")
        mock_request.assert_called_with(
            "GET", "/memory/zettel/mentioning/entity", params={"limit": 100}
        )

        client.query_by_dynamic_relation("src", "rel")
        mock_request.assert_called_with(
            "GET", "/memory/zettel/by-relation/src/rel", params={"limit": 100}
        )
