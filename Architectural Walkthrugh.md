┌──────────────────────────────────────────────────────────────────────┐
│  CLI Layer          build_arg_parser() → resolve_story()             │
│  (argparse)         --story | --file | --stdin                       │
└────────────────────────────┬─────────────────────────────────────────┘
                             │
┌────────────────────────────▼─────────────────────────────────────────┐
│  Orchestrator       generate_test_suite()                            │
│  (main flow)        validates → calls LLM → parses → writes output   │
└───┬──────────────────────┬──────────────────────┬────────────────────┘
    │                      │                      │
┌───▼──────┐     ┌─────────▼────────┐    ┌────────▼──────────────────┐
│ validate │     │  call_llm()       │    │  parse_llm_response()     │
│ _user_   │     │  @retry (tenacity)│    │  json.loads → Pydantic    │
│ story()  │     │  OpenAI client    │    │  TestCase validation       │
└──────────┘     └──────────────────┘    └───────────────────────────┘
                          │
                 ┌────────▼──────────────────────────────────────────┐
                 │  OpenAI Chat Completions API                       │
                 │  response_format: {"type": "json_object"}         │
                 │  Structured System Prompt → raw JSON out          │
                 └──────────────────────────────────────────────────┘