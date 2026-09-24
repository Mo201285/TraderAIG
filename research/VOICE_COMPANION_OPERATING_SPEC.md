# VOICE COMPANION OPERATING SPEC
## Voice-Enabled Account Companion for TraderAIG

**Last Updated:** 2026-09-11  
**Status:** Active Design Document  
**Scope:** Voice input, voice response, approvals, alerts, account companion, MT5/CEX integration

---

## 1. Purpose

This document defines the voice operating layer for the account companion.

Voice is not a cosmetic feature.
Voice is an operating interface that should help the user:

- express intent faster
- review strategy and account state hands-free
- receive concise risk and execution briefings
- trigger safe workflows
- confirm sensitive actions through controlled approval flows

The voice layer must improve speed and usability without weakening governance.

---

## 2. Core Principle

Voice may accelerate decisions.
Voice must never bypass decision controls.

The system may accept:

- strategy requests
- review requests
- monitoring commands
- paper-mode actions
- clarification responses

The system must not silently accept:

- irreversible live execution
- sensitive settings changes
- ambiguous deployment requests
- unconfirmed venue/account bindings

The text record remains the source of truth.

---

## 3. Product Role of Voice

The voice layer should act as a **hands-free operating layer** for the account companion.

Its role is to support four major workflows:

1. conversational strategy intake
2. account and strategy briefings
3. risk/execution alerts
4. approval readout and confirmation

---

## 4. Voice Modes

The system should support four modes.

### 4.1 Conversational Voice Mode
For natural interaction:

- create a strategy
- refine a draft
- ask why a strategy failed
- ask how to deploy to MT5/CEX

### 4.2 Briefing Mode
For concise spoken summaries:

- what matters now
- what needs approval
- what is degrading
- what risk is active

### 4.3 Alert Mode
For short urgent signals:

- MT5 disconnected
- strategy quarantined
- risk limit reached
- execution rejected

### 4.4 Approval Readout Mode
For high-friction, high-clarity confirmation of sensitive actions.

Examples:

- deploy strategy live
- bind strategy to account
- enable live trading on a venue
- quarantine or disable active strategy

---

## 5. Voice Interaction Model

Voice interaction should always follow this chain:

1. listen
2. transcribe
3. parse intent
4. resolve context
5. prepare structured action or answer
6. present text evidence
7. optionally speak concise response
8. request visual confirmation if sensitive

This keeps voice aligned with the governed workflow model.

---

## 6. Supported Voice Intents

### 6.1 Strategy intents

- create strategy
- edit strategy draft
- clarify entry logic
- approve for testing
- explain test results
- approve deployment
- quarantine strategy

### 6.2 Account intents

- review my account
- what is active on my account
- what needs my approval
- what is running on MT5
- what is running on Binance/OKX

### 6.3 Risk intents

- show current risk
- why was this blocked
- what is close to breach
- stop risky strategies

### 6.4 Execution intents

- explain rejected order
- show latest fills
- show venue health
- move this strategy to paper

### 6.5 Monitoring intents

- monitor this strategy
- alert me on degradation
- daily briefing
- read pending actions

---

## 7. Required Context Awareness

The voice companion must be context-aware.

It should know, at minimum:

- current user
- active account
- connected venues
- paper vs live mode
- strategy currently in focus
- pending approvals
- latest risk state
- latest validation state

Without context awareness, voice becomes unsafe and low-value.

---

## 8. Voice + Text Duality

Voice should be optimized for speed.
Text should remain optimized for auditability.

### Rules

- voice input is converted into text and stored as part of the interaction state
- strategy drafts must be displayed in text before test approval
- deployment details must be displayed in text before deployment approval
- alerts may be voice-only short prompts, but must remain visible in text logs
- any action affecting live accounts must leave a structured text record

This is mandatory for governance.

---

## 9. Approval Safety Rules

### Non-negotiable rule

Sensitive actions require explicit confirmation beyond raw voice interpretation.

### Sensitive examples

- enable live deployment
- bind strategy to live account
- submit live venue order
- change account permissions
- alter risk caps

### Required confirmation pattern

1. user speaks intent
2. system restates exact action in voice and text
3. user confirms
4. visual approval action is presented
5. only then may the system proceed

### Example

User: “Enable this strategy live on Binance futures.”

System spoken response:
“Your request is to enable strategy X on Binance Futures account Y in live mode. This action requires confirmation. Review the details on screen.”

Visual response:
- strategy id
- account
- venue
- symbols
- risk caps
- approval button

---

## 10. Conversational Strategy Intake by Voice

Voice is especially powerful for strategy intake.

### Flow

1. user describes strategy verbally
2. system transcribes and detects family candidates
3. system asks clarification questions
4. system generates draft
5. system reads a concise summary aloud
6. user approves test or requests revision

### Example interactions

- “Create a London-session gold strategy after order-block mitigation.”
- “Use a fixed 2R target and do not hold after New York closes.”
- “No, I want touch entry, not close confirmation.”

### Requirement

The full draft must still appear in text before testing.

---

## 11. Briefing Mode Requirements

Briefing Mode should be optimized for short, high-value summaries.

### Daily briefing examples

- account status
- top active strategy
- pending approvals
- risk state
- disconnected venues
- strategies degrading

### Maximum style rule

Voice briefings should be short and structured.
Avoid long spoken paragraphs.
Prefer short operating bullets.

### Example

“Two items require approval. MT5 is connected. Binance sync is stale. Strategy XAU order-block is active in paper. BTC sweep strategy failed out-of-sample and remains candidate.”

---

## 12. Alert Mode Requirements

Alerts should be concise, unmistakable, and low-latency.

### High-priority spoken alerts

- MT5 disconnected
- exchange authentication failed
- live order rejected
- drawdown limit reached
- strategy quarantined
- reconciliation mismatch detected

### Alert style

Use short, direct phrasing.
Example:

- “Alert: MT5 connection lost.”
- “Alert: live order rejected on Binance.”
- “Alert: strategy BTC sweep quarantined.”

### Rule

Alerts should not force long spoken explanations.
Details belong in the visible panel.

---

## 13. Account Companion UI Requirements

The voice layer should live inside the account companion tab.

### Required visible controls

- Start Voice
- Push to Talk
- Stop Listening
- Read Summary
- Daily Briefing
- Repeat Last Response
- Mute Alerts

### Required voice state indicators

- listening
- transcribing
- understanding
- preparing action
- awaiting approval
- speaking
- error

### Required context strip

Show:

- active account
- active venue
- paper/live mode
- current strategy
- pending approvals count
- last important risk alert

---

## 14. MT5 and CEX Integration

The voice layer should understand venue differences.

### MT5 examples

- “What is running on my MT5 account?”
- “Enable this strategy on my MT5 paper account.”
- “Why was gold blocked?”

### CEX examples

- “Can this strategy run on Binance Futures?”
- “Bind it to my OKX paper account.”
- “Explain the latest rejected order on Binance.”

### Rule

The voice assistant may discuss venue compatibility.
It may prepare deployment or execution actions.
It must not silently finalize live venue actions.

---

## 15. Dashboard Integration

The dashboard should expose voice-aware cards.

### Control Room additions

- voice companion ready/not ready
- last spoken alert
- pending spoken confirmations

### Research Lab additions

- read-out summary for latest validation
- explain strategy button

### Risk Governor additions

- speak current risk briefing
- explain latest veto

### Execution Monitor additions

- read latest rejection
- summarize fill quality

### Strategy Registry additions

- read promotion readiness
- explain quarantine reason

---

## 16. Logging and Audit Requirements

The voice system must preserve a structured record of:

- transcript text
- detected intent
- referenced entities (strategy/account/venue)
- structured action prepared
- whether approval was requested
- whether approval was granted or denied
- timestamp

### Reason

Without this, voice becomes ungoverned and hard to audit.

---

## 17. Error Handling Requirements

Voice input will sometimes be wrong.
The system must fail safely.

### Failure cases

- bad transcription
- ambiguous venue name
- ambiguous strategy reference
- unsupported command
- user changes intent mid-sentence

### Required behavior

- restate uncertainty clearly
- ask targeted follow-up question
- do not assume a sensitive action
- keep the partial transcript visible

### Example

“I found two Binance-linked accounts and two BTC strategies. Which combination do you want?”

---

## 18. Recommended Persistence Objects

Suggested persistence records:

- `VoiceInteractionRecord`
- `VoiceTranscriptRecord`
- `VoiceIntentRecord`
- `VoiceApprovalRecord`

### Suggested fields

- interaction id
- user id
- account id if relevant
- transcript
- final interpreted text
- intent type
- target strategy id
- target account id
- target venue
- action summary
- approval_required
- approval_status
- created at

---

## 19. Suggested Module Layout

Suggested new modules:

- `operations/voice_companion.py`
- `operations/voice_intents.py`
- `operations/voice_prompts.py`
- `operations/voice_state.py`
- `governance/voice_approvals.py`

These should call into existing strategy, lab, risk, execution, and account services rather than duplicating business logic.

---

## 20. Implementation Order

### Phase 1 — Safe text-backed voice intake

Implement:

- voice transcription
- intent parsing
- conversational strategy intake
- briefing mode
- text-backed approvals

### Phase 2 — Account and strategy operations

Implement:

- voice review of account state
- strategy result explanation
- pending approval readout
- venue/account binding preparation

### Phase 3 — Full governed operating layer

Implement:

- alert mode
- approval readout mode
- runtime paper-action support
- deeper MT5/CEX-specific voice flows

### Phase 4 — Advanced experience

Implement:

- personalized briefings
- scheduled voice summaries
- role-based phrasing
- adaptive clarification prompts

---

## 21. Highest-Value End State

The best end state is a voice-enabled personal operating companion that allows the account owner to:

- describe a strategy naturally
- understand what the platform changed and why
- review validation outcomes quickly
- control account bindings safely
- receive risk and execution briefings hands-free
- approve live actions only through governed confirmation

This would make voice a real operational advantage rather than a novelty.

---

## 22. Final Operating Standard

The voice system is successful only when it can help the user answer and act on:

- what did I ask the platform to do?
- what did the platform understand?
- what strategy/account/venue is being discussed?
- what action is ready now?
- what still needs my approval?
- what changed in my account, strategies, or risk state?

That is the required standard for a governed voice companion.
