# ASTRA Phase 9A: Architectural Foundation

STATUS: LOCKED ARCHITECTURE

## 1. ASTRA Mission
ASTRA is a local-first, autonomous computer-agent platform designed to execute complex, multi-step goals across applications, filesystems, and the web. ASTRA acts as a general-purpose agentic runtime, understanding the semantic intent of the user, observing the world state of the host machine, and independently selecting the best providers to execute abstract capabilities.

## 2. Core Architectural Principles
- **Application-Agnostic Design:** The world is modeled as abstract entities (Websites, Files, Processes, Windows, Generic Entities) rather than hardcoded applications (e.g., Spotify, Notepad).
- **Capability-First Execution:** The planner reasons about what it wants to do (e.g., `navigate_browser`, `focus_window`) rather than how to do it.
- **Provider Abstraction:** A capability can be fulfilled by multiple providers (e.g., Playwright, UI Automation). ASTRA dynamically selects the safest and most effective provider based on the environment.
- **Observation over Assumption:** ASTRA must independently observe and verify the world state rather than trusting that an API call's "success" means the user's goal was achieved.
- **Local-First Independence:** The core runtime, semantic resolution, and environment discovery must function seamlessly without relying on cloud-hosted LLM endpoints, treating them as optional external providers.
- **Bounded Recovery:** Failures trigger explicit, bounded recovery strategies (e.g., `REFRESH_OBSERVATION`, `SWITCH_PROVIDER`) rather than blind repetition.

## 3. Goal Contract
A **Goal** represents the final desired state requested by the user. 
- Goals are multi-step and abstract (e.g., "Prepare the report and email it to John").
- Goals are translated into a sequence of Tasks by the planner.
- A Goal is only complete when the final Observation matches the Goal's verification criteria.

## 4. Intent Contract
An **Intent** is the semantic interpretation of a single logical step within a Goal.
- Intents are application-agnostic and capability-driven.
- Example: "Open Amazon in Brave" becomes the Intent `navigate_browser` applied to target `Entity(Website: Amazon)` using `Entity(Browser: Brave)`.
- Intents must never be coupled to specific local application wrappers.

## 5. Entity Contract
An **Entity** is a formalized, semantic representation of an object in the world.
- Entities are categorized strictly (e.g., `Application`, `Website`, `File`, `Folder`, `Document`, `Process`, `Window`, `Browser`, `Browser Tab`, `Device`, `Person`, `Service`, `UI Element`, `Generic Entity`).
- Entity Resolution translates abstract nouns ("it", "Spotify", "the report") into concrete, machine-verifiable objects in the World State.

## 6. Capability Contract
A **Capability** is an independent, abstract operation that the platform can perform.
- Capabilities must be independently discoverable and registrable without core code modification.
- Examples: `navigate_browser`, `read_file`, `interact_with_ui`, `focus_window`, `manage_process`.
- The Planner maps an Intent to a Capability.

## 7. Provider Contract
A **Provider** is a concrete implementation capable of fulfilling a specific Capability.
- Capabilities are 1-to-N with Providers (e.g., `navigate_browser` could be backed by `Playwright`, `Browser DevTools`, or `UI Automation`).
- Providers are selected at runtime based on environment constraints, observation history, and availability.

## 8. World State Contract
The **World State** is a dynamic machine/world representation maintained by the runtime.
- It conceptually represents the environment (processes, windows, displays, audio state, filesystems, network state, interactions).
- The World State explicitly distinguishes between **observed state** (verifiable data from the OS) and **inferred state** (best guesses from LLM reasoning or historical data).

## 9. Observation Contract
An **Observation** is the verifiable result of an executed Action.
- Every meaningful action produces an Observation.
- Observation must differentiate between desired state, observed state, inferred state, and verified state.

## 10. Action Contract
An **Action** is the lowest-level execution of a Provider fulfilling a Capability.
- Actions represent the exact payload/commands sent to the operating system or application (e.g., clicking coordinates, invoking a shell command).
- Actions are strictly bound by the Permission Contract.

## 11. Task Contract
A **Task** is an executable unit of work generated from a Goal, containing one or more Intents.
- Tasks are tracked by the Task Runtime.
- A Task maintains state: Planning, Executing, Observing, Verifying, Recovering, Completed, Failed.
- Tasks support explicit re-planning if verification fails.

## 12. Memory Contract
**Memory** manages contextual retention across steps, tasks, and goals.
- Memory tracks entity references (e.g., allowing "it" to resolve to the previously focused window).
- Memory maintains historical observations to prevent repetitive failure loops.

## 13. Recovery Contract
**Recovery** is an explicit, bounded reaction to a verification failure.
- ASTRA prevents blind repetition of failed actions.
- Permitted recovery strategies include: `REFRESH_OBSERVATION`, `RE_RESOLVE_ENTITY`, `RE_RESOLVE_CAPABILITY`, `SWITCH_PROVIDER`, `REPLAN_TASK`, `REQUEST_USER_CONFIRMATION`, `ABORT_SAFE`.
- Recovery attempts must decrement a bounded retry counter.

## 14. Permission Contract
**Permissions** define strict authorization boundaries for Actions.
- Dangerous operations (e.g., `manage_process(kill)`, `write_file(system_path)`) are never implicitly authorized by LLM generation.
- Permissions require explicit Capability-level grants, configured via policy or user confirmation.

## 15. Execution Architecture
The execution flow strictly adheres to:
1. USER GOAL
2. INTENT
3. ENTITY RESOLUTION
4. WORLD MODEL
5. CAPABILITY DISCOVERY
6. PROVIDER SELECTION
7. TASK PLANNING
8. ACTION EXECUTION
9. OBSERVATION
10. VERIFICATION
11. RECOVERY
12. RESULT

## 16. Provider Architecture
Providers must implement the abstract Provider interface. They register their supported Capabilities and execution constraints during startup. The runtime queries the Provider registry dynamically.

## 17. Local-First Architecture
All core reasoning engines, semantic entity resolvers, world state aggregators, and observation verifiers must execute locally. Cloud LLMs may act as optional Capability Providers for complex reasoning, but the fundamental execution loop must not crash if external network access drops.

## 18. Application-Agnostic Design
No application-specific code is permitted in the core logic. Applications are treated uniformly based on their observed frameworks and available accessibility trees. Custom application logic can only exist as generic Providers implementing abstract Capabilities.

## 19. Extensibility Rules
New capabilities and providers must be added via a plugin/registry system. 
Modifying the central Planner or World State core to add support for a new capability is strictly prohibited.

## 20. Security Boundaries
ASTRA enforces strict isolation:
- No arbitrary, un-sandboxed shell command execution.
- Prevention of path traversal in filesystem Capabilities.
- No exposure of credentials in Memory or Observation logs.
- Uncontrolled process launching is blocked by the Permission Contract.

## 21. Data Ownership & Privacy
Observations, World State data, and Memory are strictly local. Sensitive contextual data must never be transmitted to external Cloud Providers without explicit user consent or anonymization layers.

## 22. Failure Philosophy
"API call returned successfully" is meaningless. Success is defined entirely by independent Observation and Verification. If a state cannot be verified, the Task falls back to Recovery.

## 23. Testing Philosophy
Tests must validate contracts, not applications.
- **DO NOT WRITE:** `test_spotify_search()` or `test_notepad_typing()`.
- **DO WRITE:** `test_browser_navigation_capability()`, `test_text_input_capability()`.
Testing focuses on capability fulfillment, provider fallback, world-state reflection, and semantic resolution.

## 24. Non-Goals
- Phase 9A is NOT building an OS from scratch.
- Phase 9A is NOT providing bespoke support for popular applications (Spotify, Chrome, etc.).
- Phase 9A is NOT replacing human oversight for highly destructive actions (e.g., formatting disks).

## 25. Phase 9A Completion Criteria
- Architecture document is finalized and locked.
- Implementation-impact summary is generated identifying Phase 7/8 components for RETAIN, EXTEND, REFACTOR, DEPRECATE, or REPLACE.
- No implementation code is written.
