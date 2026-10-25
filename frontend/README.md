# Odin Frontend — Command Center Refresh

This branch refreshes the existing single-file Odin frontend in `frontend/index.html` without removing its current dashboard integration.

## UI flow
- Dark landing hero with the requested heading: **Manage Contracts in a Fast, Controlled & Collaborative Way**.
- “Get Started” opens the existing workspace and starts at Overview; hero navigation can deep-open Contracts, Agents, Deadlines, Risk & Review, or Audit.
- Existing FastAPI fetch calls and evidence/dashboard IDs remain in place.

## Command center additions
- Dark executive dashboard theme and page navigation.
- Agent activity inspector for Odin, Thor, Norns, Loki, Heimdall, and Tyr. It renders returned trace/state when available and does not mark missing work complete.
- Draft document studio that can prefill from the latest action draft, edit the text, download a local TXT draft, and record a clearly labelled local signature intent.
- Deadline calendar based on returned timeline milestones and decision-queue dates.
- Missed-deadline scenario planner for payment, renewal/termination, delivery/performance, notice, and security incidents.

## E-sign limitation
The e-sign section is a human-controlled drafting/signature-intent prototype only. It does not perform cryptographic signing, identity verification, or transmit signatures to an external e-sign provider. A production implementation needs an approved provider integration, authorization, and audit trail.

## Visual reference
The hero uses the user-provided globe still image as a background plate. It does not draw a globe or claim the supplied looping video is playing. The existing dashboard’s API endpoints are retained.

## Local run
Continue using the repository’s current frontend/backend instructions. The page remains a single HTML file and requires no frontend build step.
