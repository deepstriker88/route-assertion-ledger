"""Standalone, script-free report. All text inserted into HTML is escaped."""
from html import escape


def html_report(result):
    s = result["summary"]
    passed = result["ok"]
    pin_mismatch = result.get("scope_pin") == "mismatch"
    headline = "Review scope changed" if pin_mismatch else ("Coverage gate passed" if passed else "Coverage gaps found")
    pin_note = '<p class="pin-warning" role="status">Scope fingerprint does not match the independently reviewed value. Do not accept this result.</p>' if pin_mismatch else ""
    def e(value):
        return escape(str(value), quote=True)
    def status_list(values):
        return ", ".join(str(x) for x in values) or "—"
    def card(row):
        state = row["state"]
        css = "covered" if state == "covered" else ("excluded" if state == "excluded" else "gap")
        labels = {"covered": "Covered", "excluded": "Excluded by policy",
                  "unobserved": "No documented response observed", "unasserted": "No response asserted",
                  "missing_required": "Required status not asserted", "unasserted_statuses": "Observed status not asserted"}
        return (
            '<article class="'+css+'"><h3>'+e(row["operation"])+'</h3><p class="state">'+e(labels.get(state, state))+
            '</p><dl><dt>Observed</dt><dd>'+e(status_list(row["observed_statuses"]))+
            '</dd><dt>Asserted</dt><dd>'+e(status_list(row["asserted_statuses"]))+
            '</dd><dt>Unasserted</dt><dd>'+e(status_list(row["unasserted_statuses"]))+
            '</dd><dt>Missing required</dt><dd>'+e(status_list(row["missing_required_statuses"]))+
            '</dd></dl></article>')
    rows = result["operations"]
    gaps = [r for r in rows if r["state"] not in ("covered", "excluded")]
    covered = [r for r in rows if r["state"] == "covered"]
    excluded = [r for r in rows if r["state"] == "excluded"]
    def section(label, group, expanded=False):
        if not group:
            return ""
        cards = '<div class="cards">'+ "".join(card(r) for r in group)+'</div>'
        if expanded:
            return '<section aria-label="'+e(label)+'"><h2>'+e(label)+' ('+e(len(group))+')</h2>'+cards+'</section>'
        return '<details><summary>'+e(label)+' ('+e(len(group))+')</summary>'+cards+'</details>'
    issues = "".join(
        '<li>'+e(issue["code"].replace("_", " "))+
        (' · record '+e(issue["row"]) if "row" in issue else ' · '+e(issue.get("operation","")))+
        (' · '+e(status_list(issue["statuses"])) if "statuses" in issue else '')+
        '</li>' for issue in result["issues"])
    gap_section = section("Needs attention", gaps, expanded=True)
    covered_section = section("Covered operations", covered)
    excluded_section = section("Excluded by policy", excluded)
    issue_section = ('<section aria-label="Validation issues"><h2>Validation issues</h2><ul class="issues">'+issues+'</ul></section>'
                     if issues else "")
    return """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'">
<meta name="referrer" content="no-referrer"><title>Route assertion report</title>
<style>
:root{font:16px/1.55 system-ui,"Segoe UI",sans-serif;color:#202523;background:#f6f6f3}
*{box-sizing:border-box}body{margin:0}main{max-width:1060px;margin:auto;padding:24px clamp(16px,4vw,44px) 48px}
header{padding:12px 0 24px;border-bottom:1px solid #dce0db}h1{font-size:clamp(1.85rem,5vw,3rem);letter-spacing:-.035em;font-weight:650;line-height:1.1;margin:10px 0}
h2{font-size:1.25rem;margin:28px 0 14px}h3{font-size:1rem;overflow-wrap:anywhere;margin:0}
p{color:#515b56;margin:8px 0}.eyebrow{color:#176354;text-transform:uppercase;letter-spacing:.08em;font-weight:650;font-size:.85rem}
.overview{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px;margin-top:20px}
.metric,article{background:#fff;border:1px solid #dce0db;border-radius:14px;padding:18px;min-width:0}
.metric strong{display:block;font-size:1.65rem;font-weight:650}.metric span{color:#515b56}
.cards{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}.state{font-weight:650}.covered .state{color:#176354}.gap .state{color:#a32832}.excluded .state{color:#515b56}.gap{border-left:4px solid #a32832}.issues{padding:0 0 0 22px;color:#81212a}.issues li{margin:5px 0}.pin-warning{border-left:4px solid #a32832;padding:8px 12px;color:#81212a}
dl{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-bottom:0}dt{color:#515b56}dd{margin:0;overflow-wrap:anywhere}
details{margin-top:24px}summary{cursor:pointer;min-height:44px;font-weight:650;padding:10px 0}
:focus-visible{outline:3px solid #176354;outline-offset:3px}code,li{overflow-wrap:anywhere}
@media(max-width:640px){.cards{grid-template-columns:1fr}.overview{grid-template-columns:1fr}.metric{display:flex;align-items:center;justify-content:space-between;gap:12px}}
</style></head><body><main><header><p class="eyebrow">Local validation report</p><h1>"""+headline+"""</h1><p>Based on supplied test assertion records, not verified network activity.</p>"""+pin_note+"""<p>Excluded operations: """+e(s["excluded"])+""" · Policy: """+("all observed documented statuses" if result["assert_all_observed"] else "required statuses and at least one assertion")+"""</p></header>
<section class="overview" aria-label="Coverage summary">
<div class="metric"><strong>"""+e(s["covered"])+"/"+e(s["in_scope"])+"""</strong><span>Operations covered</span></div>
<div class="metric"><strong>"""+e(s["observations"])+"""</strong><span>Records</span></div>
<div class="metric"><strong>"""+e(s["issues"])+"""</strong><span>Issues</span></div></section>
"""+gap_section+issue_section+covered_section+excluded_section+"""
<details><summary>Scope fingerprint and limitations</summary><p><code>"""+e(result["scope_sha256"])+"""</code></p><p>Declared route names are included. Unknown observation values and exclusion reasons are omitted. No payload, header, query or live endpoint validation. The input assertion flags must be trusted.</p></details>
</main></body></html>"""
