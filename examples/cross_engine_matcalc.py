"""Classify external engine status using both the return code and diagnostic messages."""


def classify(parsed, log, returncode, official_smoke=False):
    """Command return code zero does not guarantee numerical/model success."""
    lower = log.lower()
    if "cannot attach disordered part" in lower or "type definition ignored" in lower:
        return "incompatible_order_disorder_syntax"
    if "unknown keyword" in lower:
        return "unsupported_database_keyword"
    if returncode != 0 or parsed.get("status") != "commands_completed":
        return "execution_or_command_failed"
    if "*** error ***" in lower or "maximum number of iterations" in lower or "* error *" in lower:
        return "calculation_failed"
    if official_smoke and parsed.get("variables", {}).get("GM") is not None:
        return "official_smoke_completed"
    return "requires_model_and_homogeneity_audit"
