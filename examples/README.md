## Sample Review Outputs

This directory captures an **Example PR review** cycle to demonstrate the kinds of files and logs the agentic code-review system produces.

### Included artifacts

- `sample_review_summary.json` – a miniaturized version of what `ReviewOrchestrator` writes to step summaries. It mirrors the structure that ends up in `logs/pr_<PR>_<TIMESTAMP>/analysis_results.json` (rule IDs, severities, and metadata).
- (Not committed) `logs/pr_1234_20250202_120000/` – when you run a full review locally or via CI, the `AnalysisLogger` creates JSON/JSONL/CSV exports in `logs/`. Those exports are the real-world counterparts to the sample below.
- CLI/automation tips:
  1. Run `python -m src.main analyze --repo owner/repo --pr 1` to produce similar output.
  2. Inspect `logs/pr_<PR>_<TIMESTAMP>/analysis_results.json` and pass its contents into `examples/sample_review_summary.json` for documentation or demos.

Keep this directory in sync with real logs if you want to showcase the system for demos or documentation.
