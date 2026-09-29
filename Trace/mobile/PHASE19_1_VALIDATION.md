# Phase 19.1 — Local Android + Backend Validation Guide

Run this checklist on a developer machine with Android device + backend.

## Prerequisites

```bash
# Terminal 1 — backend
cd sentinel/backend
# follow backend README: venv, pip install, uvicorn

# Terminal 2 — mobile
cd sentinel/mobile
npm install
npx tsc --noEmit
npx expo start
```

Set `EXPO_PUBLIC_API_URL=http://<LAN-IP>:8000` on physical device if auto-detect fails.

## Verification matrix (fill during test)

| Feature | Result | Verification type | Notes |
| ------- | ------ | ----------------- | ----- |
| npm install | | Environment | |
| tsc --noEmit | | Environment | |
| Expo launch | | Device | |
| Worker login | | Real device | |
| Manager login | | Real device | |
| Role separation | | Real device | |
| Logout | | Real device | |
| Worker Home data | | API/device | |
| Zone QR access | | Device | Mark NOT TESTED if no QR |
| Demo Mode | | Device | Settings → Demonstration |
| Critical Zone Event | | Device/API | Primary SIH scenario |
| Real Mode restore | | Device | Switch back from Demo |
| Zone QR + permit | | Real camera + API | |
| Strip QR + validation | | Real camera | |
| Camera capture | | Device | |
| CV/ML result | | API/device | |
| Exposure / risk | | API/device | |
| Horizontal map | | Device | |
| Vertical map | | Device | |
| Alerts + ack | | Device/API | |
| Response Center | | Device | |
| Evacuation | | Device/API | |
| Rotation | | Device/API | |
| Remediation | | Device/API | |
| Offline + sync | | Device | |
| i18n en/hi | | Device | |
| Theme | | Device | |
| ModeBanner transparency | | Device | Never "LIVE" hardware labels in Demo |

Allowed results: PASS | PARTIAL | NOT TESTED | BLOCKED

## Demo vs Real rules

- Demo/synthetic source must never display as live hardware
- Synthetic H₂S must not display as live sensor
- Permit grant/deny must come from `/permits/request`
- No UI-hardcoded CRITICAL / ppm values

## Engines (must remain untouched)

Backend, DB, AI, ML, CV, exposure, risk, permit, alert,
evacuation, rotation, remediation — no code changes for this phase.
