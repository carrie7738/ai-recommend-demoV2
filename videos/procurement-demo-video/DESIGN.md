# Design System

## Overview

The AI Smart Procurement Assistant is a light executive workspace with a clear procurement-report hierarchy. It uses a cool white canvas, deep navy headings, blue-gray dividers, and mint status chips to make the purchase decision readable at a glance. The video preserves the live product UI instead of recreating it, adding only restrained scenario labels and slow camera movement.

## Colors

- **Workspace Surface**: `#F8F9FA` — the product page background.
- **Report Surface**: `#FFFFFF` — cards, request field, and procurement report panels.
- **Primary Ink**: `#1A1A2E` — product title and key decision text.
- **Secondary Ink**: `#31333F` — supporting labels and body copy.
- **Divider**: `#E2E8F0` — quiet table and card separation.
- **Muted Surface**: `#F0F2F6` — subtle layout contrast.
- **Action Accent**: `#FF4B4B` — the existing Generate procurement plan button.
- **Scenario Accent**: `#0054A3` — video-only scenario identifiers, drawn from captured UI tokens.

## Typography

- **Inter** (400, 500, 600, 700) — primary product interface, scenario labels, and short overlays.
- **Source Sans** (100–900 variable) — available support face; not used over the captured product UI.
- Headings are concise and bold; labels use uppercase tracking and compact sizes.

## Elevation

The product relies on pale panels, 1px blue-gray borders, and modest shadows rather than dramatic depth. The video keeps the screens full-frame and adds a low-opacity navy vignette behind scenario labels only.

## Components

- **AI Procurement Request**: large free-text input with a red generate action.
- **AI Decision Brief**: four compact decision cards for intent, demand, constraint, and confidence.
- **Procurement Summary**: budget, investment, remaining budget, and recommended-product count.
- **Recommended Products Table**: the main business-decision artifact.
- **Status Chips**: `Within Budget`, `Budget Optimized`, and other concise plan states.

## Do's and Don'ts

### Do's

- Keep the real UI screenshot as the dominant visual.
- Use slow, restrained zoom and short crossfades so the table remains readable.
- Reserve overlays for small scenario labels only.
- Leave silent pauses on the procurement report for later voiceover.

### Don'ts

- Do not redraw or obscure the product UI.
- Do not add narration, music, captions, or sound effects.
- Do not use high-energy transitions that compete with financial information.
- Do not crop out the procurement summary or table headers.
