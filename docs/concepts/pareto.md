# Pareto analysis

Pareto analysis retains tradeoffs instead of collapsing unlike metrics into one
score. `pareto_frontier` accepts either built-in `ParetoObjective` values or a
mapping from metric names to `ObjectiveDirection.MINIMIZE` /
`ObjectiveDirection.MAXIMIZE`:

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

One candidate dominates another only when it is no worse on every selected
objective and strictly better on at least one. The calculation is O(n²), does
not mutate its input, filters ineligible candidates, and sorts output by
canonical model ID. Duplicate objective vectors are all retained.

Missing objective values are excluded by default (`missing_value_policy="exclude"`).
Use `"raise"` to reject a frontier calculation when any eligible candidate has
an incomplete objective vector. `pareto_analysis` returns the same frontier and
maps dominated model IDs to their dominators.
