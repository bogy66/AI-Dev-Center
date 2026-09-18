
cd ~/KFZ-KI

source venv/bin/activate

aider \
--gui \
--model openai/gpt-5-mini \
app/

Lies CONVENTIONS.md und PROJECT_CONTEXT.md.

Fasse kurz zusammen:
- was ist das Ziel des Projekts
- was wurde bereits umgesetzt
- was ist der nächste geplante Schritt

curl -X POST \
  "http://192.168.178.240:8123/api/webhook/vt7l8htwiIAE84Oc02lHuxZhCgSdFyfoC0ycuIShYP" \
  -H "Content-Type: application/json" \
  -d '{
    "event": "TASK_COMPLETED",
    "task_id": "TEST-001",
    "agent": "claude",
    "slack_channel": "C0C00LZFZ1A",
    "report_end_ts": "1234567890.123456"
  }'


curl -i -X POST \
  "http://192.168.178.240:8123/api/webhook/vt7l8htwiIAE84Oc02lHuxZhCgSdFyfoC0ycuIShYP" \
  -H "Content-Type: application/json" \
  -d '{
    "event": "TASK_COMPLETED",
    "task_id": "TEST-REVIEW-001",
    "agent": "claude",
    "task_spec": "Implementiere Funktion X. Acceptance Gate: Test X muss grün sein. Kein Commit.",
    "report": "Status SUCCESS. Funktion X implementiert. Test X schlägt weiterhin fehl. Kein Commit durchgeführt.",
    "slack_channel": "C0C00LZFZ1A",
    "report_end_ts": "1234567890.123456"
  }'

