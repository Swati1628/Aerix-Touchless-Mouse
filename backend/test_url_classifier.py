"""Regression checks for legitimate URL complexity and safety controls."""
import unittest
import time
from unittest.mock import patch

from backend.click_safety import ClickSafety, SafetyDecision
from backend.url_classifier import URLClassifier


CLASSIFIER_CASES = [
    ("https://www.myntra.com/", "safe"),
    ("https://www.myntra.com/login?referer=https%3A%2F%2Fwww.myntra.com%2F", "safe"),
    ("https://www.myntra.com/accessories?f=Brand%3ACaprese%3A%3ACategories%3AClutches%2CHandbags%2CWallets%3A%3AGender%3Amen%20women%2Cwomen&rf=Discount%20Range%3A60.0_100.0_60.0%20TO%20100.0", "safe"),
    ("https://www.flipkart.com/", "safe"),
    ("https://www.flipkart.com/login?ret=/", "safe"),
    # The supplied product example redacts ctx/nnc with ellipses; test this
    # literal only as a format regression, not as the unredacted production URL.
    ("https://www.flipkart.com/washing-machines/~cs-8nzvbq8rjm/pr?sid=j9e%2Cabm%2C8qx&collection-tab-name=LG+WM+-+TL&ctx=...&nnc=...&BU=Mixed", "safe"),
    ("https://www.google.com/", "safe"),
    ("https://www.google.com/search?sca_esv=aad93e118372d4df&rlz=1C1OPNX_en-GBIN1105IN1106&sxsrf=APpeQnsFwWSPaCc72GuUXtUKuaCp97S5BA:1790277652639&udm=2&fbs=ABfTbFVyMZGZf1hfvX9uKjN_-G8cqCQj_06QnZs315LoFmPf5bBLHMJ0vMQmTbuI72DM7jkCMzF6tiD-p-0w1wJ8QXOpatx0Vkldwpt1Xs0WJvV6MRD10e-SCpfFx_EoMm5N6UoqlqxHWtQZgad-oYNeaOH4POwcIl1YjwoSQRYdkUKBli78qT0LM-zXBINXcSYlrK9-c1JsHI4gEfhl1Rub2XMR2TrBUg&q=nykaa&sa=X&ved=2ahUKEwjfq6P894eXAxX6iuEIHW8wBSsQtKgLegQIDxAB", "safe"),
    ("https://www.nykaa.com/", "safe"),
    ("https://web.whatsapp.com/", "safe"),
    ("https://www.canva.com/", "safe"),
    ("https://www.meesho.com/", "safe"),
    ("https://about.google/?utm_source=googlehpfooter&utm_medium=housepromos&utm_campaign=bottom-footer&fg=1", "safe"),
    ("https://member-check-account.example.test/continue?ref=ZX91", "suspicious"),
    ("http://account-login.example.test:8081/verify?redirect=%2Fauth", "dangerous"),
]


class URLClassifierRegressionTests(unittest.TestCase):
    def test_legitimate_complex_urls_and_classifier_controls(self):
        classifier = URLClassifier()
        for url, expected_risk in CLASSIFIER_CASES:
            with self.subTest(url=url):
                result = classifier.classify(url)
                self.assertEqual(result["risk"], expected_risk, (url, result))

    def test_training_pipeline_applies_inference_normalization(self):
        classifier = URLClassifier()
        url = "https://example.com/page?utm_source=mail&next=%2Faccount"
        normalized = classifier.model.named_steps["normalize"].transform([url])[0]
        self.assertEqual(normalized, "https://example.com/page?next=%2Faccount")

    def test_deterministic_download_and_parental_filter_rules_still_block(self):
        safety = ClickSafety()
        executable = safety._evaluate_url("http://download.example.test/update.bat")
        parental = safety._evaluate_url("https://blocked-test.example/", safety._filter)
        self.assertEqual((executable.allowed, executable.risk), (False, "dangerous"))
        self.assertEqual((parental.allowed, parental.risk), (False, "blocked"))

    def test_custom_site_policy_blocks_all_requested_names(self):
        safety = ClickSafety()
        names = {"netmirror", "pikashow", "ppcine", "vegamovies", "gomovies",
                 "spoteuve", "dailymotion", "moviebox"}
        self.assertTrue(names.issubset(set(safety._filter.get("blocked_site_names", []))))
        for name in names:
            url = f"https://www.{name}.test/watch?id=123&next=%2Fhome#player"
            with self.subTest(site=name):
                decision = safety._evaluate_url(url, safety._filter)
                self.assertEqual((decision.allowed, decision.risk), (False, "dangerous"))
                self.assertEqual(decision.reason, "Blocked by Aerix custom security policy")

    def test_custom_site_policy_matches_hostname_labels_not_substrings(self):
        safety = ClickSafety()
        safety._filter = {"blocked_site_names": ["netmirror"]}
        for url in (
            "https://NETMIRROR.test/path",
            "https://www.netmirror.test/path",
            "https://deep.sub.netmirror.test/path",
            "https://%6eetmirror.test/path",
        ):
            with self.subTest(url=url):
                result = safety._custom_site_block_decision(url, safety._filter)
                self.assertIsNotNone(result)
                self.assertEqual((result.allowed, result.risk), (False, "dangerous"))
        for url in ("https://notnetmirror.test/", "https://unrelated.example/", "https://netmirrorish.test/"):
            with self.subTest(url=url):
                self.assertIsNone(safety._custom_site_block_decision(url, safety._filter))

    def test_hard_block_precedes_cached_safe_and_reputation_checks(self):
        safety = ClickSafety()
        url = "https://www.dailymotion.test/video"
        normalized = safety._normalize_url(url)
        safety._results[normalized] = (time.monotonic(), SafetyDecision(True, "cached SAFE", True,
                                                                       "safe", 1.0))
        with patch.object(safety._threat_intelligence, "inspect", side_effect=AssertionError("must not query")), \
             patch.object(safety._classifier, "classify", side_effect=AssertionError("must not classify")):
            result = safety.inspect_url(url)
        self.assertEqual((result["allowed"], result["risk"]), (False, "dangerous"))
        self.assertEqual(result["reason"], "Blocked by Aerix custom security policy")
        self.assertFalse(result["cached"])
        self.assertEqual(safety.evaluate_click().risk, "dangerous")


if __name__ == "__main__":
    unittest.main()
