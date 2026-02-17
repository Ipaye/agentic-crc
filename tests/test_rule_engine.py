\"\"\"Pytest coverage for the base rule engine guardrails.\"\"\"

from src.analysis.parser import Language
from src.analysis.rules import RuleEngine


def test_rule_engine_loads_core_rules() -> None:
    \"\"\"Rule engine should expose the built-in security rule set.\"\"\"
    engine = RuleEngine()
    python_rules = engine.get_rules_for_language(Language.PYTHON)
    assert any(rule.id == "SECURITY-001" for rule in python_rules)


def test_security_rule_detects_hardcoded_secret() -> None:
    \"\"\"SECURITY-001 should flag simple hardcoded passwords.\"\"\"
    engine = RuleEngine()
    secret_snippet = 'password = "supersecret99"\nprint("ok")\n'
    security_rule = next(
        rule for rule in engine.get_rules_for_language(Language.PYTHON)
        if rule.id == "SECURITY-001"
    )
    violations = engine.apply_rule(security_rule, secret_snippet, "src/example.py", Language.PYTHON)
    assert violations, "Expected at least one violation for SECURITY-001"
    assert any("potential hardcoded secret detected" in violation.message.lower() for violation in violations)


def test_apply_all_rules_reports_expected_ids() -> None:
    \"\"\"apply_all_rules should include both SECURITY and BEST_PRACTICES triggers.\"\"\"
    engine = RuleEngine()
    code_with_issues = '''
def greet(name):
    print("hello", name)

secret_api_key = "longsecretkey1234"
'''
    results = engine.apply_all_rules(code_with_issues, "src/sample.py", Language.PYTHON)
    rule_ids = {result.rule.id for result in results}
    assert {"SECURITY-001", "BEST-005"} <= rule_ids
