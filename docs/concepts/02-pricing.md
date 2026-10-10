# 02. Pricing and cost estimates

**Level:** beginner · **Time:** 10 minutes · **Needs:** [01. Models](01-models.md)

This tutorial explains how prices are stored and what an estimate can and cannot promise.

## Step 1: Know how prices are stored

Normalized price values are `decimal.Decimal`. JSON outputs encode them as strings to preserve precision. OpenRouter prompt and completion prices are interpreted as per-token rates.

## Step 2: See how an estimate is formed

`estimate_cost` multiplies the known rate by the caller-provided estimated token count. It does not infer token counts from text. Conditional pricing overrides are resolved using the request's estimated prompt-token count.

## Step 3: Recognize an incomplete estimate

An estimate is incomplete (`amount_usd=None`) when:

- a nonzero token count lacks a corresponding price, or
- a token count is unknown.

An explicit zero price is not confused with a missing price. Missing means unknown, never free.

## Step 4: Remember what an estimate is not

The estimate is not a guarantee of a provider's final bill. Actual costs from execution are stored separately as empirical observations (see [05. Observations](05-observations.md)).

## What you learned

- Prices are `Decimal` per-token rates.
- Zero and missing are different things.
- Estimates and actual bills are kept apart.

## Next

[03. Request profiles](03-request-profile.md) describes the other half of an estimate: the request.
