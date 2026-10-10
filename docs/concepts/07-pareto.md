# 07. Pareto analysis

**Level:** advanced · **Time:** 15 minutes · **Needs:** [06. Selection](06-selection.md)

Cheap, fast, accurate, and reliable rarely come in one model. In this tutorial you will compute a Pareto frontier so you can see the tradeoffs rather than collapsing them into one score.

## Step 1: Compute a frontier

`pareto_frontier` accepts built-in `ParetoObjective` values or a mapping from metric names to `ObjectiveDirection.MINIMIZE` or `ObjectiveDirection.MAXIMIZE`:

```python
from model_compass.selection import ObjectiveDirection, pareto_frontier

frontier = pareto_frontier(
    candidates,
    {
        "quality": ObjectiveDirection.MAXIMIZE,
        "expected_cost": ObjectiveDirection.MINIMIZE,
        "latency": ObjectiveDirection.MINIMIZE,
        "reliability": ObjectiveDirection.MAXIMIZE,
    },
)
```

## Step 2: Understand dominance

One candidate dominates another only when it is no worse on every selected objective and strictly better on at least one. The frontier is what remains when every dominated candidate is removed.

## Step 3: Know the guarantees

- The calculation is O(n²).
- It does not mutate its input.
- It filters ineligible candidates.
- Output is sorted by canonical model ID.
- Duplicate objective vectors are all retained.

## Step 4: Decide how to treat missing values

Missing objective values are excluded by default (`missing_value_policy="exclude"`). Use `"raise"` to fail when any eligible candidate has an incomplete objective vector.

## Step 5: See who dominates whom

`pareto_analysis` returns the same frontier and maps each dominated model ID to the models that dominate it.

## What you learned

- A frontier keeps every non-dominated tradeoff.
- Missing values are excluded unless you ask otherwise.

## Next

[08. Quality evidence](08-quality.md) explains where the quality numbers come from.
