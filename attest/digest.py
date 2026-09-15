"""Agent-activity digests and anomaly flags (P3.6).

  digest(ledger, since_hours=24)  → counts by agent / system / level / decision, human decisions, unverified rows,
                                     and anomaly flags computed against the previous 7 days:
      new_action      an (agent, system.verb) never seen in the baseline
      volume_spike    an agent did > 3× its daily baseline (min 10)
      unverified_spike unverified rows > 2× baseline (min 3)
      off_hours       > 30% of an agent's actions between 22:00 and 06:00 UTC when its baseline is < 5%
      external_burst  external-target sends > 3× baseline (min 5)
`attest digest --since 24` prints it; the cloud serves `GET /v1/digest`; Slack / email can carry it daily.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta
from typing import Any

from attest.ledger.models import LedgerEntry


def _count(values: Any) -> dict[str, int]:
    return dict(Counter(str(v) for v in values))


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def summarize(entries: list[LedgerEntry]) -> dict[str, Any]:
    return {
        "actions": len(entries),
        "by_agent": _count(e.agent or "-" for e in entries),
        "by_system": _count(e.descriptor.get("system") for e in entries),
        "by_level": _count(e.verification.level for e in entries),
        "by_decision": _count(e.decision for e in entries),
        "human_decisions": _count(e.confirm.status for e in entries if e.confirm.status != "not_required"),
        "unverified": [{"seq": e.seq, "action": f"{e.descriptor.get('system')}.{e.descriptor.get('verb')}",
                        "target": e.descriptor.get("target"), "agent": e.agent,
                        "failed": e.verification.evidence.get("failed")} for e in entries if e.verification.level == "unverified"],
        "refused_or_rejected": sum(1 for e in entries if e.decision == "refuse" or e.confirm.status in ("rejected", "expired")),
    }


def anomalies(window: list[LedgerEntry], baseline: list[LedgerEntry], *, baseline_days: float = 7.0) -> list[dict[str, Any]]:
    flags: list[dict[str, Any]] = []
    seen = {(e.agent, e.descriptor.get("system"), e.descriptor.get("verb")) for e in baseline}
    for key in sorted({(e.agent, e.descriptor.get("system"), e.descriptor.get("verb")) for e in window} - seen, key=str):
        if baseline:
            flags.append({"flag": "new_action", "agent": key[0], "action": f"{key[1]}.{key[2]}",
                          "detail": "never seen in the previous 7 days"})
    per_agent_window = Counter(e.agent for e in window)
    per_agent_base = Counter(e.agent for e in baseline)
    for agent, n in per_agent_window.items():
        daily = per_agent_base.get(agent, 0) / max(baseline_days, 1)
        if n >= 10 and n > 3 * max(daily, 1):
            flags.append({"flag": "volume_spike", "agent": agent, "detail": f"{n} actions vs {daily:.1f}/day baseline"})
        win_off = sum(1 for e in window if e.agent == agent and _aware(e.created_at).hour in (22, 23, 0, 1, 2, 3, 4, 5))
        base_agent = [e for e in baseline if e.agent == agent]
        base_off = sum(1 for e in base_agent if _aware(e.created_at).hour in (22, 23, 0, 1, 2, 3, 4, 5))
        if n >= 5 and win_off / n > 0.3 and (not base_agent or base_off / len(base_agent) < 0.05):
            flags.append({"flag": "off_hours", "agent": agent, "detail": f"{win_off}/{n} actions between 22:00 and 06:00 UTC"})
    unv_w = sum(1 for e in window if e.verification.level == "unverified")
    unv_b = sum(1 for e in baseline if e.verification.level == "unverified") / max(baseline_days, 1)
    if unv_w >= 3 and unv_w > 2 * max(unv_b, 1):
        flags.append({"flag": "unverified_spike", "detail": f"{unv_w} unverified rows vs {unv_b:.1f}/day baseline"})
    ext_w = sum(1 for e in window if e.target_class == "external" and e.descriptor.get("verb") in ("send", "reply", "share"))
    ext_b = sum(1 for e in baseline if e.target_class == "external" and e.descriptor.get("verb") in ("send", "reply", "share")) / max(baseline_days, 1)
    if ext_w >= 5 and ext_w > 3 * max(ext_b, 1):
        flags.append({"flag": "external_burst", "detail": f"{ext_w} external sends vs {ext_b:.1f}/day baseline"})
    return flags


def digest(entries: list[LedgerEntry], *, since_hours: float = 24, now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now(UTC)
    start = now - timedelta(hours=since_hours)
    base_start = start - timedelta(days=7)
    window = [e for e in entries if _aware(e.created_at) >= start]
    baseline = [e for e in entries if base_start <= _aware(e.created_at) < start]
    return {"period": {"from": start.isoformat(), "to": now.isoformat(), "hours": since_hours},
            "summary": summarize(window), "baseline": {"days": 7, "actions": len(baseline)},
            "anomalies": anomalies(window, baseline)}


def render_text(d: dict[str, Any]) -> str:
    s = d["summary"]
    lines = [f"Attest digest — last {d['period']['hours']:g}h: {s['actions']} actions",
             "  by level:    " + ", ".join(f"{k} {v}" for k, v in sorted(s["by_level"].items())),
             "  by decision: " + ", ".join(f"{k} {v}" for k, v in sorted(s["by_decision"].items())),
             "  by agent:    " + ", ".join(f"{k} {v}" for k, v in sorted(s["by_agent"].items(), key=lambda x: -x[1])[:8]),
             "  humans:      " + (", ".join(f"{k} {v}" for k, v in sorted(s["human_decisions"].items())) or "none needed")]
    if s["unverified"]:
        lines.append(f"  UNVERIFIED ({len(s['unverified'])}):")
        lines += [f"    #{u['seq']} {u['action']} → {u['target']} [{u['agent']}] failed={u['failed']}" for u in s["unverified"][:10]]
    if d["anomalies"]:
        lines.append("  anomalies:")
        lines += [f"    {a['flag']}: {a.get('agent', '')} {a.get('action', '')} — {a['detail']}" for a in d["anomalies"]]
    return "\n".join(lines)


def slack_blocks(d: dict[str, Any]) -> list[dict[str, Any]]:
    text = render_text(d)
    return [{"type": "header", "text": {"type": "plain_text", "text": "Attest daily digest"}},
            {"type": "section", "text": {"type": "mrkdwn", "text": "```" + text[:2900] + "```"}}]


_ = defaultdict
