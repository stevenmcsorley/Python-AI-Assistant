# Long-Running Assistant – Background Operation & WhatsApp Interface

This document defines the non-negotiable behavior of the assistant as a long-running system and must be respected by PRDs, runtime architecture, and implementation decisions.

## 1. Long-Running Assistant Model

- The assistant is a **continuously running system**, not a request/response chatbot.
- It maintains **state, memory, and awareness across days and weeks**.
- The assistant can **think, prepare, and research in the background** between user interactions.
- It operates with **continuity of purpose** – remembering past conversations, ongoing projects, and user preferences.

## 2. Background Operation

### Permitted Background Activities
- Checking emails for relevant signals (e.g., job offers, deadlines, important updates).
- Reviewing calendar events and upcoming commitments.
- Preparing draft notes, plans, or research summaries based on detected signals.
- Monitoring Obsidian notes for updates or patterns.
- Running scheduled research or analysis tasks.

### Background Operation Constraints
- Background work is **read-only by default** – never silently mutates user data.
- All background work results in **prepared or draft artifacts**, not final actions.
- Background operations respect **quiet hours** and user-defined frequency limits.
- The assistant can be **paused or stopped** at any time without data loss.

## 3. Suggestion-First Behavior

- The assistant **surfaces findings as suggestions**, not actions.
- Every proactive message must include a **clear explanation** of why it is being suggested.
- The user must **explicitly approve** any action that mutates knowledge, calendar, or documents.
- Suggestions are **queued appropriately** – not interrupting active conversations.
- Users can **dismiss, snooze, or act** on suggestions with one-tap actions.

## 4. WhatsApp as the Primary Interaction Interface

### WhatsApp's Role
- **Primary channel** for receiving suggestions and updates.
- **Approval mechanism** for proposed actions.
- **Command interface** for asking questions or issuing instructions.
- **Status updates** on ongoing background work.

### Messaging Principles
- The assistant **never sends unsolicited messages** without a clear causal reason.
- Messages must be **concise, human-readable, and actionable**.
- Timing respects **user availability and preferences**.
- Messages include **clear call-to-action options** when appropriate.

## 5. Interaction Patterns

### Allowed Interactions (Examples)
- "I noticed several job-related emails. Are you currently looking for a job?"
- "I've prepared a draft weekly plan based on your calendar. Want to review it?"
- "I found 3 articles relevant to your project. Should I create a summary note?"
- "Your meeting with Alex starts in 30 minutes. Need any preparation notes?"
- "Background research on database architectures is complete. Ready for the summary?"

### Forbidden Interactions
- **Silent background changes** to calendar, documents, or knowledge.
- **Repeated or spammy notifications** without new information.
- **Actions taken without approval**, even if "obviously" correct.
- **Assumptions about user intent** without clarification.
- **Crossing privacy boundaries** without explicit permission.

## 6. Artifact Creation in the Background

### Types of Background Artifacts
- **Draft notes** – Research summaries, meeting preparations, project plans.
- **Prepared research bundles** – Curated information with analysis.
- **Proposed plans** – Day/week/month schedules based on calendar and goals.
- **Analysis reports** – Trends, patterns, or insights from monitored data.

### Artifact Labeling and Management
- All background artifacts must be **clearly labeled** (e.g., `[Draft]`, `[Prepared]`, `[Proposed]`).
- Artifacts include **metadata** explaining their purpose and source data.
- Artifacts are **surfaced via WhatsApp** for review before any use.
- Users can **accept, modify, or discard** any artifact.
- Accepted artifacts are **promoted to official status** with user approval.

## 7. Trust, Control, and Transparency

### User Control Mechanisms
- Users can always ask:
  - "What are you working on right now?"
  - "Why did you suggest this?"
  - "Show me your recent background activities."
  - "Stop background work for today."
  - "Pause all proactive suggestions."

### Transparency Requirements
- The assistant must be able to **answer control questions clearly and immediately**.
- **Audit logs** of all background activities must be accessible.
- **Confidence scores and reasoning** behind suggestions must be explainable.
- Users can **review and correct** any assumptions the assistant has made.

### Operational Controls
- Background operation can be **paused or disabled at any time**.
- Users can set **frequency limits and quiet hours**.
- **Per-domain permissions** control what data sources are monitored.
- **Global toggle** for all proactive features (off by default).

## 8. Implementation Implications

### Runtime Architecture
- The assistant must run as a **service/daemon**, not a script.
- **State persistence** must survive restarts and crashes.
- **Workflow checkpointing** enables resuming interrupted background work.
- **Resource management** prevents background work from affecting system performance.

### WhatsApp Integration
- **Message queueing** handles offline periods gracefully.
- **Read receipts and typing indicators** provide appropriate feedback.
- **Media support** for sharing documents, images, or links.
- **Quick reply templates** for common approval actions.

### Safety and Privacy
- **End-to-end encryption** for all WhatsApp communications.
- **Local processing** of sensitive data where possible.
- **Explicit consent** for any data sharing or cloud processing.
- **Data minimization** – only necessary data is processed.

---

*This operational model ensures the assistant remains **helpful without being intrusive**, **powerful without being dangerous**, and **autonomous without removing user control**.*

*Connects to: [[Assistant Product Intent – Personal Planning & Support]], [[System Invariants – Python AI Assistant]], [[PRD – Python AI Assistant v1]], [[Runtime Architecture – Python AI Assistant]]*