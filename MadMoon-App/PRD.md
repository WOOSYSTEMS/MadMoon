# MadMoon — Personal Command Center PRD

**Version:** 0.1 | **Date:** 2026-10-07 | **Owner:** Navindu | **Status:** Building

---

## 1. Purpose

MadMoon is a private iOS app for a solo founder running five businesses simultaneously. A **war room dashboard** — one screen to know where everything stands, one tap to drill in, one swipe to capture.

---

## 2. Screens

### Command Center (Home)
- Project cards (5) with health indicator (green/yellow/red), status line, top KPI, last touched
- Today's schedule strip
- Quick capture FAB

### Project Detail
- KPI grid, task list, milestones, notes/log, financials tab

### Schedule / Time-Boxing
- Weekly/daily hour blocks, assign project colors, signal tracker per block

### Financial Command
- Portfolio summary, per-project breakdown, runway calculator

### Quick Capture
- Text + project selector + type (idea/task/note) + priority. Under 5 seconds.

### Signal-to-Noise Tracker
- Daily bar, weekly trend, ratio display

### Goals & Milestones
- Per-project goals with progress bars, portfolio goals, streak counters

### Mindset
- Daily affirmation, meditation/gym streaks, weekly review prompt

---

## 3. Design

- Background: #0A0A0F (near-black)
- Surface: #14141F (cards)
- Border: #1E1E2E
- Text: #E4E4E7 / #71717A
- UmmaGlobal: #1B5E3B | Bamba: #0F4C75 | OneBrain: #7C3AED | App Factory: #F59E0B | BizData: #14B8A6
- SF Pro Mono for data, SF Pro Rounded for headers
- Sharp crescent moon logo

---

## 4. Tech

- Swift 6, SwiftUI, SwiftData, iOS 18+, MVVM
- Private distribution (TestFlight/ad-hoc)
- No backend, local-first, iCloud backup optional
