"""Regression tests for MEOW's cloud-only LLM router."""

import unittest
from unittest.mock import patch

import llm_router


class CloudOnlyRouterTests(unittest.TestCase):
    def test_provider_order_prefers_selected_configured_provider(self):
        config = {
            "selected_model": "groq",
            "gemini_api_key": "gemini-key",
            "groq_api_key": "groq-key",
            "nvidia_api_key": "",
            "openrouter_api_key": "router-key",
        }
        self.assertEqual(
            llm_router._provider_order(config),
            ["groq", "gemini", "openrouter"],
        )

    def test_legacy_local_model_selection_never_selects_local_inference(self):
        config = {
            "selected_model": "llama",
            "gemini_api_key": "",
            "groq_api_key": "groq-key",
            "nvidia_api_key": "",
            "openrouter_api_key": "",
        }
        self.assertEqual(llm_router._provider_order(config), ["gemini", "groq"])

    def test_no_configured_cloud_provider_returns_setup_message(self):
        with patch.object(llm_router.memory_manager, "load_config", return_value={
            "selected_model": "gemini",
            "gemini_api_key": "",
            "groq_api_key": "",
            "nvidia_api_key": "",
            "openrouter_api_key": "",
        }):
            response = llm_router.query_llm("hello", "system")
        self.assertIn("cloud-only mode", response)
        self.assertIn("API key", response)

    def test_non_streaming_request_tries_next_cloud_provider(self):
        config = {
            "selected_model": "gemini",
            "gemini_api_key": "gemini-key",
            "groq_api_key": "groq-key",
            "nvidia_api_key": "",
            "openrouter_api_key": "",
        }
        with patch.object(llm_router.memory_manager, "load_config", return_value=config), \
             patch.object(llm_router, "_call_provider", side_effect=[
                 "I encountered an error communicating with Gemini.",
                 "Groq response",
             ]) as call:
            response = llm_router.query_llm("hello", "system")
        self.assertEqual(response, "Groq response")
        self.assertEqual(call.call_count, 2)

    def test_streaming_request_tries_next_cloud_provider_before_output(self):
        config = {
            "selected_model": "gemini",
            "gemini_api_key": "gemini-key",
            "groq_api_key": "groq-key",
            "nvidia_api_key": "",
            "openrouter_api_key": "",
        }
        def stream(provider, *_args, **_kwargs):
            if provider == "gemini":
                yield "Sorry, Gemini returned an empty or invalid response."
            else:
                yield "Groq "
                yield "response"
        with patch.object(llm_router.memory_manager, "load_config", return_value=config), \
             patch.object(llm_router, "_stream_provider", side_effect=stream):
            response = "".join(llm_router.query_llm_stream("hello", "system"))
        self.assertEqual(response, "Groq response")


if __name__ == "__main__":
    unittest.main()
