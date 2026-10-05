# Coverage Requirements Checklist

## Coverage Quick Start

This project requires **85% test coverage** on all code. This is enforced automatically when running tests.

### Running Tests with Coverage

#### Main Project

```powershell
# Install dev dependencies (one-time)
pip install -e .[dev]

# Run tests (coverage check included by default)
pytest

# View detailed coverage report
# Open: .htmlcov/index.html
```

### What This Means

- ✅ All test runs automatically measure and report code coverage
- ✅ Tests **fail** if coverage drops below 85%
- ✅ Failed tests block merging to main branches
- ✅ Coverage reports are always available in `.htmlcov/` directory

### If Coverage Check Fails

1. **Identify uncovered code**: Open `.htmlcov/index.html` in a browser
    - Red lines = not covered by tests
    - Yellow lines = partially covered
    - Green lines = fully covered

2. **Add tests** for the uncovered code, or

3. **Mark intentional exclusions** with `# pragma: no cover`:
   ```python
   def __repr__(self):  # pragma: no cover
       return f"{self.__class__.__name__}()"
   ```

4. **Re-run tests**:
   ```powershell
   pytest
   ```

### Threshold Details

- **Why 85%?** Balances quality with pragmatism
- **Not 100%**: Some code (error paths, UI, etc.) is hard/expensive to test
- **Not below 85%**: Ensures critical code paths are tested

### Configuration

Coverage settings are in `pyproject.toml` and `.coveragerc`

### Tips

- Run specific tests: `pytest tests/test_module.py --cov`
- Faster runs locally: `pytest --no-cov` (but CI will still check)
- Update threshold: Edit `fail_under` in `pyproject.toml` (don't lower!)

## Checklist Before Submitting a Pull Request

### ✅ Local Testing

- [ ] Installed latest dependencies
  ```powershell
  pip install -e .[dev]           # Main project
  ```

- [ ] Ran tests locally with coverage
  ```powershell
  pytest              # Coverage check is automatic
  ```

- [ ] Coverage is ≥ 85%
  - [ ] Terminal output shows ≥ 85%
  - [ ] No "FAILED" message from coverage check

### ✅ Code Review

- [ ] Reviewed uncovered code in `.htmlcov/index.html`
  - [ ] Red lines (uncovered) are intentional or excluded
  - [ ] If uncovered, added `# pragma: no cover` with explanation
  - [ ] New code has test coverage ≥ 85%

- [ ] If coverage decreased:
  - [ ] Added new tests for new code paths
  - [ ] Documented why exclusions are needed
  - [ ] Consulted with team if threshold is concerning

### ✅ Commit & Push

- [ ] Commit message references coverage status
  ```
  feat: Add new feature with 87% coverage
  - Added 5 new test cases
  - Coverage improved from 82% to 87%
  ```

- [ ] Push to feature branch
  - [ ] CI/CD pipeline runs successfully
  - [ ] All coverage checks pass
  - [ ] Coverage reports available in artifacts

### ✅ Pull Request

- [ ] PR description includes:
  - [ ] Coverage before/after numbers
  - [ ] Any code intentionally excluded from coverage
  - [ ] Testing approach for new code

- [ ] Link to coverage report:
  ```markdown
  ## Coverage
  - **Before**: 84%
  - **After**: 86%
  - **Report**: See GitHub Actions artifacts
  ```

- [ ] All CI checks pass (including coverage)
  - [ ] ✅ Coverage: 85%
  - [ ] ✅ All tests pass
  - [ ] ✅ No regressions

## Adding New Code

### For New Modules

1. **Create test file** first (TDD approach):
   ```
   src/model_compass/feature/module.py
   tests/feature/test_module.py  ← Create this first
   ```

2. **Write tests** for all public functions
   ```python
   # tests/feature/test_module.py
   def test_feature_basic():
       """Test basic functionality."""
       result = module.feature(input_data)
       assert result == expected_output
   
   def test_feature_edge_case():
       """Test edge cases."""
       # ...
   ```

3. **Implement module** to pass tests
4. **Run coverage check**: `pytest`
5. **Verify** coverage shows new code is tested

### For New Functions in Existing Modules

1. **Add test case** to relevant test file
2. **Verify test fails** (red):

```powershell
pytest tests/feature/test_module.py::test_new_function
```

3. **Implement function** to pass test
4. **Verify test passes** (green)
5. **Check coverage** includes new code

### Code Patterns to Test

Make sure you test:

- ✅ **Happy path**: Normal, expected usage
  ```python
  def test_happy_path():
      result = function(valid_input)
      assert result == expected_value
  ```

- ✅ **Edge cases**: Boundary conditions
  ```python
  def test_empty_input():
      result = function([])
      assert result is not None
  ```

- ✅ **Error handling**: Invalid inputs
  ```python
  def test_invalid_input():
      with pytest.raises(ValueError):
          function(invalid_input)
  ```

- ✅ **Type variations**: Different input types
  ```python
  def test_with_string():
      ...
  def test_with_int():
      ...
  ```

## When Coverage Drops

If local tests show coverage < 85%:

### Step 1: Identify Coverage Gaps

```powershell
# Open coverage report
open .htmlcov/index.html

# Look for red lines (uncovered code)
```

### Step 2: Three Options

**Option A: Add Tests** (Preferred)
```python
# Add test for uncovered code path
def test_missing_coverage():
    # Test the uncovered line/branch
    ...
```

**Option B: Exclude with Pragma** (Justified Cases)
```python
def error_handler():  # pragma: no cover
    # This code path is hard to test in CI environment
    # Verified manually in local environment
    ...
```

**Option C: Discuss with Team** (If Threshold Too High)
- Consensus needed to lower threshold below 85%
- Document rationale
- Update `fail_under` in configuration

### Step 3: Re-verify

```powershell
pytest
# Should show ≥ 85% and PASS
```

## Troubleshooting

### "Coverage failed: 83% < 85%"

1. Check what's uncovered:
   ```powershell
   pytest --cov-report=term-missing
   ```

2. Open `.htmlcov/index.html` to visualize

3. Add tests or pragma comments

4. Re-run until ≥ 85%

### "Some files show 0% coverage"

1. Verify the source path in `pyproject.toml` matches your package layout,
   e.g. `src/model_compass`.

2. Ensure the test file imports the `model_compass` module.

3. Run from correct directory:
   ```powershell
   uv run pytest -q
   ```

### "HTML report not generated"

1. Ensure `--cov-report=html` in pytest options
2. Check `.htmlcov/` directory exists
3. Try running with explicit flag:
   ```powershell
   pytest --cov --cov-report=html
   ```

## Resources

- **Quick Guide**: `COVERAGE_QUICKSTART.md`
- **Full Documentation**: `docs/configuration/coverage.md`
- **Setup Summary**: `COVERAGE_SETUP_SUMMARY.md`
- **Validation Script**: `python validate_coverage.py`

## Questions?

1. Check documentation first: `docs/configuration/coverage.md`
2. Review project PR discussions for similar issues
3. Ask the team in the development channel
4. Reference [Coverage.py docs](https://coverage.readthedocs.io/)

## Summary

| Action               | Command                       | Expected Result                |
|----------------------|-------------------------------|--------------------------------|
| Run all tests        | `pytest`                      | All pass + 85% coverage        |
| View coverage        | Open `.htmlcov/index.html`    | Colored per-file view          |
| Check specific test  | `pytest tests/test_module.py` | Tests pass + coverage reported |
| Refresh coverage     | `pytest --cov-erase`          | Fresh calculation next run     |
| Find uncovered lines | Look for **red** in HTML      | Know what to test next         |

---

**Remember**: Coverage ≥ 85% is required. Every PR must pass this check. Great tests = Better code! 🚀

## Actual Test Layout

No test files were found under `tests/`.
