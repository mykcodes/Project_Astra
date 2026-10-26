# ASTRA Phase A Architecture

## Canonical World State
ASTRA maintains ONE canonical `WorldState` representation inside `app/domain/entities.py`.
This represents an immutable point-in-time snapshot of the system.
Multiple observations can be tracked by their `ObservationMetadata` timestamp.
The WorldState utilizes strict `TriState` semantics (`TRUE`, `FALSE`, `UNKNOWN`) to enforce that observation failures never equate to logical false.

## Application vs Window State Separation
- **ApplicationInfo**: Tracks identity, running state, and PIDs. It does NOT duplicate window-specific visibility states.
- **WindowInfo**: Tracks authoritative visibility, bounds, title, and handles.
- **Derived State**: Application-level semantic queries (e.g., "is Chrome foreground?") are derived dynamically from WindowInfo records.

## Permission Model
Permissions are contextual and scoped, following the flow:
`USER COMMAND → INTENT → CAPABILITY → RESOURCE → TASK → PERMISSION → AUTHORIZATION DECISION`

The `PermissionEvaluator` evaluates a full `PermissionRequest` representing the WHO, WHAT, and WHY, issuing `PermissionGrant`s that can expire or be revoked.

## Freshness Policies
Observation freshness is consumer-driven.
The `FreshnessEvaluator` assesses the observation timestamp against predefined `FreshnessPolicy` profiles (`REALTIME_POLICY`, `DIAGNOSTIC_POLICY`, etc.).

## Observation Failures
Environmental observation failures are strictly mapped to `ObservationStatus` (`SUCCESS`, `PARTIAL`, `FAILED`) instead of mutating underlying `WorldState` fields to false values.
Structured error types (`ProcessQueryError`, `WindowQueryError`, etc.) prevent broad catch-alls.

<!-- ASTRA Prompt & Architecture Note: Ref #11 -->
