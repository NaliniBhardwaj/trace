# TRACE
## Passive H₂S Exposure Dosimeter & Industrial Safety Intelligence Platform

> **Smart India Hackathon 2026 — Problem Statement 26118**  
> **Passive Colorimetric H₂S Exposure-Dosimeter with AI-Based Quantitative Reading**

TRACE is an end-to-end industrial worker-safety platform designed to transform passive colorimetric Hydrogen Sulphide (H₂S) exposure strips into a digitally traceable safety workflow.

Instead of treating a passive sensing strip as an isolated colour-changing indicator, TRACE connects the strip to worker identity, zone access, smartphone-based image analysis, exposure estimation, physical location, alerts, worker rotation, evacuation, remediation, and supervisor response.

The platform combines **QR identification, computer vision, machine learning, BLE-based location intelligence, exposure analytics, safety rules, offline synchronization, and role-based mobile interfaces** into one operational workflow.

---

# Table of Contents

- [1. Problem](#1-problem)
- [2. TRACE Vision](#2-trace-vision)
- [3. Core Workflow](#3-core-workflow)
- [4. Key Features](#4-key-features)
- [5. Worker Application](#5-worker-application)
- [6. Manager Application](#6-manager-application)
- [7. H₂S Strip Analysis Pipeline](#7-h₂s-strip-analysis-pipeline)
- [8. QR-Based Strip Validation](#8-qr-based-strip-validation)
- [9. Zone Access & Worker Permit](#9-zone-access--worker-permit)
- [10. BLE Location Intelligence](#10-ble-location-intelligence)
- [11. Exposure & Risk Engine](#11-exposure--risk-engine)
- [12. Alerts & Emergency Response](#12-alerts--emergency-response)
- [13. Automated Worker Rotation](#13-automated-worker-rotation)
- [14. Evacuation Management](#14-evacuation-management)
- [15. Cleaning & Remediation](#15-cleaning--remediation)
- [16. Offline Operation](#16-offline-operation)
- [17. Maps & Zone Intelligence](#17-maps--zone-intelligence)
- [18. AI / ML Architecture](#18-ai--ml-architecture)
- [19. Role-Based Access](#19-role-based-access)
- [20. Demo Mode](#20-demo-mode)
- [21. System Architecture](#21-system-architecture)
- [22. Data Flow](#22-data-flow)
- [23. Technology Stack](#23-technology-stack)
- [24. Project Structure](#24-project-structure)
- [25. Safety & Engineering Principles](#25-safety--engineering-principles)
- [26. Limitations](#26-limitations)
- [27. Running the Project](#27-running-the-project)
- [28. Future Scope](#28-future-scope)
- [29. Team](#29-team)

---

# 1. Problem

Hydrogen Sulphide (H₂S) is a hazardous gas encountered in multiple industrial environments.

Passive colorimetric H₂S strips provide a low-cost method for indicating cumulative exposure. However, traditional workflows have several limitations:

- Colour interpretation can be subjective.
- Readings may not be digitally recorded.
- Strip identity and validity may be difficult to track.
- Exposure information may remain disconnected from worker identity.
- Zone access may not be connected to current risk conditions.
- Supervisors may lack a unified operational view.
- Exposure events may not automatically lead to rotation or remediation workflows.
- Connectivity loss can interrupt digital workflows.
- Historical exposure information can be difficult to correlate with location and operational events.

TRACE addresses this gap by building a complete digital safety workflow around the passive strip.

---

# 2. TRACE Vision

TRACE follows a simple principle:

> **A passive H₂S strip should not end as a colour on a piece of paper. It should become a traceable digital safety event.**

The platform connects:

```text
Worker
   ↓
Zone Access
   ↓
QR-identified Strip
   ↓
Camera Capture
   ↓
Computer Vision
   ↓
ML Dose Estimation
   ↓
Exposure / Risk Analysis
   ↓
Worker Guidance
   ↓
Alerts
   ↓
Rotation / Evacuation / Remediation
   ↓
Manager Response
   ↓
Reports & Handover
3. Core Workflow

A typical TRACE workflow is:

Step 1 — Worker Login

The worker authenticates using the existing backend authentication system.

The backend determines the user's role and assigned information.

TRACE separates the operational experience into:

Worker
Manager / Supervisor
Step 2 — Physical Location Detection

BLE beacon infrastructure can determine the worker's physical zone.

The application can display:

Physical zone
Assigned zone
Location confidence
Location freshness
Location source
Offline/local state

If the physical zone differs from the assigned zone, TRACE explicitly surfaces the mismatch.

Step 3 — Zone Access

Before entering a controlled zone, the worker can open:

Scan → Zone Access

The worker scans the zone QR.

TRACE resolves the zone and obtains the corresponding entry information from the existing backend.

The application can show:

Zone
Floor
Current risk
Assigned zone
Physical zone
Zone mismatch
Permit status

The backend then determines whether the worker receives access.

Possible outcomes include:

ACCESS GRANTED

or

ACCESS DENIED

The actual authorization decision remains server-side.

Step 4 — Strip Identification

The worker opens:

Scan → Strip Analysis

The strip QR is scanned first.

The QR identifies the strip and allows TRACE to validate the strip before image analysis.

Step 5 — Strip Validation

TRACE separates:

Strip validity

from

Zone access authorization

The strip can be classified by the existing validation pipeline as:

Valid
Expiring
Expired
Invalid

An invalid strip does not proceed into image analysis.

Step 6 — Camera Capture

After successful validation, the worker captures the physical strip using the smartphone camera.

The application follows the analysis stages:

IDENTIFY
    ↓
VALIDATE
    ↓
CAPTURE
    ↓
ANALYZE
    ↓
RESULT

The image-processing pipeline performs the existing computer-vision and ML workflow.

Step 7 — AI / ML Analysis

The captured strip image is processed by the existing analysis pipeline.

The system uses image-derived colour information to estimate exposure-related quantities.

The resulting information can contribute to:

Dose estimation
Exposure summary
Risk classification
Worker guidance
Zone risk
Operational response

The mobile frontend does not independently invent or recalculate safety values.

Step 8 — Exposure Monitoring

TRACE connects exposure readings with worker and operational context.

Worker-facing information can include:

Current risk
H₂S-related reading
Exposure duration
Cumulative ppm·min
Number of scans
Peak exposure
Daily exposure information
Active safety actions
Step 9 — Safety Response

Depending on existing backend/risk-engine state, TRACE can surface:

Alerts
Evacuation
Rotation recommendations
Strip requirements
Expired strip warnings
Remediation requirements
SOS events
Step 10 — Manager Response

The manager dashboard aggregates operational information into:

Overview
Response
Workers
Zones
Alerts
Rotation
Remediation
Handover
Reports

This creates a continuous chain from:

worker event → safety analysis → operational response → supervisor action

4. Key Features
Worker Features
Secure login
Role-based navigation
Worker dashboard
BLE physical-location awareness
Assigned-zone visibility
Zone mismatch detection
Zone access QR
Worker permit workflow
Strip QR scanning
Strip validation
Camera capture
Computer vision analysis
ML-based exposure estimation
Exposure history
Risk status
Safety alerts
SOS
Offline operation
SQLite local queue
Synchronization
Map
Insights
Senti assistant
Settings
Language switching
Theme support
Manager Features
Manager authentication
Operational overview
Response Center
Worker monitoring
Zone monitoring
Alert management
Evacuation status
Rotation recommendations
Remediation / cleaning queue
Shift handover
Reports
Zone risk maps
Exposure context
SOS awareness
Operational response tracking
5. Worker Application

The Worker Home screen is designed as an operational safety surface rather than a generic dashboard.

It includes:

Header
TRACE branding
Worker identity
Online/offline state
Notification access
Settings
Location Card

Shows:

Physical BLE zone
Assigned zone
Location confidence
Location freshness
Location source
Offline/local status

A physical-vs-assigned mismatch is explicitly displayed.

Current Safety

Displays information obtained from the existing exposure APIs:

Current risk
H₂S-related measurement
Exposure duration
Cumulative exposure
Safety status

The frontend does not implement a second safety engine.

Today's Exposure

Can surface:

Scan count
Peak exposure
Dose information
Link to Insights
Active Actions

Only relevant actions are displayed, such as:

EVACUATION ACTIVE
ROTATION RECOMMENDED
STRIP REQUIRED
STRIP EXPIRED
STRIP INVALID
Permit Status

The worker can see relevant active permits including:

Zone
Permit status
Validity
Alerts

Recent alerts are surfaced directly from the existing alert system.

SOS

TRACE includes a hold-to-trigger SOS workflow.

6. Manager Application

The Manager Dashboard provides an operational control surface.

Overview

The Overview provides a Response Snapshot containing information such as:

Critical zones
High-risk zones
Active evacuations
Rotation requirements
Cleaning/remediation queue
Unacknowledged alerts

Cards provide navigation into the relevant operational section.

Response Center

The Response Center consolidates incident-response information.

It can surface:

Critical zones
High-risk zones
Evacuations
Rotation recommendations
Remediation requirements

The Response Center does not generate fake safety events.

It uses existing application state and backend data.

Workers

The Workers section provides worker-level operational context.

This can include:

Worker identity
Assigned zone
Exposure-related status
Operational state
Safety-related attention requirements
Zones

The Zones section provides zone-level context including:

Risk
Worker count
Exposure information
Floor
Zone identity
Alerts

The Alerts section aggregates operational alerts.

Alerts may contain:

Severity
Type
Zone
Status
Acknowledgement state
Relevant operational context
Rotation

The Rotation section displays existing rotation recommendations.

Rotation is driven by the existing safety/exposure logic rather than a second frontend algorithm.

Remediation

The Remediation section prioritizes areas requiring corrective action or cleaning.

The frontend displays the existing remediation state.

Handover

Handover allows supervisors to transfer operational context between shifts.

Reports

Reports provide a review and accountability surface for recorded activity.

7. H₂S Strip Analysis Pipeline

TRACE uses a multi-stage workflow:

STRIP QR
   ↓
IDENTIFY
   ↓
VALIDATE
   ↓
CAMERA CAPTURE
   ↓
IMAGE QUALITY / CV
   ↓
ML ANALYSIS
   ↓
DOSE ESTIMATION
   ↓
RISK / GUIDANCE
   ↓
RESULT

The UI prevents invalid strip states from progressing into analysis.

This is important because:

A QR identifying a strip does not automatically mean that the strip is valid for analysis.

8. QR-Based Strip Validation

Every strip can be associated with a QR identity.

TRACE uses QR information to establish strip identity before image analysis.

Validation can distinguish:

VALID
EXPIRING
EXPIRED
INVALID

Invalid or unusable strips are blocked from progressing to the capture/analysis stage.

This prevents the UI from presenting an apparently valid AI result for a strip that failed validation.

9. Zone Access & Worker Permit

TRACE also uses QR codes for controlled zone access.

Worker flow:

Scan
 ↓
Zone Access
 ↓
Scan Zone QR
 ↓
Resolve Zone
 ↓
Entry Information
 ↓
Permit Request
 ↓
Backend Authorization
 ↓
ACCESS GRANTED / ACCESS DENIED

The entry screen can provide:

Zone name
Zone code
Floor
Current risk
Physical BLE location
Assigned zone
Location mismatch warning
Permit status
Authorization reason

Authorization remains controlled by the existing backend permit system.

10. BLE Location Intelligence

TRACE supports BLE-based physical-location awareness.

The existing location architecture uses:

BLE Beacon
    ↓
RSSI / Beacon Detection
    ↓
Location Context
    ↓
Zone Resolution
    ↓
Worker Physical Zone

The application can use:

Beacon identity
RSSI processing
Zone mapping
Location confidence
Freshness
Offline location events

The UI does not create a separate BLE location algorithm.

The existing BLE engine remains the source of truth.

11. Exposure & Risk Engine

TRACE integrates with the existing exposure and risk system.

The application can consume:

H₂S-related readings
Exposure duration
Cumulative ppm·min
Worker exposure
Zone exposure
Risk level
Safety actions

The frontend intentionally avoids duplicating safety calculations.

This prevents inconsistencies between:

Backend Safety Logic

and

Mobile UI Logic
12. Alerts & Emergency Response

TRACE integrates operational alerts including:

Critical H₂S locality events
High-risk conditions
Adjacent-zone warnings
Supervisor/admin alerts
SOS-related events
Evacuation-related events

Alert handling supports:

Severity
Type
Zone
Status
Acknowledgement
Deduplication through the existing alert engine

The alert system is designed to surface actionable operational information rather than simply display notifications.

13. Automated Worker Rotation

TRACE supports worker rotation recommendations.

The workflow is:

Exposure / Operational State
          ↓
Existing Safety / Rotation Engine
          ↓
Rotation Recommendation
          ↓
Manager Dashboard
          ↓
Supervisor Response

Rotation recommendations can become particularly relevant when a worker's exposure or operating context indicates the need for relief.

TRACE does not create a separate frontend rotation algorithm.

The manager UI presents the existing recommendation and its associated operational context.

14. Evacuation Management

TRACE integrates evacuation information into the operational response workflow.

When an evacuation state exists, it can be surfaced through:

Worker Home
Manager Overview
Response Center
Alerts
Rotation/response surfaces

The objective is to connect incident state with operational visibility.

TRACE does not replace site emergency procedures or certified emergency systems.

15. Cleaning & Remediation

TRACE includes remediation prioritization.

The manager can access a queue representing areas requiring corrective action.

The workflow is:

Risk / Exposure State
        ↓
Existing Remediation Logic
        ↓
Priority Queue
        ↓
Manager Remediation View
        ↓
Corrective Action

The frontend displays existing remediation state rather than inventing cleaning priorities.

16. Offline Operation

TRACE is designed to remain useful when network connectivity is interrupted.

The mobile application uses local SQLite storage and synchronization mechanisms.

Offline architecture supports:

Mobile Event
     ↓
Local SQLite
     ↓
Offline Queue
     ↓
Connectivity Restored
     ↓
Synchronization
     ↓
Backend

The UI can communicate:

Online
Offline
Local
Sync-related state

The application does not falsely claim that an event has reached the server when it has only been stored locally.

17. Maps & Zone Intelligence

TRACE includes operational zone maps.

The map supports:

Zone visualization
Risk context
Worker counts
Floor-level information
Horizontal layout
Vertical/floor filtering
Safe route visualization where available

Zone data comes from the existing API and local fallback structures.

The map does not hardcode fake operational risk values into the UI.

18. AI / ML Architecture

TRACE's intelligence layer consists of multiple components.

Computer Vision

The camera image can be processed to identify and analyze the colorimetric strip.

The pipeline can include:

Image capture
Strip localization
Image-quality checks
Colour feature extraction
Analysis preparation
Machine Learning

The ML layer maps extracted image information to exposure-related estimates.

The prototype uses a trained model and calibration data for software validation.

The resulting value should be interpreted as a prototype software estimate, not a laboratory-certified gas measurement.

AI / Scenario Intelligence

TRACE also contains an AI foundation for operational scenarios.

Existing scenario pathways include:

NORMAL_OPERATION
HIGH_RISK_ZONE
COMBINED_CRITICAL_EVENT

These pathways can provide deterministic operational scenarios for demonstrations and testing without replacing the underlying safety engine.

19. Role-Based Access

TRACE separates Worker and Manager experiences.

Worker

Worker login routes to the worker application containing:

Home
Scan
Map
Insights
Senti
Alerts/settings through existing navigation surfaces
Manager

Manager login routes to the manager operational dashboard containing:

Overview
Response
Workers
Zones
Alerts
Rotation
Remediation
Handover
Reports

Role selection is determined through the existing authentication/session system.

The frontend does not simply change labels to pretend that a worker is a manager.

20. Demo Mode

TRACE includes a controlled Demo Mode for deterministic demonstrations.

This exists because physical industrial hardware and live H₂S exposure cannot always be reproduced during a software demonstration.

Demo Mode supports scenarios such as:

Normal Operations
Elevated Exposure
Critical Zone Event
Zone Access / Permit
Strip Analysis

The Demo Mode uses the existing synthetic/AI scenario pathways rather than creating a second fake safety engine inside the UI.

Real Mode

Real Mode remains the default operating mode.

Real Mode continues to use:

Real BLE pipeline
Real camera
Real QR scanning
Existing APIs
Existing ML pipeline
Existing SQLite/offline architecture
Existing safety logic
Demo Mode Transparency

Demo Mode is explicitly identified as synthetic scenario data.

The application does not label synthetic data as live hardware measurements.

This distinction is maintained so that demonstrations remain technically honest.

21. System Architecture
                         ┌──────────────────────┐
                         │       TRACE          │
                         │   Mobile Platform    │
                         └──────────┬───────────┘
                                    │
                  ┌─────────────────┼─────────────────┐
                  │                 │                 │
             WORKER APP        MANAGER APP       SETTINGS
                  │                 │
                  └─────────────────┼─────────────────┘
                                    │
                              API / SERVICES
                                    │
        ┌───────────────────────────┼───────────────────────────┐
        │                           │                           │
   Authentication             Exposure / Risk              Permits
        │                           │                           │
        │                     Rotation / Evacuation        Zone Access
        │                           │                           │
        └───────────────────────────┼───────────────────────────┘
                                    │
                              FastAPI Backend
                                    │
                 ┌──────────────────┼──────────────────┐
                 │                  │                  │
                AI                 ML                 BLE
                 │                  │                  │
          Scenario Engine     Strip Analysis      Location Engine
                 │                  │                  │
                 └──────────────────┼──────────────────┘
                                    │
                              Data / SQLite
                                    │
                         Offline Synchronization
22. Data Flow
Worker Exposure Flow
Worker Login
     ↓
Worker Identity
     ↓
Assigned Zone
     ↓
BLE Physical Location
     ↓
Zone Context
     ↓
Strip QR
     ↓
Strip Validation
     ↓
Camera Capture
     ↓
CV / ML Analysis
     ↓
Exposure Estimate
     ↓
Risk Engine
     ↓
Worker Guidance
     ↓
Alerts / Rotation / Evacuation
     ↓
Manager Dashboard
Zone Access Flow
Worker
  ↓
Zone Access
  ↓
Zone QR
  ↓
Zone Resolution
  ↓
Physical vs Assigned Location
  ↓
Entry Information
  ↓
Permit Request
  ↓
Backend Authorization
  ↓
Grant / Deny
Incident Response Flow
Exposure / Zone Event
        ↓
Risk & Safety Engine
        ↓
Alert
        ↓
Worker Notification
        ↓
Manager Response Center
        ↓
Evacuation / Rotation / Remediation
        ↓
Operational Follow-up
23. Technology Stack
Mobile
React Native
Expo
TypeScript
React Navigation
Expo Camera
QR scanning
SQLite
AsyncStorage
lucide-react-native
React Context architecture
Backend
Python
FastAPI
Uvicorn
REST APIs
JWT-based authentication
CORS configuration
Database / Local Storage
Backend application database
SQLite for mobile offline storage
Offline event queue
Synchronization mechanisms
AI / ML
Python ML pipeline
Computer Vision
Colour feature extraction
Regression-based dose estimation
Existing trained model artifacts
AI scenario engine
Location
BLE beacons
RSSI-based processing
Zone resolution
Location confidence
Offline location events
QR

QR functionality is used for:

Strip identification
Strip validation
Zone identification
Worker zone-access workflow
24. Project Structure

A simplified project structure is:

TRACE/
│
├── mobile/
│   ├── App.tsx
│   ├── app.json
│   ├── package.json
│   │
│   └── src/
│       ├── api/
│       ├── components/
│       ├── contexts/
│       ├── data/
│       ├── db/
│       ├── navigation/
│       ├── screens/
│       │   ├── HomeScreen.tsx
│       │   ├── ScanScreen.tsx
│       │   ├── ZoneAccessScreen.tsx
│       │   ├── MapScreen.tsx
│       │   ├── InsightsScreen.tsx
│       │   ├── AlertsScreen.tsx
│       │   ├── ManagerDashboard.tsx
│       │   └── SettingsScreen.tsx
│       │
│       ├── theme/
│       └── ...
│
├── backend/
│   ├── app/
│   ├── main.py
│   ├── requirements.txt
│   └── ...
│
├── ml/
│   ├── models/
│   ├── preprocessing/
│   └── ...
│
└── README.md

Internal filenames and directories may differ depending on the current repository structure. Existing model artifacts, QR protocols, API contracts, and backend identifiers should not be renamed merely for branding purposes.

25. Safety & Engineering Principles

TRACE follows several important engineering principles.

No Duplicate Safety Logic

The mobile UI does not create a second exposure/risk engine.

Safety decisions remain within the existing backend and safety architecture.

No Fabricated Live Measurements

Synthetic/demo values are not presented as live hardware measurements.

QR Validity ≠ Authorization

A valid QR does not automatically mean a worker is authorized to enter a zone.

Strip validation and zone authorization are separate workflows.

Invalid Strip ≠ AI Result

An invalid or expired strip should not proceed through the analysis pipeline.

Offline ≠ Synced

An offline event is stored locally until synchronization succeeds.

The application does not falsely report successful server synchronization.

Demo ≠ Real Hardware

Demo scenarios exist for deterministic demonstrations.

Real Mode continues to use the actual application pipelines.

26. Limitations

TRACE is a prototype intended for Smart India Hackathon evaluation and software validation.

Important limitations include:

The ML dose estimate is a prototype software estimate.
It is not a laboratory-certified H₂S measurement instrument.
Synthetic calibration/scenario data may be used for software validation.
BLE accuracy depends on beacon deployment and environmental conditions.
Smartphone camera performance depends on lighting, focus, angle, and image quality.
Real industrial deployment requires calibration and field validation.
Emergency workflows do not replace certified gas detection systems.
TRACE does not replace Permit-to-Work procedures.
TRACE does not replace site-specific emergency response procedures.
Production deployment would require appropriate safety certification, validation, security review, and industrial testing.
27. Running the Project
Backend

Start the backend using the project's configured environment.

Example:

uvicorn app.main:app --host 0.0.0.0 --port 8000

The backend must be reachable by the mobile device.

Mobile

Install dependencies:

cd mobile
npm install

Start Expo:

npx expo start

For LAN development:

npx expo start --lan
Android USB Development

When using a physical Android device through USB debugging:

adb devices

For backend access through USB:

adb reverse tcp:8000 tcp:8000

For Metro:

adb reverse tcp:8081 tcp:8081

The mobile API URL can then use:

EXPO_PUBLIC_API_URL=http://127.0.0.1:8000

When using LAN instead, use the PC's LAN IPv4 address:

EXPO_PUBLIC_API_URL=http://<PC-LAN-IP>:8000

After changing .env, restart Metro so the environment variables are reloaded.

28. Future Scope

TRACE can be extended with:

Laboratory-validated calibration datasets
Larger real-world H₂S exposure datasets
Improved camera calibration
Controlled illumination accessories
More robust strip segmentation
Advanced model uncertainty estimation
Production push notifications
Industrial BLE infrastructure
Additional wearable integrations
Advanced worker exposure forecasting
Enterprise authentication
Audit trails
Advanced reporting
Industrial deployment validation
Safety certification and regulatory compliance
29. Team
Team Spectrum

Smart India Hackathon 2026

Problem Statement: 26118
Problem: Passive Colorimetric H₂S Exposure-Dosimeter with AI-Based Quantitative Reading

Project

TRACE — Passive H₂S Exposure Dosimeter & Industrial Safety Intelligence Platform

Conclusion

TRACE transforms a passive colorimetric H₂S exposure strip into a connected digital safety workflow.

It connects:

IDENTITY
   +
ZONE
   +
PERMIT
   +
STRIP
   +
QR
   +
CAMERA
   +
COMPUTER VISION
   +
MACHINE LEARNING
   +
BLE LOCATION
   +
EXPOSURE
   +
RISK
   +
ALERTS
   +
ROTATION
   +
EVACUATION
   +
REMEDIATION
   +
MANAGER RESPONSE

The result is a unified platform where a worker's exposure event can move from physical strip identification to digital analysis and operational response.

TRACE is not simply a strip-scanning application.

It is an integrated safety intelligence workflow designed to connect passive exposure sensing with worker-level and site-level operational decision support.

TRACE — Turning passive exposure into actionable safety intelligence.
