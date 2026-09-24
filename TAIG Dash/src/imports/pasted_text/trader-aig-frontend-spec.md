You are the lead frontend engineer, frontend architect, product-minded UI builder, and interaction systems designer for this repository.

Your mission is to build the full frontend application for:

# TraderAIG Institutional Operating Core

This is an institutional-style trading and research operating system.
It is not a generic fintech dashboard.
It is not a meme trading interface.
It is not a toy portfolio app.

It is a serious operating environment for:
- research
- market regime understanding
- thesis construction
- risk-governed decision making
- strategy validation
- promotion queues
- paper execution workflows
- learning, replay, and audit trails
- subscriber premium experience

The frontend must feel:
- premium
- intelligent
- interactive
- educational
- explainable
- trustworthy
- technically sharp
- dynamic but disciplined

---

# OPERATING RULES

1. Understand the repository before changing anything.
2. Inspect existing backend/API structure before designing frontend contracts.
3. Reuse existing concepts and workflows from the project.
4. Do not invent backend features if they do not exist; if a UI surface needs a missing API, define it clearly as a required stub or adapter.
5. Prefer production-ready, modular, typed frontend code.
6. Build a cohesive system, not isolated pages.
7. Keep changes reversible and organized.
8. Use a consistent design system and component architecture.
9. Make the app visually rich but never noisy.
10. Every UI action must reflect actual workflow state.
11. Risk, auditability, paper mode, and validation state must always be represented clearly.
12. Subscriber-only value must feel real and premium.

---

# FIRST ACTIONS

Before implementation:
- inspect repository structure
- inspect API/backend routes
- inspect strategy-lab related modules
- inspect workflow/persistence/research/risk concepts
- identify frontend absence or current frontend state
- determine where the frontend should live in the repo
- determine whether to create a dedicated `frontend/` app or integrate into an existing structure

Then create a short implementation plan.

Do not immediately dump code without discovery.

---

# GOAL

Build a complete, high-quality frontend for the entire product, including public marketing pages and authenticated app surfaces.

The result should be something a user can actually use to:
- understand the platform
- onboard
- manage subscription value
- explore research
- use Strategy Lab
- run paper workflows
- see risk status
- inspect audit trails
- learn from outcomes

---

# PRODUCT STRUCTURE TO BUILD

The frontend must include these major surfaces:

## 1. Public Marketing Site
Build:
- Hero section
- Product thesis section
- “How it works” section
- Why paper-first matters
- Explainability / auditability value
- Strategy Lab teaser
- Subscriber premium value section
- Pricing / entitlement comparison
- FAQ
- Final CTA

This landing page must feel premium, institutional, and modern.

---

## 2. Onboarding Experience
Build:
- welcome flow
- mode selection:
  - Observe
  - Learn
  - Paper Operate
- risk profile setup
- workspace intro
- explain paper vs live boundaries
- initial personalization
- first dashboard launch

Must feel guided and polished.

---

## 3. Authenticated App Shell
Build:
- left sidebar navigation
- top command/search bar
- global status strip
- notification center
- workspace switcher
- subscriber badge / plan chip
- mode indicator
- quick actions area

The app shell should feel like a serious operating terminal with premium SaaS polish.

---

## 4. Command Center / Home Dashboard
Build widgets for:
- market regime overview
- active theses
- latest observations
- promotion queue summary
- paper execution status
- learning insights
- risk warnings
- watchlist / monitored symbols
- subscriber-only insights panel
- “what should I do next?” intelligent recommendation card

This should be the main operating dashboard.

---

## 5. Research Workspace
Build:
- multi-panel layout
- evidence board
- thesis builder
- scenario / risk matrix
- notes panel
- AI explanation panel
- saved research states
- context panels for session / regime / risk

This area should encourage exploration while staying structured.

---

## 6. Strategy Lab
Build:
- strategy contracts list
- create/edit strategy contract form
- validation state display
- risk review display
- observation builder
- observation lifecycle timeline
- promotion queue panel
- paper handoff panel
- paper execution result panel
- audit metadata viewer
- learning notes viewer

This is one of the core product differentiators and must be treated as a premium feature.

---

## 7. Subscriber Dashboard
Build a dedicated premium dashboard with:
- current plan
- unlocked features
- usage / capability status
- saved strategies
- recent paper workflows
- performance summary
- audit history
- learning progression
- upgrade / renewal messaging
- premium intelligence modules
- “what you unlock next” experience

Make subscribers feel:
- privileged
- supported
- upgraded
- institutionally equipped

---

## 8. Paper Workflow Center
Build:
- queued promotion decisions
- approved/vetoed promotion states
- handoff requests
- dispatched requests
- executed paper trades
- request/ticket lifecycle
- result details
- PnL summary
- lessons capture
- replay CTA

This area must reflect the actual project workflow semantics:
- queue
- promotion
- handoff
- intake
- execution
- outcome

---

## 9. Risk & Approval Center
Build:
- current risk policy view
- veto log
- active constraints
- invalidation thresholds
- exposure summaries
- warning stack
- approval boundary explainer
- why-action-was-blocked details

This should look strong, clear, and trustworthy.

---

## 10. Learning Center
Build:
- experience records table
- replay history
- mistakes / lessons clusters
- regime-based insights
- pattern attribution
- progress milestones
- recommendations for improving decision quality
- educational cards

The learning center should make the user smarter over time.

---

# UX REQUIREMENTS

The product must be:
- highly interactive
- dynamic
- layered
- educational
- premium
- easy to navigate
- rich in detail without chaos

Use:
- progressive disclosure
- contextual help
- rich hover states
- panel transitions
- smart empty states
- event-driven badges
- timelines
- accordions
- drawers
- split-panel layouts
- command-like quick actions

Do NOT use childish gamification.
Do NOT make it look like a casino.
Do NOT overuse flashy animations.

---

# VISUAL DESIGN REQUIREMENTS

Create a premium design system with:
- dark-first institutional theme
- optional light mode if time permits
- elegant typography hierarchy
- dense but readable information layouts
- strong spacing system
- refined cards and panels
- data-focused visuals
- subtle gradients
- crisp borders
- meaningful highlights
- restrained motion

Suggested visual feeling:
- Bloomberg Terminal meets premium modern SaaS
- but more inviting, more explainable, more product-led

---

# EDUCATIONAL LAYER

The frontend must teach the user through the UI itself.

Include:
- “why this matters” drawers
- explain-this-decision interactions
- strategy anatomy breakdowns
- glossary tooltips
- replay cards
- what-changed summaries
- risk/reward visual explainers
- contextual education modules
- layered detail for beginner to advanced understanding

The user should learn simply by using the interface.

---

# SUBSCRIPTION / ENTITLEMENT EXPERIENCE

Build entitlement-aware UI:
- clearly show locked vs unlocked capabilities
- premium features should be desirable, not annoying
- avoid cheap dark patterns
- use prestige framing
- explain why a feature matters
- make upgrade paths contextual

Need surfaces for:
- pricing comparison
- current plan summary
- entitlement indicators
- feature-level lock states
- renewal nudges
- premium recommendations

---

# INTERACTION / STATE REQUIREMENTS

The UI must represent these stateful concepts clearly:

- strategy validation state
- observation state
- promotion decision state
- paper request state
- execution state
- risk decision state
- subscriber plan state
- entitlement state
- learning/review status
- empty/loading/error states

Use consistent state chips, colors, icons, and transitions.

---

# FRONTEND TECHNICAL REQUIREMENTS

Build with a modern, maintainable stack.

Preferred stack:
- React
- TypeScript
- Next.js or Vite-based React app
- Tailwind CSS
- component primitives (Radix UI or equivalent)
- state management suited for dashboard workflows
- React Query / TanStack Query for server state
- charting library suited for financial UI
- data grid for audit / logs / learning tables

But first inspect the repo and choose the best fit.
Justify your choice briefly in code comments or documentation if needed.

---

# IMPLEMENTATION REQUIREMENTS

You must produce:

## A. Frontend app structure
Organize clearly, e.g.:
- app / routes
- components
- features
- layouts
- lib
- hooks
- services
- types
- mocks
- theme
- assets

## B. Design system
Create:
- color tokens
- typography tokens
- spacing tokens
- status tokens
- panel/card styles
- buttons
- tabs
- pills
- tables
- empty states
- badges
- command bar
- timeline components

## C. Reusable feature modules
Create modular feature areas for:
- strategy-lab
- paper-workflow
- subscriber-dashboard
- research
- risk-center
- learning

## D. Mock + real API readiness
If backend endpoints are incomplete:
- create adapters
- isolate mock data
- structure calls cleanly
- make it easy to switch to real APIs

Do not hardwire mock data directly into page components.

## E. Responsive behavior
Desktop-first, but ensure tablet usability.
Mobile can be reduced scope, but app shell and major views should degrade gracefully.

---

# SPECIFIC BUILD EXPECTATIONS

You should build actual code, not just describe pages.

At minimum include:
- layout shell
- routing
- navigation
- dashboard pages
- core widgets
- strategy lab pages
- subscriber dashboard page
- risk page
- learning page
- paper workflow page
- landing page
- reusable UI primitives
- typed service layer
- initial API integrations or mocks
- polished styling
- interactive stateful behavior

Where backend data is missing, simulate realistic states using isolated mock services.

---

# API / BACKEND ALIGNMENT

The existing backend includes concepts like:
- strategy contracts
- observations
- risk review
- promotion decisions
- paper execution requests
- workflow facade
- paper workflow endpoint
- audit and learning records

Reflect those structures in frontend types and screens.
Do not flatten everything into generic cards.
Preserve the domain model in the UI.

---

# COPY STYLE

UI copy must be:
- premium
- concise
- intelligent
- explanatory
- not robotic
- not cheesy

Good examples:
- “Validated for paper promotion”
- “Risk gate blocked this strategy before execution”
- “Observation triggered, awaiting promotion review”
- “Paper execution completed and linked to learning record”
- “Subscribers unlock deeper workflow control and replay intelligence”

Bad examples:
- “Awesome! Your trade is super cool 🚀”
- “Let’s gooo”
- “You crushed it king”

---

# QUALITY BAR

What you produce must feel like:
- a real premium SaaS product
- not a demo hack
- not a design dribbble shot
- not a backend admin panel
- not a generic template

Prioritize:
- coherence
- usability
- domain fidelity
- state clarity
- premium finish
- implementation realism

---

# DELIVERY STYLE

When working:
1. inspect repository
2. identify frontend architecture choice
3. create plan
4. build incrementally
5. keep code organized
6. avoid unrelated refactors
7. create or update minimal docs if needed
8. validate build/test paths where possible

If backend gaps exist:
- state them clearly
- isolate them cleanly
- continue with mock-compatible architecture

---

# FINAL GOAL

By the end, the repository should contain a serious frontend product layer that makes TraderAIG feel like a complete premium institutional operating platform with:
- engaging UX
- dynamic screens
- educational depth
- subscriber value
- clear workflow states
- paper-first safety
- audit-friendly visibility

Build the product, not just the pages.
