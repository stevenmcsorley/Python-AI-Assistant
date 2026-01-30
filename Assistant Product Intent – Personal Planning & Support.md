---
title: Assistant Product Intent – Personal Planning & Support
type: product-intent
date: 2026-01-30
status: authoritative
version: 1.0
---

## 1. Product Vision

This assistant is a long-running personal AI assistant that serves as a chief-of-staff–style system. It is not a chatbot or research toy. Its primary purpose is to help the user plan, prepare, and execute across time horizons.

The assistant emphasizes:
- **Planning** – Structured thinking about future actions
- **Preparation** – Getting ready for what's coming
- **Continuity** – Maintaining context across sessions and time
- **User support** – Acting in service of the user's goals

The assistant exists to reduce cognitive load, prevent oversights, and ensure the user is prepared for what matters.

## 2. Core Assistant Responsibilities

The assistant's core responsibilities are:

- **Understanding the user's goals, plans, and intentions** – Actively listening and asking clarifying questions
- **Helping plan days, weeks, months, and future events** – Creating structured plans that can be reviewed and adjusted
- **Detecting signals from emails, calendar events, and Obsidian notes** – Identifying what needs attention or preparation
- **Proposing next actions, preparations, and research** – Suggesting concrete steps based on context
- **Acting only with user approval** – Never taking autonomous action without explicit consent

## 3. Planning & Time Horizons

The assistant operates across multiple time horizons:

- **Day planning** – Today's schedule, meetings, tasks, and preparations
- **Week planning** – Upcoming week's commitments, deadlines, and preparation needs
- **Month planning** – Longer-term projects, goals, and milestones
- **Event-based future planning** – Specific events like interviews, deadlines, trips, or goals

All plans are:
- **Proposed** – Presented as suggestions for review
- **Reviewable** – Can be examined, adjusted, or rejected
- **Persisted as artifacts** – Saved as structured documents (Obsidian notes) for future reference

## 4. Intent & Signal Detection

The assistant detects signals from multiple sources:

- **Signals from email** – Job offers, interview invitations, meeting requests, deadlines
- **Signals from calendar events** – Upcoming meetings, appointments, deadlines
- **Signals from Obsidian notes** – User's documented goals, plans, research, or concerns
- **Explicit user statements** – Direct requests or statements of intent

The assistant follows **clarification-first behavior** before creating plans or memory. It asks for confirmation before assuming intent.

## 5. Example Canonical Flow – Job Search Assistance

1. **Detect job-related signals in email** – Identify job offers, interview invitations, or application confirmations
2. **Ask for confirmation of intent** – "Are you looking for a job?" or "Is this job search active?"
3. **Review CV from Obsidian or files** – Access existing CV/resume documents
4. **Suggest CV improvements** – Propose edits based on job descriptions or industry standards
5. **Help track applications** – Maintain a structured log of applications, responses, and next steps
6. **Prepare for interviews** – Research companies, suggest questions to ask, propose preparation timelines

All outputs are **drafts unless explicitly approved**. The user maintains final control over all documents and actions.

## 6. Research as a Supporting Capability

Research capabilities exist to support planning and preparation:

- **Web search** – Finding relevant information for upcoming events or decisions
- **Reading and synthesis** – Processing articles, documents, or research papers
- **Information organization** – Structuring findings for easy reference

Research outputs are **structured artifacts** (Obsidian notes, summaries, comparison tables), not chat replies. They serve as inputs to planning and decision-making.

## 7. Memory Model (Product Perspective)

The assistant maintains memory to improve continuity and usefulness:

- **Stores confirmed goals** – Only goals explicitly stated and confirmed by the user
- **Stores ongoing projects** – Active work the user has acknowledged
- **Stores preferences** – User's stated preferences and working styles
- **Stores context** – Relevant background information for current activities

Memory is:
- **Inspectable** – The user can view all stored memory
- **Editable** – The user can correct or delete memory entries
- **Never silently inferred** – Memory is only created from explicit user confirmation

Memory exists to make the assistant more helpful over time, not to build a profile without user awareness.

## 8. Trust & Boundaries

Core trust principles that cannot be violated:

- **No silent actions** – Every action is announced before execution
- **No silent memory creation** – Memory is only created with user awareness
- **No calendar or document mutation without approval** – Changes require explicit consent
- **The assistant explains why it is suggesting something** – Transparency in reasoning

These boundaries ensure the assistant remains a trusted tool rather than an autonomous agent.

---

**Status:** This document represents the authoritative product intent for the assistant and must be considered when composing PRDs or architecture documents.

**Related Documents:** [[PRD – Python AI Assistant v1]], [[System Invariants – Python AI Assistant]], [[Project Seed – Python AI Assistant v1]]