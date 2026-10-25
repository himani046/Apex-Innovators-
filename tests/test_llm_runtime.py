import unittest

from backend.services.llm_runtime import (
    cached_response,
    ensure_token_budget,
    llm_run_context,
    store_response,
    usage_snapshot,
)


class LLMRuntimeTests(unittest.TestCase):
    def test_exact_prompt_response_is_cached_within_run(self):
        with llm_run_context(100) as state:
            store_response("system", "prompt", 20, "model", '{"ok":true}', {
                "input_tokens": 8, "output_tokens": 4,
            })
            self.assertEqual(cached_response("system", "prompt", 20, "model"), '{"ok":true}')
            usage = usage_snapshot(state)
            self.assertEqual(usage["provider_calls"], 1)
            self.assertEqual(usage["cache_hits"], 1)
            self.assertEqual(usage["tokens_used"], 12)

    def test_token_budget_blocks_additional_provider_call(self):
        with llm_run_context(5) as state:
            store_response("system", "prompt", 20, "model", "result", {
                "input_tokens": 3, "output_tokens": 2,
            })
            with self.assertRaisesRegex(RuntimeError, "token budget exhausted"):
                ensure_token_budget()
            self.assertEqual(usage_snapshot(state)["tokens_used"], 5)

    def test_cache_does_not_leak_between_runs(self):
        with llm_run_context(100):
            store_response("system", "prompt", 20, "model", "result", {})
        with llm_run_context(100) as state:
            self.assertIsNone(cached_response("system", "prompt", 20, "model"))
            self.assertEqual(usage_snapshot(state)["cache_hits"], 0)


if __name__ == "__main__":
    unittest.main()
