from pathlib import Path
from .schemas import AnalysisResult, PolicyFacts, RateComponent, Citation

RATER_ROOT=Path(__file__).resolve().parents[1]/"rate_cards"

def insurer_key(name: str | None) -> str | None:
    if not name: return None
    n=name.lower()
    if "hdfc" in n: return "hdfc-ergo"
    if "digit" in n: return "godigit"
    if "reliance" in n: return "reliance-indusind"
    if "tata" in n: return "tata-aig"
    return None

def resolve(facts: PolicyFacts, source_filename: str) -> AnalysisResult:
    key=insurer_key(facts.insurer)
    trace=["Policy facts extracted from the uploaded PDF using Gemini structured extraction."]
    if facts.insurer and facts.previous_insurer:
        trace.append(f"Business type derived from insurer comparison: {facts.business_type or 'not determined'}.")
    if facts.rto: trace.append(f"RTO identified as {facts.rto}; insurer-specific geographic mapping is required.")
    if facts.make_model: trace.append(f"Vehicle identified as {facts.make_model}; insurer-specific segment mapping is required.")
    if facts.policy_type and "standalone" in facts.policy_type.lower() and "tp" in facts.policy_type.lower():
        od=RateComponent(applicable=False,status="not_applicable",explanation="OD is not applicable to a stand-alone TP policy, per the challenge brief.")
    else:
        od=RateComponent(applicable=True,status="unsupported",explanation="No rate returned: the matching insurer grid row and all required conditions have not yet been deterministically verified.")
    tp=RateComponent(applicable=True,status="unsupported",explanation="No rate returned: the matching insurer grid row and all required conditions have not yet been deterministically verified.")
    if not key:
        reason="Insurer could not be mapped to one of the supplied rate-card providers."
    else:
        reason=f"Identified supplied rate-card family '{key}', but no verified rule adapter has been enabled yet."
    trace.append(reason)
    trace.append("Fail-closed decision: no commission percentage is invented when a complete, evidence-backed lookup cannot be established.")
    warning=["Commission resolution is intentionally fail-closed until insurer-specific deterministic grid adapters and mapping tables are verified."]
    if facts.missing_or_uncertain: warning.extend(facts.missing_or_uncertain)
    return AnalysisResult(
        status="unsupported" if facts.insurer else "ambiguous",
        insurer=facts.insurer, facts=facts, od=od, tp=tp, confidence="low",
        confidence_explanation="Policy extraction may be useful, but commission lookup is not yet verified against a complete grid path.",
        decision_trace=trace, warnings=warning,
        citations=[Citation(source_file=source_filename,location=f"PDF page {p}",role="policy_fact") for p in sorted(set(facts.source_pages.values()))]
    )
