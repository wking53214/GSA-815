# GSA-815

A governed adaptive processing architecture for controlled decision-making, execution, simulation, learning, and system integration. The current implementation is an Interactive Voice Response (IVR) call-center system.

## What this repo actually is

GSA-815 is the **IVR / "Iceberg" application** that was extracted out of the
[`sentinel_os`](https://github.com/wking53214/sentinel_os) governance kernel.
It is the domain-specific consumer; `sentinel_os` is the domain-blind
governance substrate (append-only hash-chained ledger, episode/event schema,
conservation boundary, twin witness).

- **It does not run standalone.** GSA-815's code imports ~16 modules from the
  `sentinel_os` kernel (`episode`, `event_v1`, `governance/`, `cassette_*`,
  `circuit_breaker`, …) which are **deliberately not copied in here** — one
  copy of the kernel, not two that can drift. See [`DEPENDENCIES.md`](DEPENDENCIES.md).
- **The live path** is `production_harness.py` (`IcebergProductionHarness`) and
  `api_server_resilient.py`. A call record goes friction-gate → Claude governor
  → kernel `judge_episode` (shadow) → atomic ledger append.
- **Provenance:** see [`PROVENANCE.md`](PROVENANCE.md). Several root-level
  `gsa-*.py` files and `gsa-governance-core/` descend from an earlier Gemini
  design transcript and are **not on the live path**.

### Running it

You need the `sentinel_os` kernel importable and a local Postgres reachable as
`iceberg`/`iceberg`. [`DEPENDENCIES.md`](DEPENDENCIES.md) has the exact setup
and the current test result (127 passed). Then:

```bash
python3 -m pytest Tests/
```

Everything below describes the architecture the IVR application demonstrates.

## Architectural Purpose

GSA-815 provides a structured environment in which processing, adaptation, simulation, learning, language-model intelligence, and governance can operate together under explicit control.

At a conceptual level:

INPUT / ENVIRONMENT
        ↓
DOMAIN & STATE
        ↓
PROCESSING / INTELLIGENCE
        ↓
DECISION / ACTION
        ↓
OBSERVATION
        ↓
SIMULATION / LEARNING
        ↓
GOVERNANCE CONTROL
        ↓
CONTROLLED EXECUTION

The architecture is intended to support systems in which decisions and actions must remain subject to defined governance constraints while still allowing adaptive processing and intelligent interpretation.

## Core Architectural Areas

The repository contains distinct architectural areas for:

- domain representation;
- processing and decision engines;
- state and latent representations;
- simulation;
- training and adaptation;
- governance;
- control-plane integration;
- language-model integration;
- testing and validation.

These components provide the structural foundation from which a domain-specific implementation can be constructed.

## Language-Model Integration

GSA-815 includes an interface to large language model capabilities as one component of its broader processing and intelligence architecture.

The LLM is not treated as the governing authority of the system. It operates within the surrounding architecture and is subject to the system's processing, state, and governance mechanisms.

This allows language-model capabilities to be used for tasks such as interpretation, reasoning, classification, or other application-specific intelligence while keeping those capabilities within a controlled system boundary.

The architecture therefore separates:

Application / Environment
          ↓
GSA-815 Processing Architecture
          ↓
LLM / Intelligence Capability
          ↓
Governed Decision / Action

The specific role of the language model is determined by the application using the architecture.

## Governance

Governance is treated as an architectural concern rather than as an external reporting layer.

The repository incorporates governance-control-plane functionality and associated kernel material as part of the broader GSA-815 architecture.

This allows governance constraints and control mechanisms to participate directly in system operation rather than being applied only after processing has occurred.

## Current Demonstration Application

The current implementation demonstrates the architecture through an IVR call-center system.

Within that application, the architecture provides a concrete environment for demonstrating concepts such as:

- controlled interaction with an external environment;
- state management;
- decision processing;
- language-model-assisted intelligence;
- adaptive behavior;
- simulation and training;
- governed execution;
- testing of system behavior under defined conditions.

The IVR scenario should be understood as a reference application showing how the underlying architecture functions.

The architecture is not inherently limited to call centers, telecommunications, or IVR systems.

## Adaptive Processing

The architecture provides dedicated areas for processing engines, simulation, training, and latent-state representation.

This separation allows adaptive behavior to be examined independently from the domain-specific application used to demonstrate it.

The objective is not simply to automate a particular workflow, but to provide a framework in which adaptive processing and machine intelligence can operate while remaining subject to explicit system constraints and governance.

## Simulation and Training

Simulation and training components provide mechanisms for evaluating system behavior and developing adaptive behavior under controlled conditions.

These capabilities are part of the architecture rather than requirements imposed by the IVR application.

## Governance Control Plane

GSA-815 includes integration with a governance-control-plane component and associated governance kernel material.

The governance layer provides the architectural mechanism through which system activity can be evaluated against defined controls rather than relying solely on application-level behavior.

The repository documents this governance-control-plane material as co-located with GSA-815 for unified development and deployment.

## Integration Boundaries

GSA-815 is not defined solely as an adapter between two particular repositories.

It provides an architectural processing and governance boundary that can participate in a larger system through defined interfaces and integration points.

The current repository configuration includes specific governance-control-plane integration, but that integration should not be interpreted as limiting the architecture to a single upstream or downstream system.

## Testing

Testing is treated as an architectural component of the repository.

The project includes dedicated test structures intended to evaluate processing, governance, simulation, training, and integration behavior.

Specific guarantees should be interpreted according to the individual implementation and test coverage rather than as a claim of universal system correctness.

## Architectural Model

The most useful abstraction of GSA-815 is:

                 ┌───────────────────────┐
                 │      ENVIRONMENT      │
                 └───────────┬───────────┘
                             ↓
                 ┌───────────────────────┐
                 │   DOMAIN / STATE      │
                 └───────────┬───────────┘
                             ↓
                 ┌───────────────────────┐
                 │ PROCESSING / ENGINES  │
                 └───────────┬───────────┘
                             ↓
                 ┌───────────────────────┐
                 │ LLM / INTELLIGENCE    │
                 └───────────┬───────────┘
                             ↓
                 ┌───────────────────────┐
                 │ DECISION / EXECUTION  │
                 └───────────┬───────────┘
                             ↓
                 ┌───────────────────────┐
                 │ OBSERVATION / STATE   │
                 └───────────┬───────────┘
                             ↓
                 ┌───────────────────────┐
                 │ SIMULATION / TRAINING │
                 └───────────┬───────────┘
                             ↓
                 ┌───────────────────────┐
                 │ GOVERNANCE / CONTROL  │
                 └───────────────────────┘

The LLM is a component within the processing and intelligence pathway. It does not replace the surrounding governance, state, processing, or execution architecture.

The IVR application supplies the current concrete environment in which this model is exercised.

## Design Objective

GSA-815 is intended to provide a reusable architectural foundation for systems that require:

- adaptive processing;
- explicit system state;
- language-model-assisted intelligence;
- simulation and training;
- governed decision-making;
- controlled execution;
- and integration with broader governance infrastructure.

The current IVR implementation is the reference application used to demonstrate these capabilities.

It is an example of how GSA-815 functions—not the limit of what GSA-815 is.