# ModelCompass Python Language Rules

This style guide is a list of *dos and don'ts* for Python programs.

**Table of Contents**

- [1. Lint](#s1-lint)
- [2. Imports](#s2-imports)
- [3. Packages](#s3-packages)
- [4. Exceptions](#s4-exceptions)
- [5. Mutable Global State](#s5-mutable-global-state)
- [6. Nested/Local/Inner Classes and Functions](#s6-nested-local-inner-classes-and-functions)
- [7. Comprehensions & Generator Expressions](#s7-comprehensions-generator-expressions)
- [8. Default Iterators and Operators](#s8-default-iterators-and-operators)
- [9. Generators](#s9-generators)
- [10. Lambda Functions](#s10-lambda-functions)
- [11. Conditional Expressions](#s11-conditional-expressions)
- [12. Default Argument Values](#s12-default-argument-values)
- [13. Properties](#s13-properties)
- [14. True/False Evaluations](#s14-true-false-evaluations)
- [16. Lexical Scoping](#s16-lexical-scoping)
- [17. Function and Method Decorators](#s17-function-and-method-decorators)
- [18. Threading](#s18-threading)
- [19. Power Features](#s19-power-features)
- [20. Modern Python: from \_\_future\_\_ imports](#s20-modern-python-from-future-imports)
- [21. Type Annotated Code](#s21-type-annotated-code)


<a id="s1-lint"></a>
### 1. Lint

<!-- TODO: describe ruff, mypy, Flake8 -->

<a id="s2-imports"></a>
### 2. Imports

Use `import` statements for packages and modules only, not for individual types, classes, or functions.

#### 2.1 Definition

Reusability mechanism for sharing code from one module to another.

#### 2.2 Pros

The namespace management convention is simple. 
The source of each identifier is indicated in a consistent way; `x.Obj` says that object `Obj` is defined in module `x`.

#### 2.3 Cons

Module names can still collide. Some module names are inconveniently long.

#### 2.4 Decision

- Use `import x` for importing packages and modules.
- Use `from x import y` where `x` is the package prefix and `y` is the module name with no prefix.
- Use `from x import y as z` in any of the following circumstances:
  - Two modules named `y` are to be imported.
  - `y` conflicts with a top-level name defined in the current module.
  - `y` conflicts with a common parameter name that is part of the public API (e.g. `features`).
  - `y` is an inconveniently long name.
  - `y` is too generic in the context of your code (e.g. `from storage.file_system import options as fs_options`).
- Use `import y as z` only when `z` is a standard abbreviation (e.g. `import numpy as np`).

For example the module `sound.effects.echo` may be imported as follows:

```python
from sound.effects import echo

...
echo.EchoFilter(input, output, delay=0.7, atten=4)
```

Do not use relative names in imports. Even if the module is in the same package, use the full package name. 
This helps prevent unintentionally importing a package twice.

##### 2.4.1 Exemptions

Exemptions from this rule:

Symbols from the following modules are used to support static analysis and type checking:

- `typing`
- `collections.abc`
- `typing_extensions`

<a id="s3-packages"></a>
### 3. Packages

Import each module using the full pathname location of the module.

#### 3.1 Pros

Avoids conflicts in module names or incorrect imports due to the module search path not being what the author expected. 
Makes it easier to find modules.

#### 3.2 Cons

Makes it harder to deploy code because you have to replicate the package hierarchy. 
Not really a problem with modern deployment mechanisms.

#### 3.3 Decision

All new code should import each module by its full package name.

Imports should be as follows:

Yes:

```python
# Reference absl.flags in code with the complete name (verbose).
import absl.flags
from doctor.who import jodie

_FOO = absl.flags.DEFINE_string(...)
```

Yes:

```python
# Reference flags in code with just the module name (common).
from absl import flags
from doctor.who import jodie

_FOO = flags.DEFINE_string(...)
```

*(assume this file lives in `doctor/who/` where `jodie.py` also exists)*

No:

```python
# Unclear what module the author wanted and what will be imported.  The actual
# import behavior depends on external factors controlling sys.path.
# Which possible jodie module did the author intend to import?
import jodie
```

The directory the main binary is located in should not be assumed to be in `sys.path` despite that happening in some environments. 
This being the case, code should assume that `import jodie` refers to a third-party or top-level package named `jodie`, not a local `jodie.py`.

<a id="s4-exceptions"></a>
### 4. Exceptions

Exceptions are allowed but must be used carefully.

#### 4.1 Definition

Exceptions are a means of breaking out of normal control flow to handle errors or other exceptional conditions.

#### 4.2 Pros

The control flow of normal operation code is not cluttered by error-handling code. 
It also allows the control flow to skip multiple frames when a certain condition occurs, e.g., returning from N nested functions in one step instead of having to plumb error codes through.

#### 4.3 Cons

May cause the control flow to be confusing. Easy to miss error cases when making library calls.

#### 4.4 Decision

Exceptions must follow certain conditions:

- Use your own exception classes where possible - this way you distinguish them from exception thrown by libraries
- Do not use `assert` statements in place of conditionals or validating preconditions. They must not be critical to the application logic. A litmus test would be that the `assert` could be removed without breaking the code. `assert` conditionals are [not guaranteed](https://docs.python.org/3/reference/simple_stmts.html#the-assert-statement) to be evaluated. For [pytest](https://pytest.org/) based tests, `assert` is okay and expected to verify expectations. For example:

Yes:

```python
def connect_to_next_port(self, minimum: int) -> int:
    """Connects to the next available port.

    :param minimum: A port value greater or equal to 1024.
    :returns: The new minimum port.
    :raises ConnectionError: If no available port is found.
    """
    if minimum < 1024:
        # Note that this raising of ValueError is not mentioned in the doc
        # string's "Raises:" section because it is not appropriate to
        # guarantee this specific behavioral reaction to API misuse.
        raise ValueError(f"Min. port must be at least 1024, not {minimum}.")
    port = self._find_next_open_port(minimum)
    if port is None:
        raise ConnectionError(f"Could not connect to service on port {minimum} or higher.")
    # The code does not depend on the result of this assert.
    assert port >= minimum, f"Unexpected port {port} when minimum was {minimum}."
    return port
```

No:
  
```python
def connect_to_next_port(self, minimum: int) -> int:
    """Connects to the next available port.

    :param minimum: A port value greater or equal to 1024.

    :returns: the minimum port
    """
    assert minimum >= 1024, "Minimum port must be at least 1024."

    # The following code depends on the previous assert.
    port = self._find_next_open_port(minimum)
    assert port is not None
    # The type checking of the return statement relies on the assert.
    return port
```
  

- Libraries or packages may define their own exceptions. When doing so they must inherit from an existing exception class. Exception names should end in `Error` and should not introduce repetition (`foo.FooError`).
- Never use catch-all `except:` statements, or catch `Exception` or `StandardError`, unless you are
  - re-raising the exception, or
  - creating an isolation point in the program where exceptions are not propagated but are recorded and suppressed instead, such as protecting a thread from crashing by guarding its outermost block.

Python is very tolerant in this regard and `except:` will really catch everything including misspelled names, `sys.exit()` calls, `Ctrl+C` interrupts, `unittest` failures and all kinds of other exceptions that you simply don't want to catch.

- Minimize the amount of code in a `try`/`except` block. The larger the body of the `try`, the more likely that an exception will be raised by a line of code that you didn't expect to raise an exception. In those cases, the `try`/`except` block hides a real error.
- Use the `finally` clause to execute code whether an exception is raised in the `try` block. This is often useful for cleanup, i.e., closing a file.
- Strictly avoid suppressing exceptions without at least logging or rethrowing

No:

```python
try:
    x = f()
except FException:
    pass
```

No:

```python
try:
    x = f()
except FException:
    return
```


<a id="s5-mutable-global-state"></a>
### 5. Mutable Global State

Avoid mutable global state.

#### 5.1 Definition

Module-level values or class attributes that can get mutated during program execution.

#### 5.2 Pros

Occasionally useful.

#### 5.3 Cons

- Breaks encapsulation: Such design can make it hard to achieve valid objectives. For example, if global state is used to manage a database connection, then connecting to two different databases at the same time (such as for computing differences during a migration) becomes difficult. Similar problems easily arise with global registries.
- Has the potential to change module behavior during the import, because assignments to global variables are done when the module is first imported.

#### 5.4 Decision

Avoid mutable global state.

In those rare cases where using global state is warranted, mutable global entities should be declared at the module level or as a class attribute and made internal by prepending an `_` to the name. 
If necessary, external access to mutable global state must be done through public functions or class methods. 
Please explain the design reasons why mutable global state is being used in a comment or a doc linked to from a comment.

Module-level constants are permitted and encouraged. For example:

* `_MAX_HOLY_HANDGRENADE_COUNT = 3` for an internal use constant or
* `SIR_LANCELOTS_FAVORITE_COLOR = "blue"` for a public API constant. 

Constants must be named using all caps with underscores.

<a id="s6-nested-local-inner-classes-and-functions"></a>
### 6. Nested/Local/Inner Classes and Functions

Nested local functions or classes are fine when used to close over a local variable. Inner classes are fine.

#### 6.1 Definition

A class can be defined inside a method, function, or class. A function can be defined inside a method or function. 
Nested functions have read-only access to variables defined in enclosing scopes.

#### 6.2 Pros

Allows definition of utility classes and functions that are only used inside a very limited scope. 
Very [ADT](https://en.wikipedia.org/wiki/Abstract_data_type)-y. Commonly used for implementing decorators.

#### 6.3 Cons

Nested functions and classes cannot be directly tested. Nesting can make the outer function longer and less readable.

#### 6.4 Decision

They are fine with some caveats. Do not nest a function just to hide it from users of a module. 
Instead, prefix its name with an `_` at the module level so that it can still be accessed by tests.

<a id="s7-comprehensions-generator-expressions"></a>
### 7. Comprehensions & Generator Expressions

Okay to use for simple cases.

#### 7.1 Definition

List, Dict, and Set comprehensions as well as generator expressions provide a concise and efficient way to create container types and iterators without resorting to the use of traditional loops, `map()`, `filter()`, or `lambda`.

#### 7.2 Pros

Simple comprehensions can be clearer and simpler than other dict, list, or set creation techniques. 
Generator expressions can be very efficient, since they avoid the creation of a list entirely.

#### 7.3 Cons

Complicated comprehensions or generator expressions can be hard to read.

#### 7.4 Decision

Comprehensions are allowed, however multiple `for` clauses or filter expressions are not permitted.
Optimize for readability, not conciseness.

Yes:

```python
result = [mapping_expr for value in iterable if filter_expr]

result = [
    is_valid(metric={'key': value})
    for value in interesting_iterable
    if a_longer_filter_expression(value)
]

descriptive_name = [
    transform({'key': key, 'value': value}, color='black')
    for key, value in generate_iterable(some_input)
    if complicated_condition_is_met(key, value)
]

result = 

return (x**2 for x in range(10))

unique_names = {user.name for user in users if user is not None}
```

No:

```python
result = [(x, y) for x in range(10) for y in range(5) if x * y > 10]

return ((x, y, z) for x in range(5) for y in range(5) if x != y for z in range(5) if y != z)
```

<a id="s8-default-iterators-and-operators"></a>
### 8. Default Iterators and Operators

Use default iterators and operators for types that support them, like lists, dictionaries, and files.

#### 8.1 Definition

Container types, like dictionaries and lists, define default iterators and membership test operators ("in" and "not in").

#### 8.2 Pros

The default iterators and operators are simple and efficient. 
They express the operation directly, without extra method calls. 
A function that uses default operators is generic. It can be used with any type that supports the operation.

#### 8.3 Cons

You can't tell the type of objects by reading the method names (unless the variable has type annotations). 
This is also an advantage.

#### 8.4 Decision

Use default iterators and operators for types that support them, like lists, dictionaries, and files. 
The built-in types define iterator methods, too. 
Prefer these methods to methods that return lists, except that you should not mutate a container while iterating over it.

Yes:

```python
for key in adict:
    ...
if obj in alist:
    ...
for line in afile:
    ...
for k, v in adict.items():
    ...
```

<a id="s9-generators"></a>
### 9. Generators

Use generators as needed.

#### 9.1 Definition

A generator function returns an iterator that yields a value each time it executes a yield statement. 
After it yields a value, the runtime state of the generator function is suspended until the next value is needed.

#### 9.2 Pros

Simpler code, because the state of local variables and control flow are preserved for each call. 
A generator uses less memory than a function that creates an entire list of values at once.

#### 9.3 Cons

Local variables in the generator will not be garbage collected until the generator is either consumed to exhaustion or itself garbage collected.

#### 9.4 Decision

Fine. Use `yields:` rather than `returns:` in the docstring for generator functions.

If the generator manages an expensive resource, make sure to force the cleanup.

A good way to do the cleanup is by wrapping the generator with a context manager [PEP-0533](https://peps.python.org/pep-0533/).

<a id="s10-lambda-functions"></a>
### 10. Lambda Functions

Okay for one-liners. Prefer generator expressions over `map()` or `filter()` with a `lambda`.

#### 10.1 Definition

Lambdas define anonymous functions in an expression, as opposed to a statement.

#### 10.2 Pros

Convenient.

#### 10.3 Cons

Harder to read and debug than local functions. The lack of names means stack traces are more difficult to understand. 
Expressiveness is limited because the function may only contain an expression.

#### 10.4 Decision

Lambdas are allowed. If the code inside the lambda function spans multiple lines or is longer than 60-80 chars, it might be better to define it as a regular [nested function](#s16-lexical-scoping).

For common operations like multiplication, use the functions from the `operator` module instead of lambda functions. For example, prefer `operator.mul` to `lambda x, y: x * y`.

<a id="s11-conditional-expressions"></a>
### 11. Conditional Expressions

Okay for simple cases.

#### 11.1 Definition

Conditional expressions (sometimes called a "ternary operator") are mechanisms that provide a shorter syntax for if statements. 

For example: 

```python
x = 1 if cond else 2
```

#### 11.2 Pros

Shorter and more convenient than an if statement.

#### 11.3 Cons

May be harder to read than an if statement. The condition may be difficult to locate if the expression is long.

#### 11.4 Decision

Okay to use for simple cases. Each portion must fit on one line: `true`-expression, `if`-expression, `else`-expression. 
Use a complete `if` statement when things get more complicated.

Yes:

```python
one_line = "yes" if predicate(value) else "no"

slightly_split = "yes" if predicate(value) else "no, nein, nyet"

the_longest_ternary_style_that_can_be_done = (
    "yes, true, affirmative, confirmed, correct" if predicate(value) else "no, false, negative, nay"
)
```

No:

```python
bad_line_breaking = "yes" if predicate(value) else "no"
portion_too_long = (
    "yes" if some_long_module.some_long_predicate_function(really_long_variable_name) else "no, false, negative, nay"
)
```

<a id="s12-default-argument-values"></a>
### 12. Default Argument Values

Okay in most cases.

#### 12.1 Definition

You can specify values for variables at the end of a function's parameter list, e.g., `def foo(a, b=0):`. If `foo` is called with only one argument, `b` is set to 0. If it is called with two arguments, `b` has the value of the second argument.

#### 12.2 Pros

Often you have a function that uses lots of default values, but on rare occasions you want to override the defaults. 
Default argument values provide an easy way to do this, without having to define lots of functions for the rare exceptions. As Python does not support overloaded methods/functions, default arguments are an easy way of "faking" the overloading behavior.

#### 12.3 Cons

Default arguments are evaluated once at module load time. 
This may cause problems if the argument is a mutable object such as a list or a dictionary. 
If the function modifies the object (e.g., by appending an item to a list), the default value is modified.

#### 12.4 Decision

Okay to use with the following caveat:

Do not use mutable objects as default values in the function or method definition.

Yes: 

```python
def foo(a, b=None):
    if b is None:
        b = []  # Could still get passed to unchecked code.
```

<a id="s13-properties"></a>
### 13. Properties

Properties may be used to control getting or setting attributes that require trivial computations or logic. 
Property implementations must match the general expectations of regular attribute access: that they are cheap, straightforward, and unsurprising.

#### 13.1 Definition

A way to wrap method calls for getting and setting an attribute as a standard attribute access.

#### 13.2 Pros

- Allows for an attribute access and assignment API rather than getter and setter method calls.
- Can be used to make an attribute read-only.
- Allows calculations to be lazy.
- Provides a way to maintain the public interface of a class when the internals evolve independently of class users.

#### 13.3 Cons

- Can hide side effects much like operator overloading.
- Can be confusing for subclasses.

#### 13.4 Decision

Properties are allowed, but, like operator overloading, should only be used when necessary and match the expectations of typical attribute access; follow getter and setter rules otherwise.

For example, using a property to simply both get and set an internal attribute isn't allowed: there is no computation occurring, so the property is unnecessary (make the attribute public instead). 
In comparison, using a property to control attribute access or to calculate a *trivially* derived value is allowed: the logic is simple and unsurprising.

Properties should be created with the `@property` [decorator](#s17-function-and-method-decorators).
Manually implementing a property descriptor is considered a [power feature](#s19-power-features).

Inheritance with properties can be non-obvious. 
Do not use properties to implement computations a subclass may ever want to override and extend.

<a id="s14-true-false-evaluations"></a>
### 14. True/False Evaluations

Use the "implicit" false if at all possible (with a few caveats).

#### 14.1 Definition

Python evaluates certain values as `False` when in a boolean context. 
A quick "rule of thumb" is that all "empty" values are considered false, so `0, None, , ''` all evaluate as `False` in a boolean context.

#### 14.2 Pros

Conditions using Python booleans are easier to read and less error-prone. In most cases, they're also faster.

#### 14.3 Cons

May look strange to C/C++ developers.

#### 14.4 Decision

Use the "implicit" false if possible, e.g. `if foo:` rather than `if foo !=`  

<a id="s16-lexical-scoping"></a>
### 16. Lexical Scoping

Okay to use.

#### 16.1 Definition

A nested Python function can refer to variables defined in enclosing functions, but cannot assign to them. 
Variable bindings are resolved using lexical scoping, that is, based on the static program text. 
Any assignment to a name in a block will cause Python to treat all references to that name as a local variable, even if the use precedes the assignment. 
If a global declaration occurs, the name is treated as a global variable.

An example of the use of this feature is:

```python
def get_adder(summand1: float) -> Callable[[float], float]:
    """Returns a function that adds numbers to a given number."""

    def adder(summand2: float) -> float:
        return summand1 + summand2

    return adder
```

#### 16.2 Pros

Often results in clearer, more elegant code. 
Especially comforting to experienced Lisp and Scheme (and Haskell and ML and ...) programmers.

#### 16.3 Cons

Can lead to confusing bugs.

```python
i = 4


def foo(x: Iterable[int]):
    def bar():
        print(i, end="")

    # ...
    # A bunch of code here
    # ...
    for i in x:  # Ah, i *is* local to foo, so this is what bar sees
        print(i, end="")
    bar()
```


So `foo([1, 2, 3])` will print `1 2 3 3`, not `1 2 3 4`.

#### 16.4 Decision

Okay to use.

<a id="s17-function-and-method-decorators"></a>
### 17. Function and Method Decorators

Use decorators judiciously when there is a clear advantage. Limit use of `staticmethod` and `classmethod`.

#### 17.1 Definition

[Decorators for Functions and Methods](https://docs.python.org/3/glossary.html#term-decorator) ("the `@` notation"). 
One common decorator is `@property`, used for converting ordinary methods into dynamically computed attributes. 
However, the decorator syntax allows for user-defined decorators as well. 

Specifically, for some function `my_decorator`, this:

```python
class C:
    @my_decorator
    def method(self):
        pass
```

is equivalent to:

```python
class C:
    def method(self):
        # method body ...
    method = my_decorator(method)
```

#### 17.2 Pros

Elegantly specifies some transformation on a method; the transformation might eliminate some repetitive code, enforce invariants, etc.

#### 17.3 Cons

Decorators can perform arbitrary operations on a function's arguments or return values, resulting in surprising implicit behavior. 
Additionally, decorators execute at object definition time. 
For module-level objects (classes, module functions, ...) this happens at import time. 
Failures in decorator code are pretty much impossible to recover from.

#### 17.4 Decision

Use decorators judiciously when there is a clear advantage. 
Decorators should follow the same import and naming guidelines as functions. 
A decorator docstring should clearly state that the function is a decorator. 
Write unit tests for decorators.

Avoid external dependencies in the decorator itself (e.g. don't rely on files, sockets, database connections, etc.), since they might not be available when the decorator runs (at import time, perhaps from `pydoc` or other tools). 
A decorator that is called with valid parameters should (as much as possible) be guaranteed to succeed in all cases.

Decorators are a special case of top-level code.

Use `classmethod` only when writing a named constructor, or a class-specific routine that modifies necessary global state such as a process-wide cache.

<a id="s18-threading"></a>
### 18. Threading

Do not rely on the atomicity of built-in types.

While Python's built-in data types such as dictionaries appear to have atomic operations, there are corner cases where they aren't atomic (e.g. if `__hash__` or `__eq__` are implemented as Python methods) and their atomicity should not be relied upon. 
Neither should you rely on atomic variable assignment (since this in turn depends on dictionaries).

Use the `queue.Queue` data type as the preferred way to communicate data between threads. 
Otherwise, use the `threading` module and its locking primitives. 
Prefer condition variables and `threading.Condition` instead of using lower-level locks.

<a id="s19-power-features"></a>
### 19. Power Features

Use these features only if absolutely necessary, usually in large libraries or frameworks.

#### 19.1 Definition

Python is an extremely flexible language and gives you many fancy features such as custom metaclasses, access to bytecode, on-the-fly compilation, dynamic inheritance, object reparenting, import hacks, reflection (e.g. some uses of `getattr()`), modification of system internals, `__del__` methods implementing customized cleanup, etc.

#### 19.2 Pros

These are powerful language features. They can make your code more compact.

#### 19.3 Cons

It's very tempting to use these "cool" features when they're not absolutely necessary. 
It's harder to read, understand, and debug code that's using unusual features underneath. 
It doesn't seem that way at first (to the original author), but when revisiting the code, it tends to be more difficult than code that is longer but is straightforward.

#### 19.4 Decision

Use only if the advantage clearly outweighs the complexity.

<a id="s20-modern-python-from-future-imports"></a>
### 20. Modern Python: from `__future__` imports

New language version semantic changes may be gated behind a special future import to enable them on a per-file basis within earlier runtimes.

#### 20.1 Definition

Being able to turn on some of the more modern features via `from __future__ import` statements allows early use of features from expected future Python versions.

#### 20.2 Pros

This has proven to make runtime version upgrades smoother as changes can be made on a per-file basis while declaring compatibility and preventing regressions within those files. 

#### 20.3 Cons

Such code may not work on very old interpreter versions prior to the introduction of the needed future statement. 

#### 20.4 Decision

##### from `__future__` imports 

<a id="s21-type-annotated-code"></a>
### 21. Type Annotated Code

You can annotate Python code with [type hints](https://docs.python.org/3/library/typing.html). 
Type-check the code at build time with a type checking tool like [pytype](https://github.com/google/pytype). 
In most cases, when feasible, type annotations are in source files. 
For third-party or extension modules, annotations can be in [stub `.pyi` files](https://peps.python.org/pep-0484/#stub-files).

#### 21.1 Definition

Type annotations (or "type hints") are for function or method arguments and return values:

```python
def func(a: int) -> list[int]:
```

You can also declare the type of variable using similar syntax:

```python
a: SomeType = some_func()
```

#### 21.2 Pros

Type annotations improve the readability and maintainability of your code. 
The type checker will convert many runtime errors to build-time errors, and reduce your ability to use [Power Features](#s19-power-features).

#### 21.3 Cons

You will have to keep the type declarations up to date. 
You might see type errors that you think are valid code. 
Use of a [type checker](https://github.com/google/pytype) may reduce your ability to use [Power Features](#s19-power-features).

#### 21.4 Decision

You are strongly encouraged to enable Python type analysis when updating code. 
When adding or modifying public APIs, include type annotations and enable checking via pytype in the build system. 
As static analysis is relatively new to Python, we acknowledge that undesired side effects (such as wrongly inferred types) may prevent adoption by some projects.
In those situations, authors are encouraged to add a comment with a `TODO` or link to a bug describing the issue(s) currently preventing type annotation adoption in the `BUILD` file or in the code itself as appropriate.
