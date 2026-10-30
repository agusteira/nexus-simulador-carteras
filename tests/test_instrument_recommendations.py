import unittest
import tempfile
from datetime import date, datetime, timedelta, timezone

from nexus.instrument_recommendations import (
    evaluate_recommendation, recommendation_decide_category, recommendation_rank,
)
from nexus.instrument_rules import evaluate_candidate
from nexus.instrument_knowledge import KnowledgeStore
from nexus.instrument_research import ResearchLimits, research_instruments


TODAY = date(2026, 10, 30)
CONTEXT = {
    "selection_scope": "instrument_recommendation",
    "category": "Renta variable",
    "profile": "MODERADO",
    "horizon_months": 48,
    "objective": "Crecimiento",
    "budget": 100_000,
    "allocation_weight": 20,
    "tolerance": 30,
    "currency": "ARS",
    "liquidity_required": 20,
}


def complete_fci(cid, *, fee=1.0, minimum=1000, name="Fondo"):
    record = {
        "canonical_id": cid, "instrument_type": "FCI", "market": "AR:FCI",
        "name": name, "category": "Renta variable", "exposure": "equity",
        "quotation_currency": "ARS", "minimum": minimum, "settlement_days": 1,
        "fund_open": True, "subscription_open": True, "redemption_open": True,
        "qualified_only": False, "horizon": "Largo Plazo", "duration": None,
        "fund_fee_annual_pct": fee, "fund_fee_components_annual_pct": {
            "administracion_gerente": fee, "administracion_depositaria": 0.0,
            "gasto_ordinario_gestion": 0.0,
        }, "raw_fees": {"administracion_gerente": fee, "administracion_depositaria": 0.0,
                        "gasto_ordinario_gestion": 0.0}, "entry_fee_pct": None,
        "fund_aum": None, "underlying_id": cid.rsplit(":", 1)[0],
        "evidence": [],
    }
    observed = "2026-10-30T12:00:00+00:00"
    expires = "2026-11-06T23:59:59+00:00"
    fields = ["canonical_id", "instrument_type", "market", "name", "category",
              "exposure", "quotation_currency", "minimum", "settlement_days",
              "fund_open", "subscription_open", "redemption_open", "qualified_only",
              "horizon", "fund_fee_annual_pct"]
    record["evidence"].append({
        "kind": "observed", "source": "Fixture CAFCI", "url": "https://example.test/catalog",
        "observed_at": observed, "data_date": "2026-10-30", "expires_at": expires,
        "fields": {key: record[key] for key in fields},
        "raw_source_fields": {"fees": record["raw_fees"]},
    })
    return record


class RecommendationContractTests(unittest.TestCase):
    def _cedear(self, *, observed_at=None, ordinary="ORDINARIAS"):
        now = datetime.now(timezone.utc)
        observed = observed_at or now
        expires = observed + timedelta(minutes=15)
        cid = "CEDEAR:GENERIC:BYMA"
        record = {
            "canonical_id": cid, "instrument_type": "CEDEAR", "market": "BYMA",
            "ticker": "GENERIC", "name": "Generic ordinary CEDEAR", "quotation_currency": "ARS",
            "category": "Renta variable", "exposure": "equity", "underlying_type_source": ordinary,
            "reference_offer_price": 100, "reference_offer_quantity": 20,
            "reference_bid_price": 99, "reference_bid_quantity": 15,
            "quote_volume_amount": 100000, "settlement_days": 1,
            "unit_price": None, "quote_data_date": None,
            "market_unit_rule": {
                "nominal": 1, "rule_id": "BYMA17710_CEDEAR_VN1",
                "source": "https://data-widgets.byma.com.ar/wp-content/uploads/2020/08/BYMA-COM-17710-Modificacion-de-unidad-minima-de-negociacion-CEDEAR.pdf",
                "published_at": "2020-08-14",
            },
            "evidence": [],
        }
        identity_fields = {key: record[key] for key in (
            "canonical_id", "instrument_type", "market", "ticker", "name",
            "category", "exposure", "underlying_type_source",
        )}
        record["evidence"].append({
            "kind": "observed", "scope": "product_identity", "source": "Ficha BYMA",
            "url": "https://example.test/byma/product", "observed_at": now.isoformat(),
            "data_date": None, "expires_at": (now + timedelta(days=30)).isoformat(),
            "fields": identity_fields,
        })
        quote_fields = {key: record[key] for key in (
            "canonical_id", "instrument_type", "ticker", "market", "quotation_currency",
            "reference_offer_price", "reference_offer_quantity", "reference_bid_price",
            "reference_bid_quantity", "quote_volume_amount",
            "settlement_days",
        )}
        record["evidence"].append({
            "kind": "observed", "scope": "market_snapshot", "source": "BYMADATA",
            "url": "https://example.test/byma/quote", "observed_at": observed.isoformat(),
            "data_date": None, "expires_at": expires.isoformat(), "fields": quote_fields,
        })
        return record

    def _fixed_candidate(self, category, holdings):
        candidate = complete_fci("AR:FCI:FIXED:1")
        candidate["category"] = category
        candidate["exposure"] = "inflation" if category == "Renta fija inflación" else "fx"
        candidate["exposure_basis"] = "mandate"
        candidate["horizon"] = "Largo Plazo"
        candidate["duration"] = "Mayor a 1 y Menor Igual 3 Años"
        candidate["evidence"][0]["fields"].update({
            "category": category, "exposure": candidate["exposure"],
            "horizon": candidate["horizon"], "duration": candidate["duration"],
        })
        candidate["holdings_details"] = holdings
        candidate["holdings_date"] = "2026-10-20"
        candidate["evidence"].append({
            "kind": "observed", "source": "Fixture CAFCI holdings",
            "url": "https://example.test/holdings", "observed_at": "2026-10-20T12:00:00+00:00",
            "data_date": "2026-10-20", "expires_at": "2026-11-24T23:59:59+00:00",
            "fields": {"holdings_details": holdings, "holdings_date": "2026-10-20"},
        })
        return candidate

    def test_scope_dispatch_and_strict_default_stays_strict(self):
        candidate = complete_fci("AR:FCI:DISPATCH:1")
        legacy_context = dict(CONTEXT)
        legacy_context.pop("selection_scope")
        selected_scope = evaluate_candidate(candidate, legacy_context, today=TODAY)
        recommendation = evaluate_candidate(candidate, CONTEXT, today=TODAY)
        self.assertNotIn("selection_scope", selected_scope)
        self.assertEqual(recommendation["selection_scope"], "instrument_recommendation")

    def test_no_fallback_when_required_fact_is_missing(self):
        candidate = complete_fci("AR:FCI:GENERIC:1")
        candidate["qualified_only"] = None
        candidate["evidence"][0]["fields"].pop("qualified_only")
        result = evaluate_recommendation(candidate, CONTEXT, today=TODAY)
        self.assertFalse(result["eligible"])
        self.assertEqual(result["decision"], "INFORMACION_INSUFICIENTE")
        self.assertIn("qualified_only", result["missing_fields"])
        self.assertEqual(result["execution_checks"]["status"], "PENDIENTE_INTERMEDIARIO")

    def test_lower_published_fund_expense_wins_without_identity_preference(self):
        familiar = complete_fci("AR:FCI:SPYLIKE:1", fee=1.2, name="Known commercial label")
        candidate = complete_fci("AR:FCI:XYZ:1", fee=0.4, name="Unfamiliar generic")
        familiar["familiar"] = True
        ranked = recommendation_rank([familiar, candidate], CONTEXT, today=TODAY)
        self.assertEqual(ranked[0]["canonical_id"], candidate["canonical_id"])
        self.assertTrue(ranked[0]["eligible"])
        familiar["raw_fees"]["administracion_gerente"] = 0.2
        familiar["evidence"][0]["raw_source_fields"]["fees"] = dict(familiar["raw_fees"])
        familiar["fund_fee_components_annual_pct"] = dict(familiar["raw_fees"])
        familiar["fund_fee_annual_pct"] = 0.2
        candidate["raw_fees"]["administracion_gerente"] = 1.5
        candidate["evidence"][0]["raw_source_fields"]["fees"] = dict(candidate["raw_fees"])
        candidate["fund_fee_components_annual_pct"] = dict(candidate["raw_fees"])
        candidate["fund_fee_annual_pct"] = 1.5
        reversed_costs = recommendation_rank([candidate, familiar], CONTEXT, today=TODAY)
        self.assertEqual(reversed_costs[0]["canonical_id"], familiar["canonical_id"])

    def test_mixed_family_rank_is_deterministic_and_preserves_comparable_fee_order(self):
        expensive = complete_fci("AR:FCI:A:1", fee=2)
        cheaper = complete_fci("AR:FCI:Z:1", fee=1)
        share = self._cedear()
        candidates = [expensive, share, cheaper]
        outputs = []
        for pool in (candidates, list(reversed(candidates)), [share, expensive, cheaper]):
            outputs.append([item["canonical_id"] for item in recommendation_rank(pool, CONTEXT, today=TODAY)
                            if item["eligible"]])
        self.assertEqual(outputs[0], outputs[1])
        self.assertEqual(outputs[1], outputs[2])
        self.assertLess(outputs[0].index(cheaper["canonical_id"]), outputs[0].index(expensive["canonical_id"]))
        choice = recommendation_decide_category(candidates, CONTEXT, original_id=expensive["canonical_id"], today=TODAY)
        self.assertEqual(choice["decision"], "PROPONER_ALTERNATIVA_COMPATIBLE")
        self.assertIn("gasto anual de fondo publicado", choice["comparison"]["reason"])

    def test_budget_change_excludes_candidate_below_published_minimum(self):
        candidate = complete_fci("AR:FCI:XYZ:1", minimum=1500)
        low_budget = dict(CONTEXT, budget=1400)
        result = evaluate_recommendation(candidate, low_budget, today=TODAY)
        self.assertFalse(result["eligible"])
        self.assertIn("R_PRESUPUESTO_MINIMO", result["rule_ids"])

    def test_unknown_broker_fees_remain_execution_check_not_recommendation_gate(self):
        candidate = complete_fci("AR:FCI:XYZ:1")
        result = evaluate_recommendation(candidate, CONTEXT, today=TODAY)
        self.assertTrue(result["eligible"])
        self.assertEqual(result["execution_checks"]["status"], "PENDIENTE_INTERMEDIARIO")
        self.assertIn("broker_fees", result["execution_checks"]["missing_fields"])

    def test_string_percentages_in_raw_cafci_fee_facts_are_derived_without_rewriting_source(self):
        candidate = complete_fci("AR:FCI:STRINGS:1", fee=0.75)
        candidate["raw_fees"] = {
            "administracion_gerente": "0.5",
            "administracion_depositaria": "0.25",
            "gasto_ordinario_gestion": "0.0",
        }
        candidate["fund_fee_components_annual_pct"] = {
            "administracion_gerente": 0.5,
            "administracion_depositaria": 0.25,
            "gasto_ordinario_gestion": 0.0,
        }
        candidate["evidence"][0]["raw_source_fields"]["fees"] = dict(candidate["raw_fees"])
        result = evaluate_recommendation(candidate, CONTEXT, today=TODAY)
        self.assertTrue(result["eligible"])
        self.assertEqual(result["record"]["derived_fund_fee_annual_pct"], 0.75)
        self.assertEqual(result["record"]["raw_fees"]["administracion_gerente"], "0.5")
        self.assertEqual(result["ranking_factors"]["published_fund_fees"], 0.75)
        self.assertFalse(any("gastos anuales" in warning for warning in result["selection_warnings"]))
        self.assertTrue(any("Gastos anuales" in item and "0.75%" in item
                            for item in result["selection_explanation"]))
        self.assertTrue(any("Mínimo publicado" in item and "presupuesto simulado" in item
                            for item in result["selection_explanation"]))
        self.assertTrue(any("Horizonte CAFCI" in item and "T+1" in item
                            for item in result["selection_explanation"]))

    def test_normalized_fee_mismatch_requires_review_instead_of_claiming_published_fee(self):
        candidate = complete_fci("AR:FCI:FEE-MISMATCH:1", fee=1.4)
        candidate["fund_fee_annual_pct"] = 99.0
        result = evaluate_recommendation(candidate, CONTEXT, today=TODAY)
        self.assertFalse(result["eligible"])
        self.assertEqual(result["decision"], "REQUIERE_REVISION")
        self.assertIn("R_CONTRADICCION", result["rule_ids"])
        self.assertEqual(result["ranking_factors"]["published_fund_fees"], 1.4)
        self.assertNotIn("gasto incompleto", " ".join(result["selection_explanation"]).casefold())

    def test_current_economic_issuer_from_byma_identity_enforces_concentration_limit(self):
        candidate = self._cedear()
        candidate["underlying_name"] = "Foreign Issuer Inc"
        candidate["underlying_issuer_role"] = "economic_issuer"
        identity = candidate["evidence"][0]["fields"]
        identity.update({"underlying_name": candidate["underlying_name"],
                         "underlying_issuer_role": candidate["underlying_issuer_role"]})
        high_weight = dict(CONTEXT, allocation_weight=60)
        result = evaluate_recommendation(candidate, high_weight, today=TODAY)
        self.assertFalse(result["eligible"])
        self.assertIn("R_CONCENTRACION_EMISOR", result["rule_ids"])
        check = result["concentration_checks"]["issuer"]
        self.assertEqual(check["status"], "known")
        self.assertEqual(check["total_weight_percent"], 60)

        at_limit = evaluate_recommendation(candidate, dict(CONTEXT, allocation_weight=50), today=TODAY)
        self.assertNotIn("R_CONCENTRACION_EMISOR", at_limit["rule_ids"])

    def test_depositary_name_alone_does_not_count_as_economic_issuer_concentration(self):
        candidate = self._cedear()
        candidate["issuer"] = "Depositary Bank"
        candidate["issuer_role"] = "depositary"
        candidate["evidence"][0]["fields"].update({"issuer": "Depositary Bank", "issuer_role": "depositary"})
        result = evaluate_recommendation(candidate, dict(CONTEXT, allocation_weight=60), today=TODAY)
        self.assertNotIn("R_CONCENTRACION_EMISOR", result["rule_ids"])
        self.assertEqual(result["concentration_checks"]["issuer"]["status"], "unknown")

    def test_future_intraday_evidence_is_rejected_for_facts_and_fund_fees(self):
        future_record = complete_fci("AR:FCI:FUTURE:1")
        future_time = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
        future_record["evidence"][0]["observed_at"] = future_time
        result = evaluate_recommendation(future_record, CONTEXT, today=TODAY)
        self.assertFalse(result["eligible"])
        self.assertIn("canonical_id_evidence", result["missing_fields"])

        fee_future = complete_fci("AR:FCI:FEEFUTURE:1")
        fee_future["evidence"][0]["raw_source_fields"].pop("fees")
        fee_future["evidence"].append({
            "kind": "observed", "source": "Future CAFCI fee", "url": "https://example.test/future-fee",
            "observed_at": future_time, "data_date": "2026-10-30",
            "expires_at": (datetime.now(timezone.utc) + timedelta(days=7)).isoformat(),
            "fields": {}, "raw_source_fields": {"fees": fee_future["raw_fees"]},
        })
        result = evaluate_recommendation(fee_future, CONTEXT, today=TODAY)
        self.assertTrue(result["eligible"])
        self.assertIsNone(result["ranking_factors"]["published_fund_fees"])
        self.assertNotIn("derived_fund_fee_annual_pct", result["record"])

    def test_research_budget_investigates_best_preflight_eligible_candidate_first(self):
        expensive = complete_fci("AR:FCI:A:1", fee=2)
        cheaper = complete_fci("AR:FCI:Z:1", fee=1)
        class Provider:
            def __init__(self): self.calls = []
            def supports(self, candidate): return True
            def source_key(self, candidate): return "https://example.test/" + candidate["canonical_id"]
            def research(self, candidate, **kwargs):
                self.calls.append(candidate["canonical_id"])
                return candidate
        result = {"capital": 100000, "moneda": "ARS", "perfil_riesgo": "MODERADO",
                  "cartera_porcentual": {"Renta variable": 20}}
        snapshot = {"perfil": {"horizonte": 48, "objetivo": "Crecimiento",
                               "tolerancia": 30, "liquidez": 20}}
        source = {"normalized_records": [expensive, cheaper]}
        with tempfile.TemporaryDirectory() as directory:
            provider = Provider()
            research = research_instruments(
                result, snapshot, [source], provider=provider,
                store=KnowledgeStore(directory + "/knowledge.db"),
                limits=ResearchLimits(1, 10, 12), today=TODAY,
            )
        self.assertEqual(provider.calls, [cheaper["canonical_id"]])
        self.assertEqual(research["categories"][0]["selected_id"], cheaper["canonical_id"])

    def test_fx_mandate_without_holdings_does_not_pass(self):
        candidate = complete_fci("AR:FCI:FX:1")
        candidate["category"] = "Renta fija cambiaria"
        candidate["exposure"] = "fx"
        candidate["exposure_basis"] = "mandate"
        candidate["evidence"][0]["fields"].update({"category": candidate["category"], "exposure": "fx"})
        candidate["horizon"] = "Mediano Plazo"
        candidate["duration"] = "Menor o Igual a 1 Año"
        candidate["evidence"][0]["fields"].update({"horizon": candidate["horizon"]})
        context = dict(CONTEXT, category="Renta fija cambiaria", horizon_months=24)
        result = evaluate_recommendation(candidate, context, today=TODAY)
        self.assertFalse(result["eligible"])
        self.assertIn("holdings_details", result["missing_fields"])
        self.assertIn("actual_exposure_or_holdings", result["missing_fields"])

    def test_inflation_requires_strict_majority_of_explicit_current_holdings(self):
        for share, expected in ((51, True), (50, False), (40, False)):
            with self.subTest(share=share):
                candidate = self._fixed_candidate("Renta fija inflación", [
                    {"name": "Bono BONCER", "weight_percent": share},
                    {"name": "Resto de Activos", "weight_percent": 100 - share},
                ])
                context = dict(CONTEXT, category="Renta fija inflación")
                result = evaluate_recommendation(candidate, context, today=TODAY)
                self.assertEqual(result["eligible"], expected)
                if expected:
                    self.assertEqual(result["record"]["derived_exposure"], {"inflation": 51.0})
                    self.assertEqual(result["record"]["derived_selection_category"], "Renta fija inflación")
                    self.assertEqual(result["record"]["derived_exposure_date"], "2026-10-20")
                else:
                    self.assertIn("R_EXPOSICION_ESPECIFICA_INSUFICIENTE", result["rule_ids"])

    def test_commercial_fund_name_with_cer_does_not_prove_underlying_exposure(self):
        candidate = self._fixed_candidate("Renta fija inflación", [
            {"name": "Fondo CER Promesa", "weight_percent": 80},
            {"name": "Resto de Activos", "weight_percent": 20},
        ])
        result = evaluate_recommendation(candidate, dict(CONTEXT, category="Renta fija inflación"), today=TODAY)
        self.assertFalse(result["eligible"])
        self.assertEqual(result["record"].get("derived_exposure"), None)
        self.assertIn("R_EXPOSICION_ESPECIFICA_INSUFICIENTE", result["rule_ids"])

    def test_multiple_mandate_hints_allow_other_category_only_after_holdings_match(self):
        candidate = self._fixed_candidate("Renta fija inflación", [
            {"name": "Letra dollar-linked", "weight_percent": 51},
            {"name": "Resto de Activos", "weight_percent": 49},
        ])
        candidate["category_hints"] = ["Renta fija inflación", "Renta fija cambiaria"]
        result = evaluate_recommendation(candidate, dict(CONTEXT, category="Renta fija cambiaria"), today=TODAY)
        self.assertTrue(result["eligible"], result["missing_fields"])
        self.assertEqual(result["record"]["derived_exposure"], {"fx": 51.0})
        self.assertEqual(result["record"]["derived_selection_category"], "Renta fija cambiaria")

    def test_fixed_fund_requires_fresh_evidenced_duration_and_flexible_needs_duration(self):
        fixed = self._fixed_candidate("Renta fija inflación", [
            {"name": "Bono BONCER", "weight_percent": 51},
            {"name": "Resto de Activos", "weight_percent": 49},
        ])
        fixed["evidence"][0]["data_date"] = "2026-10-01"
        result = evaluate_recommendation(fixed, dict(CONTEXT, category="Renta fija inflación"), today=TODAY)
        self.assertFalse(result["eligible"])
        self.assertIn("duration_evidence", result["missing_fields"])

        flexible = complete_fci("AR:FCI:FLEX:1")
        flexible["horizon"] = "Flexible"
        flexible["duration"] = "Menor o Igual a 1 Año"
        flexible["evidence"][0]["fields"].update({
            "horizon": flexible["horizon"], "duration": flexible["duration"],
        })
        result = evaluate_recommendation(flexible, CONTEXT, today=TODAY)
        self.assertTrue(result["eligible"], result["missing_fields"])

        flexible["duration"] = None
        flexible["evidence"][0]["fields"].pop("duration")
        result = evaluate_recommendation(flexible, CONTEXT, today=TODAY)
        self.assertFalse(result["eligible"])
        self.assertIn("duration", result["missing_fields"])

    def test_fx_bank_account_is_not_dollar_linked_exposure(self):
        candidate = self._fixed_candidate("Renta fija cambiaria", [
            {"name": "Cuenta USD", "weight_percent": 70},
            {"name": "Resto de Activos", "weight_percent": 30},
        ])
        result = evaluate_recommendation(candidate, dict(CONTEXT, category="Renta fija cambiaria"), today=TODAY)
        self.assertFalse(result["eligible"])
        self.assertIn("R_EXPOSICION_ESPECIFICA_INSUFICIENTE", result["rule_ids"])

    def test_bymadata_snapshot_can_support_indicative_selection_but_not_execution_price(self):
        result = evaluate_recommendation(self._cedear(), CONTEXT, today=TODAY)
        self.assertTrue(result["eligible"], result["missing_fields"])
        self.assertIsNone(result["record"]["unit_price"])
        self.assertIsNone(result["record"]["quote_data_date"])
        self.assertEqual(result["record"]["indicative_minimum"], 100)
        self.assertEqual(result["execution_checks"]["status"], "PENDIENTE_INTERMEDIARIO")

    def test_stale_snapshot_and_nonordinary_cedear_do_not_pass(self):
        old = datetime.now(timezone.utc) - timedelta(minutes=20)
        stale = evaluate_recommendation(self._cedear(observed_at=old), CONTEXT, today=TODAY)
        self.assertFalse(stale["eligible"])
        self.assertTrue(any("fresh_market_snapshot" in value for value in stale["missing_fields"]))
        nonordinary = evaluate_recommendation(self._cedear(ordinary="ETF"), CONTEXT, today=TODAY)
        self.assertFalse(nonordinary["eligible"])
        self.assertIn("ordinary_share_representation", nonordinary["missing_fields"])

    def test_ce_dollar_rule_requires_exact_normative_source_and_crypto_never_passes(self):
        invalid_rule = self._cedear()
        invalid_rule["market_unit_rule"]["source"] = "https://example.test/fake-rule"
        result = evaluate_recommendation(invalid_rule, CONTEXT, today=TODAY)
        self.assertFalse(result["eligible"])
        self.assertIn("documented_market_unit_rule", result["missing_fields"])

        crypto = complete_fci("CRYPTO:BTC")
        crypto["instrument_type"] = "CRYPTO"
        crypto["exposure"] = "bitcoin"
        result = evaluate_recommendation(crypto, CONTEXT, today=TODAY)
        self.assertFalse(result["eligible"])
        self.assertIn("R_CRYPTO_POLICY", result["rule_ids"])


if __name__ == "__main__":
    unittest.main()
