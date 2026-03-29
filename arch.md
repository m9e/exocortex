# Exocortex / Ghost Architecture Notes

## Thesis

- **Canonical self is not the same thing as a Ghost.**
- A **Ghost** is an embodied, channel-facing projection of self with bounded authority.
- **OpenClaw** is a strong runtime for Ghosts.
- **Your exocortex core** should remain the executive and source of truth.

## Core definitions

- **Canonical Self Fabric**: ground-truth ledger + autobiographical memory + preference graph + objective graph + relationship graph + policy graph.
- **Identity Compiler**: converts authored human outputs into a canonical self model.
- **Facet Compiler**: produces bounded projections of self for contexts like work, public, research, or family.
- **Ghost**: an OpenClaw agent/workspace/session bundle powered by one facet projection.
- **Executive Core**: policy, routing, salience, objective management, approval, audit.
- **Worker Fabrics**: DeerFlow for open-ended work, Gas Town for repo-centric coding swarms, local/frontier models for direct tasks.

## Diagram 1 — top-level stack

```mermaid
flowchart TB
    H[Human]
    C[Canonical Self Fabric<br />truth ledger + memory + objectives + relationships + policy]
    IC[Identity Compiler]
    FC[Facet Compiler / Membranes]
    EX[Executive Core<br />attention + routing + approvals + budget + audit]

    G1[Ghost: Main Private Self<br />OpenClaw instance]
    G2[Ghost: Work Self<br />OpenClaw instance]
    G3[Ghost: Public Self<br />OpenClaw instance]
    G4[Ghost: Research Self<br />OpenClaw instance]

    D[DeerFlow<br />open-ended agent substrate]
    GT[Gas Town<br />repo coding swarm substrate]
    LM[Local model fleet<br />cheap bulk cognition]
    FM[Frontier specialists<br />Codex / Claude / Gemini]

    H --> IC --> C --> FC
    C <--> EX
    FC --> G1
    FC --> G2
    FC --> G3
    FC --> G4

    EX --> G1
    EX --> G2
    EX --> G3
    EX --> G4

    EX --> D
    EX --> GT
    EX --> LM
    EX --> FM

    G1 --> EX
    G2 --> EX
    G3 --> EX
    G4 --> EX
```

## Diagram 2 — human-out ingestion

```mermaid
flowchart LR
    A[Dictated messages]
    B[Phone calls / transcripts]
    C[Emails sent]
    D[Social posts]
    E[Code edits accepted]
    F[Calendar commitments]
    G[Notes / docs]

    N[Normalization / attribution / redaction]
    L[Immutable truth ledger]
    X[Extractors<br />style, preferences, commitments, topics, relationships]
    M[Canonical memory graph]
    O[Objective / obligation graph]
    P[Policy / boundary graph]

    A --> N
    B --> N
    C --> N
    D --> N
    E --> N
    F --> N
    G --> N

    N --> L
    L --> X
    X --> M
    X --> O
    X --> P
```

## Diagram 3 — Ghost as embodied projection

```mermaid
flowchart TB
    C[Canonical Self Fabric]
    F[Facet spec<br />role + relationships + allowed domains + tone + risk limits]
    P[Projection pack<br />SOUL / IDENTITY / USER / MEMORY / standing orders]
    O[OpenClaw Ghost]
    CH[Channels<br />voice, chat, phone, messaging]

    C --> F --> P --> O --> CH
```

## Diagram 4 — authority membrane

```mermaid
flowchart TB
    U[User / event / standing order]
    G[Ghost]
    EX[Executive Core]

    subgraph Policy membrane
      A[Allowed scopes]
      B[Relationship boundaries]
      C[Risk tier]
      D[Budget tier]
      E[Disclosure rules]
      F[Approval gates]
    end

    U --> G --> EX
    EX --> A
    EX --> B
    EX --> C
    EX --> D
    EX --> E
    EX --> F
```

## Diagram 5 — deeper work escalation

```mermaid
flowchart LR
    G[Ghost receives task]
    T{Can Ghost handle<br />inside its rights + budget?}
    S[Respond directly]
    R[Send intent + context to executive]
    K{Task class?}
    L[Local models<br />extract / summarize / draft / classify]
    D[DeerFlow<br />research / synthesize / artifact generation]
    GT[Gas Town<br />repo work / swarms / merge flows]
    F[Frontier specialist<br />judge / architecture / risky review]
    B[Result bundle]
    G2[Ghost delivers outcome<br />with correct persona and disclosure]

    G --> T
    T -- yes --> S --> G2
    T -- no --> R --> K
    K --> L
    K --> D
    K --> GT
    K --> F
    L --> B
    D --> B
    GT --> B
    F --> B
    B --> G2
```

## Diagram 6 — memory promotion

```mermaid
flowchart TD
    RT[Recent action log<br />append-only, immutable]
    ST[Short-term session traces]
    EV[Event extractor]
    WG[Warm graph memory<br />people, projects, obligations, preferences]
    LT[Curated long-term memory]
    FAC[Facet-specific memory views]

    RT --> EV
    ST --> EV
    EV --> WG --> LT --> FAC
```

## Suggested control principles

1. **Whole self is not an API.** Every Ghost gets a bounded projection, not the raw total self.
2. **Ghosts do not own truth.** They consume truth and produce actions.
3. **Canonical truth must be append-only first, summarized second.**
4. **Every outward action writes to the action ledger before or at execution time.**
5. **Facet projection is explicit.** Work-self, public-self, partner-self, research-self should not silently bleed into one another.
6. **High-risk acts route through approval or frontier review.**
7. **OpenClaw is embodiment; the exocortex core is sovereignty.**

## One-line operating model

**Human outputs train the canonical self; the canonical self compiles bounded facets; bounded facets animate Ghosts; Ghosts invoke the executive; the executive routes into worker fabrics; all actions flow back into the truth ledger.**
