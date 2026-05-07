{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "HTB Mission Control Agent Decision",
  "type": "object",
  "required": ["summary", "confidence", "proposed_actions", "findings", "notes"],
  "properties": {
    "summary": {"type": "string"},
    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
    "proposed_actions": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["type", "label", "why", "risk"],
        "properties": {
          "type": {"type": "string", "enum": ["run_command", "add_note", "add_finding", "ask_user", "update_hosts", "update_report"]},
          "label": {"type": "string"},
          "command": {"type": "string"},
          "risk": {"type": "string", "enum": ["safe_auto", "logged_auto", "approval_required", "blocked", "unknown"]},
          "why": {"type": "string"},
          "expected_output": {"type": "string"},
          "evidence_ids": {"type": "array", "items": {"type": "string"}},
          "requires_approval_reason": {"type": "string"}
        },
        "additionalProperties": true
      }
    },
    "findings": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "title": {"type": "string"},
          "severity": {"type": "string"},
          "confidence": {"type": "number"},
          "needs_verification": {"type": "boolean"},
          "evidence": {"type": "array"}
        },
        "additionalProperties": true
      }
    },
    "notes": {"type": "array", "items": {"type": "string"}}
  },
  "additionalProperties": true
}
