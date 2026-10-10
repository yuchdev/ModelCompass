# 01. Models, requests, and evidence

**Level:** beginner · **Time:** 10 minutes · **Needs:** nothing; read this first

This tutorial walks through the three ideas every other page builds on: what a model is, what a request is, and what counts as evidence.

## Step 1: Meet the model

Three types describe a model, from small to large:

- `ModelIdentity` is a provider-scoped logical model, with a canonical ID of the form `provider:model_id`.
- `ModelEndpoint` is an execution endpoint, kept separate. Catalog adapters do not invent endpoint data that their source does not supply.
- `ModelProfile` combines identity, capabilities, pricing, provenance, and retrieval time.

## Step 2: Learn the three-state capability

Capabilities use `SupportStatus.SUPPORTED`, `UNSUPPORTED`, and `UNKNOWN`. Missing catalog fields stay `UNKNOWN`. They are never treated as "no", and they never count as "yes".

## Step 3: Meet the request

`RequestProfile` describes what you need: the task, modalities, context, tool and structured-output needs, and cost, latency, and quality requirements. [03. Request profiles](03-request-profile.md) goes deeper.

## Step 4: Understand evidence

Selection uses only quality observations with the exact requested task. It does not substitute a general benchmark score for task-specific evidence. Every `CandidateAssessment` keeps its eligibility, reasons, estimated cost, and available evidence values, so you can always see why a candidate won or lost.

## What you learned

- A `ModelProfile` is the unit every comparison works on.
- `UNKNOWN` is a real state, not a default.
- Evidence is task-specific.

## Next

[02. Pricing](02-pricing.md) explains how a model's prices are represented.
