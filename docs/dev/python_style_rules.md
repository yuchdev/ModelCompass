# ModelCompass Python Style Rules

## 0. To review later

- Annotation and typing, Union, Optional
- Exceptions
- Test documentation
- ruff, mypy, Flake8
- Imports formatting - compare to Ruff
- Getters and Setters - check in Python course


## 1. Semicolons

Do not terminate your lines with semicolons, and do not use semicolons to put two statements on the same line.

<a id="line-length"></a>
<a id="s3.2-line-length"></a>
## 2. Line length

The maximum line length is *120 characters*.

Explicit exceptions to the 120-character limit:

- Long import statements.
- URLs, pathnames, or long flags in comments of docstrings
- Long string module-level constants do not contain whitespace that would be inconvenient to split across lines such as URLs or pathnames.
- Pylint disables comments. (e.g. `# pylint: disable=invalid-name`)

Do not use a backslash for [explicit line continuation](https://docs.python.org/3/reference/lexical_analysis.html#explicit-line-joining).

Instead, make use of Python's [implicit line joining inside parentheses, brackets and braces](http://docs.python.org/reference/lexical_analysis.html#implicit-line-joining).
If necessary, you can add an extra pair of parentheses around an expression.

When a literal string doesn't fit on a single line, use parentheses for
implicit line joining.

```python
x = ('This will build a very long long '
    'long long long long long long string')
```

Prefer to break lines at the highest possible syntactic level. If you
must break a line twice, break it at the same syntactic level both
times.

Yes: 

```python
bridgekeeper.answer(
    name="Arthur", quest=questlib.find(owner="Arthur", perilous=True)
)

answer = (a_long_line().of_chained_methods()
      .that_eventually_provides().an_answer())

if (
    config is None
    or 'editor.language' not in config
    or config['editor.language'].use_spaces is False
):
    use_tabs()
```

No:

```python
bridgekeeper.answer(name="Arthur", quest=questlib.find(owner="Arthur", 
perilous=True))
if (config is None or 'editor.language' not in config or config[
  'editor.language'].use_spaces is False):
  use_tabs()
```

Within comments, put long URLs on one line

Yes:  

```python
# See details at
# https://www.example.com/us/developer/documentation/api/content/v2.0/csv_file_name_extension_full_specification.html
```

No:  

```python
# See details at
# https://www.example.com/us/developer/documentation/api/content/\
# v2.0/csv_file_name_extension_full_specification.html
```

Make note regarding the indentation of the elements in the line continuation examples above; see the [indentation](#s3.4-indentation) section for explanation.

## 3. Parentheses

Use parentheses sparingly.

It is not required to use parentheses around tuples. Do not use them in return statements or conditional statements unless using parentheses for implied line continuation or to indicate a tuple.

Yes:

```python
if foo:
    bar()

while x:
    x = bar()

if x and y:
    bar()

if not x:
    bar()

# For a 1 item tuple the ()s are more visually obvious than the comma.

onesie = (foo,)

return foo

return spam, beans

dish = (spam, beans,)

for (x, y) in dict.items(): ...
```

No:

```python
if (x):
    bar()

if not(x):
    bar()

return (foo)
```

Parentheses are redundant for returning the tuple:

Yes:

```python
return foo, bar
```

No:

```python
return (foo, bar)
```

<a id="indentation"></a>
<a id="s3.4-indentation"></a>
## 4. Indentation

Indent your code blocks with *4 spaces*.

Implied line continuation should align wrapped elements vertically (see [line length examples](#s3.2-line-length)), or use a hanging 4-space indent. Closing (round, square or curly) brackets can be placed at the end of the expression, or on separate lines, but then should be indented the same as the line with the corresponding opening bracket.

Yes:

```python
# Aligned with opening delimiter.
foo = long_function_name(var_one, var_two, var_three, var_four)
meal = (spam, beans)

# Aligned with opening delimiter in a dictionary.
foo = {
    'long_dictionary_key': value1 + value2,
    ...
}

# 4-space hanging indent; nothing on first line.
foo = long_function_name(var_one, var_two, var_three, var_four)
meal = (spam, beans)

# 4-space hanging indent; nothing on first line,
# closing parenthesis on a new line.
foo = long_function_name(var_one, var_two, var_three, var_four)
meal = (spam, beans,)

# 4-space hanging indent in a dictionary.
foo = {
    'long_dictionary_key': long_dictionary_value,
    ...
}
```

No:

```python
# Stuff below forbidden.
foo = long_function_name(var_one, var_two,
var_three, var_four)
meal = (spam,
beans)

# 4-space hanging indent forbidden.
foo = long_function_name(
    var_one, var_two, var_three,
    var_four)

# No hanging indent in a dictionary.
foo = {
    'long_dictionary_key':
    long_dictionary_value,
    ...
}
```

### 4.1 Trailing commas in sequences of items?

Trailing commas in sequences of items are recommended only when the closing container token `)`

Yes:

```python
golomb3 = (0, 1, 3,)
```

No:

```python
golomb4 = [0, 1, 4, 6,]
```

## 5. Blank Lines

Two blank lines between top-level definitions, be they function or class definitions. 
One blank line between method definitions and between the docstring of a `class` and the first method. 
No blank line following a `def` line. Use single blank lines as you judge appropriate within functions or methods.

Blank lines need not be anchored to the definition. 
For example, related comments immediately preceding function, class, and method definitions can make sense. 
Strongly prefer your comment to be the part of the docstring.

## 6. Whitespace

Follow standard typographic rules for the use of spaces around punctuation.

No whitespace inside parentheses, brackets or braces.

Yes:

```python
spam(ham[1], {'eggs': 2}, , [ ] )
```

No whitespace before a comma, semicolon, or colon. Do use whitespace
after a comma, semicolon, or colon, except at the end of the line.

Yes:

```python
if x == 4:
    print(x, y)

x, y = y, x
```

No:

```python
if x == 4 :
    print(x , y)

x , y = y , x
```

No whitespace before the open paren/bracket that starts an argument list, indexing or slicing.

Yes:

```python
spam(1)
```

```python
dict['key'] = list[index]
```

No:

```python
spam (1)
```

```python
dict ['key'] = list [index]
```

No trailing whitespace.

Surround binary operators with a single space on either side for assignment (`=`), comparisons (`==, <, >, !=, <>, <=, >=, in, not in, is, is not`), and Booleans (`and, or, not`). 
Use your better judgment for the insertion of spaces around arithmetic operators (`+`, `-`, `*`, `/`, `//`, `%`, `**`, `@`).

Yes:

```python
x == 1
```

No:

```python
x<1
```

Never use spaces around `=` when passing keyword arguments or defining a default parameter value, with one exception: [when a type annotation is present](#typing-default-values), *do* use spaces around the `=` for the default parameter value.

Yes:

```python
def complex(real, imag=0.0): return Magic(r=real, i=imag)
def complex(real, imag: float = 0.0): return Magic(r=real, i=imag)
```

No:

```python
def complex(real, imag = 0.0): return Magic(r = real, i = imag)
def complex(real, imag: float=0.0): return Magic(r = real, i = imag)
```

Don't use spaces to vertically align tokens on consecutive lines, since it becomes a maintenance burden (applies to `:`, `#`, `=`, etc.):

Yes:

```python
foo = 1000  # comment
long_name = 2  # comment that should not be aligned

dictionary = {
    'foo': 1,
    'long_name': 2,
}
```

No:

```python
foo       = 1000  # comment
long_name = 2     # comment that should not be aligned

dictionary = {
    'foo'      : 1,
    'long_name': 2,
}
```

## 7. Shebang Line

Most `.py` files do not need to start with a `#!` line. 
Start the main file of a program with `#!/usr/bin/env python3` (to support virtualenvs) or `#!/usr/bin/python3` per [PEP-394](https://peps.python.org/pep-0394/).

This line is used by the kernel to find the Python interpreter, but is ignored by Python when importing modules. 
It is only necessary on a file intended to be executed directly.

## 8. Comments and Docstrings

Be sure to use the right style for module, function, method docstrings and inline comments.

### 8.1 Docstrings

Python uses *docstrings* to document code. A docstring is a string that is the first statement in a package, module, class or function. 
These strings can be extracted automatically through the `__doc__` member of the object and are used by `pydoc` 
(Try running `pydoc` on your module to see how it looks.) 
Always use the three-double-quote `"""` format for docstrings (per [PEP 257](https://peps.python.org/pep-0257/)). A docstring should be organized as a summary line (one physical line not exceeding 120 characters) terminated by a period, question mark, or exclamation point.
When writing more (encouraged), this must be followed by a blank line, followed by the rest of the docstring starting at the same cursor position as the first quote of the first line.

**Note: Sphinx notation with leading colons (`:param`, `:type`, `:returns`, `:raises`, `:ivar`, etc.) is required for documenting functions, classes, and methods instead of Google style (`Args:`, `Raises:`).**
**If explicitly requested by a project/team, the `@`-prefixed variant (`@param`, `@type`, `@returns`, `@raises`, `@ivar`, etc.) may be supported as a secondary option.**
There are more formatting guidelines for docstrings below.

### 8.2 Modules

Files should start with a docstring describing the contents and usage of the module.

```python
"""A one-line summary of the module or program, terminated by a period.

Leave one blank line.  The rest of this docstring should contain an
overall description of the module or program.  Optionally, it may also
contain a brief description of exported classes and functions and/or usage
examples.

Typical usage example:

foo = ClassFoo()
bar = foo.function_bar()
"""
```

#### 8.2.1 Test modules

Module-level docstrings for test files are not required. 
They should be included only when there is additional information that can be provided.

Examples include some specifics on how the test should be run, an
explanation of an unusual setup pattern, dependency on the external
environment, and so on.

```python
"""This blaze test uses golden files.

You can update those files by running
`blaze run //foo/bar:foo_test -- --update_golden_files` from the `google3` directory.
"""
```

Docstrings that do not provide any new information should not be used.

```python
"""Tests for foo.bar."""
```

### 8.3 Functions and Methods

In this section, "function" means a method, function, generator, or property.

A docstring is mandatory for every function except:

- lambda
- nested function

A docstring should give enough information to write a call to the function without reading the function's code. 
The docstring should describe the function's calling syntax and its semantics, but generally not its implementation details, unless those details are relevant to how the function is to be used. 
For example, a function that mutates one of its arguments as a side effect should note that in its docstring.
Otherwise, subtle but important details of a function's implementation that are not relevant to the caller are better expressed as comments alongside the code than within the function's docstring.

The docstring may be descriptive-style (`"""Fetches rows from a Bigtable."""`) or imperative-style (`"""Fetch rows from a Bigtable."""`), but the style should be consistent within a file.
The docstring for a `@property` data descriptor should use the same style as the docstring for an attribute or a [function argument](#doc-function-args) (`"""The Bigtable path."""`, rather than `"""Returns the Bigtable path."""`).

Certain aspects of a function should be documented using Sphinx notation, using the tags `:param`, `:type`, `:returns`, `:yields`, and `:raises`. The tags must be aligned with the text of the docstring.

#### 8.3.1 Param and Return Tags

<a id="doc-function-args"></a>
[*:param* and *:type:*](#doc-function-args)

`:param name: description` lists a parameter by name and describes it.

`:type name: type` defines the type of the parameter, if not present in the type annotations.

If the description is too long to fit on a single 120-character line, use a hanging indent of 2 or 4 spaces (be consistent with the rest of the docstrings in the file).
If a function accepts `*foo` (variable length argument lists) and/or `**bar` (arbitrary keyword arguments), they should be listed as `:param *foo:` and `:param **bar:`.

#### 8.3.2 Raises Tag

<a id="doc-function-returns"></a>
[*:returns* (or *:yields* for generators):](#doc-function-returns)

`:returns: description` describes the semantics of the return value, including any type information that the type annotation does not provide. If the function only returns `None`, this tag is not required.

`:rtype: type`

If the function uses `yield` (is a generator), the `:yields` tag should document the object returned by `next()`, instead of the generator object itself.

#### 8.3.3 Raises Tag

<a id="doc-function-raises"></a>
[*:raises:*](#doc-function-raises)

`:raises ExceptionType: description` lists exceptions that are relevant to the interface followed by a description.

```python
def fetch_smalltable_rows(
    table_handle: smalltable.Table,
    keys: Sequence[bytes | str],
    require_all_keys: bool = False,
) -> Mapping[bytes, tuple[str, ...]]:
    """Fetches rows from a Smalltable.

    Retrieves rows pertaining to the given keys from the Table instance
    represented by table_handle.  String keys will be UTF-8 encoded.

    :param table_handle: An open smalltable.Table instance.
    :param keys: A sequence of strings representing the key of each table row to fetch.  String keys will be UTF-8 encoded.
    :param require_all_keys: If True only rows with values set for all keys will be returned.
    :returns: A dict mapping keys to the corresponding table row data fetched. Each row is represented as a tuple of strings.
    For example:

        {b'Serak': ('Rigel VII', 'Preparer'),
         b'Zim': ('Irk', 'Invader'),
         b'Lrrr': ('Omicron Persei 8', 'Emperor')}
      
        Returned keys are always bytes.  If a key from the keys argument is
        missing from the dictionary, then that row was not found in the
        table (and require_all_keys must have been False).
    :raises IOError: An error occurred accessing the smalltable.
    """
```

#### 8.3.4 At-sign Sphinx Notation (Secondary, On Request)

If explicitly requested by the project/team, this `@`-prefixed Sphinx variation is also allowed as a secondary option:

```python
def fetch_smalltable_rows(
    table_handle: smalltable.Table,
    keys: Sequence[Union[bytes, str]],
    require_all_keys: bool = False,
) -> Mapping[bytes, tuple[str, ...]]:
    """Fetches rows from a Smalltable.

    Retrieves rows pertaining to the given keys from the Table instance
    represented by table_handle.  String keys will be UTF-8 encoded.

    @param table_handle: An open smalltable.Table instance.
    @param keys: A sequence of strings representing the key of each table row to fetch.  String keys will be UTF-8 encoded.
    @param require_all_keys: If True only rows with values set for all keys will be returned.
    @returns: A dict mapping keys to the corresponding table row data fetched. Each row is represented as a tuple of strings.
    For example:

        {b'Serak': ('Rigel VII', 'Preparer'),
         b'Zim': ('Irk', 'Invader'),
         b'Lrrr': ('Omicron Persei 8', 'Emperor')}
      
        Returned keys are always bytes.  If a key from the keys argument is
        missing from the dictionary, then that row was not found in the
        table (and require_all_keys must have been False).
    @raises IOError: An error occurred accessing the smalltable.
    """
```

### 8.4 Classes

Classes should have a docstring below the class definition describing the class. Public attributes, excluding [properties](python_language_rules.md#s13-properties), should be documented here using `:ivar` (instance variable) or `:type` tags and follow the same formatting as a [function's parameters](#doc-function-args).

```python
class SampleClass:
    """Summary of class here.

    Longer class information...
    Longer class information...

    :ivar likes_spam: A boolean indicating if we like SPAM or not.
    :ivar eggs: An integer count of the eggs we have laid.
    """

    def __init__(self, likes_spam: bool = False):
        """Initializes the instance based on spam preference.

        :param likes_spam: Defines if instance exhibits this preference.
        """
        self.likes_spam = likes_spam
        self.eggs = 0

    @property
    def butter_sticks(self) -> int:
        """The number of butter sticks we have."""
```

All class docstrings should start with a one-line summary that describes what the class instance represents. 
This implies that subclasses of `Exception` should also describe what the exception represents, and not the context in which it might occur. 
The class docstring should not repeat unnecessary information, such as that the class is a class.

Yes:

```python
class CheeseShopAddress:
    """The address of a cheese shop.  
    ...
    """
  
class OutOfCheeseError(Exception):
    """No more cheese is available."""
```

No:

```python
class CheeseShopAddress:
    """Class that describes the address of a cheese shop.  
    ...
    """
  
class OutOfCheeseError(Exception):
    """Raised when no more cheese is available."""
```

### 8.5 Block and Inline Comments

The final place to have comments is in tricky parts of the code. 
If you're going to have to explain it at the next code review, you should comment it now. 
Complicated operations get a few lines of comments before the operations commence.
Try to avoid comments at the end of the line, prefer comments one line above. 

```python
# We use a weighted dictionary search to find out where i is in
# the array.  We extrapolate position based on the largest num
# in the array and the array size and then do binary search to
# get the exact number.

if i & (i-1) == 0:  # True if i is 0 or a power of 2.
```

Never describe the code in comment. 
Assume the person reading the code knows Python (though not what you're trying to do) better than you do.

```python
# BAD COMMENT: Now go through the b array and make sure whenever i occurs
# the next element is i+1
```

### 8.6 Punctuation, Spelling, and Grammar

Pay attention to punctuation, spelling, and grammar; it is easier to
read well-written comments than badly written ones.

Comments should be as readable as narrative text, with proper
capitalization and punctuation. In many cases, complete sentences are
more readable than sentence fragments. Shorter comments, such as
comments at the end of a line of code, can sometimes be less formal, but
you should be consistent with your style.

It is very important that source code maintain a high level of clarity and readability. 
Proper punctuation, spelling, and grammar help with that goal.

## 10. Strings

Prefer the f-string. Do not use the `%` operator as outdated. 
Use the `format()` method only for string parameters passed by name.
For example:

```python
SCORE_TEMPLATE = "The score of {team} if {score}"

score_template = SCORE_TEMPLATE.format(team="Team A", score=42)
```

A single string join with `+` is okay but never format with `+`

Yes:

```python
x = f'name: {name}; score: {n}'
x = '{}, {}'.format(first, second)
x = 'name: {}; score: {}'.format(name, n)
x = a + b
```

No: 

```python
x = first + ', ' + second
x = 'name: ' + name + '; score: ' + str(n)
x = '%s, %s!' % (imperative, expletive)
x = 'name: %s; score: %d' % (name, n)
x = 'name: %(name)s; score: %(score)d' % {'name':name, 'score':n}
```

Avoid using the `+` and `+=` operators to accumulate a string within a loop. 
In some conditions, accumulating a string with addition can lead to quadratic rather than linear running time. 
Although common accumulations of this sort may be optimized on CPython, that is an implementation detail. 
The conditions under which an optimization applies are not easy to predict and may change. 
Instead, add each substring to a list and `''.join` the list after the loop terminates, or write each substring to an `io.StringIO` buffer. 
These techniques consistently have amortized-linear run-time complexity.

Yes:

```python
items = ['<table>']
for last_name, first_name in employee_list:
    items.append('<tr><td>%s, %s</td></tr>' % (last_name, first_name))
items.append('</table>')
employee_table = ''.join(items)
```

No:

```python
employee_table = '<table>'
for last_name, first_name in employee_list:
    employee_table += '<tr><td>%s, %s</td></tr>' % (last_name, first_name)
employee_table += '</table>'
```

Be consistent with your choice of string quote character within a file.
Pick `'` or `"` and stick with it. 
It is okay to use the other quote character on a string to avoid the need to backslash-escape quote characters within the string.

Yes:

```python
  Python('Why are you hiding your eyes?')
  Gollum("I'm scared of lint errors.")
  Narrator('"Good!" thought a happy Python reviewer.')
```

No:

```python
  Python("Why are you hiding your eyes?")
  Gollum('The lint. It burns. It burns us.')
  Gollum("Always the great lint. Watching. Watching.")
```

Use `"""` for multi-line strings rather than `'''`.

Multi-line strings do not flow with the indentation of the rest of the program. 
If you need to avoid embedding extra space in the string, use either concatenated single-line strings or a multi-line string with [`textwrap.dedent()`](https://docs.python.org/3/library/textwrap.html#textwrap.dedent) to remove the initial space on each line:

No:

```python
    long_string = """This is pretty ugly.
Don't do this.
"""
```

Yes:

```python
CONST_TOP_LEVEL = """This is fine if your multiline is
global top-level const."""
```

```python
long_string = """This is fine if your use case can accept
    extraneous leading spaces."""
```

```python
long_string = ("And this is fine if you cannot accept\n" +
               "extraneous leading spaces.")
```

```python
long_string = ("And this too is fine if you cannot accept\n"
               "extraneous leading spaces.")
```

```python
import textwrap

long_string = textwrap.dedent("""\
    This is also fine, because textwrap.dedent()
    will collapse common leading spaces in each line.""")
```
  
Note that using a backslash here does not violate the prohibition against [explicit line continuation](#line-length); in this case, the backslash is escaping a newline in a string literal.

### 10.1 Logging

`%-strings` and `f-strings` are both allowed in logging.

`%-strings` have two practical advantages:

1. Some logging implementations collect the unexpanded pattern-string as a queryable field.
2. They can avoid spending time rendering a message that no logger is configured to output.

`f-strings` evaluate eagerly, so message construction happens before the logger decides whether to emit the message.

Depending on the project, these advantages can be important or not important. For that reason, all three approaches are allowed in logs: `%-strings`, `f-strings`, and `t-strings`.

In Python 3.15+, prefer `t-strings` for logging because they offer delayed build.

The only requirement is consistency: choose one approach for the project and apply it consistently.

Prefer options in the following order

Yes (consistent f-strings):

```python  
import os
from absl import logging

pager = os.getenv('PAGER', default='')
logging.info(f'Current $PAGER is: {pager}')

homedir = os.getenv('HOME')
if homedir is None or not os.access(homedir, os.W_OK):
    logging.error(f'Cannot write to home directory, $HOME={homedir!r}')
```


Yes (consistent %-strings):

```python  
import os
from absl import logging

logging.info('Current $PAGER is: %s', os.getenv('PAGER', default=''))

homedir = os.getenv('HOME')
if homedir is None or not os.access(homedir, os.W_OK):
    logging.error('Cannot write to home directory, $HOME=%r', homedir)
```

Yes (Python 3.15+, consistent t-strings):

```python
import os
from absl import logging

pager = os.getenv('PAGER', default='')
logging.info(t'Current $PAGER is: {pager}')

homedir = os.getenv('HOME')
if homedir is None or not os.access(homedir, os.W_OK):
    logging.error(t'Cannot write to home directory, $HOME={homedir!r}')
```

No (mixed styles in one project):

```python
import os
from absl import logging

pager = os.getenv('PAGER', default='')
logging.info('Current $PAGER is: %s', pager)

homedir = os.getenv('HOME')
if homedir is None or not os.access(homedir, os.W_OK):
    logging.error(f'Cannot write to home directory, $HOME={homedir!r}')
```

### 10.2 Error Messages

Error messages (such as messages on exceptions like `ValueError`, or messages shown to the user) should follow three guidelines:

1.  The message needs to precisely match the actual error condition.

2.  Interpolated pieces need to always be clearly identifiable as such.

3.  They should allow simple automated processing (e.g. grepping).

Yes:

```python
if not 0 <= p <= 1:
    raise ValueError(f'Not a probability: {p=}')

try:
    os.rmdir(workdir)
except OSError as error:
    logging.warning('Could not remove directory (reason: %r): %r',
                    error, workdir)
```

No:

```python
if p < 0 or p > 1:  # PROBLEM: also false for float('nan')!
    raise ValueError(f'Not a probability: {p=}')

try:
    os.rmdir(workdir)
except OSError:
    # PROBLEM: Message makes an assumption that might not be true:
    # Deletion might have failed for some other reason, misleading
    # whoever has to debug this.
    logging.warning('Directory already was deleted: %s', workdir)

try:
    os.rmdir(workdir)
except OSError:
    # PROBLEM: The message is harder to grep for than necessary, and
    # not universally non-confusing for all possible values of `workdir`.
    # Imagine someone calling a library function with such code
    # using a name such as workdir = 'deleted'. The warning would read:
    # "The deleted directory could not be deleted."
    logging.warning('The %s directory could not be deleted.', workdir)
```

## 11. Files, Sockets, and similar Stateful Resources

Explicitly close files and sockets when done with them. 
This rule naturally extends to closeable resources that internally use sockets, such as database connections, and also other resources that need to be closed down in a similar fashion. 

Leaving files, sockets or other such stateful objects open longer than required has many downsides:

- They may consume limited system resources, such as file descriptors. Code that deals with many such objects may exhaust those resources unnecessarily if they're not returned to the system promptly after use.
- Holding files open may prevent other actions such as moving or deleting them, or unmounting a filesystem.
- Files and sockets that are shared throughout a program may inadvertently be read from or written to after logically being closed. If they are actually closed, attempts to read or write from them will raise exceptions, making the problem known sooner.

Furthermore, while files and sockets (and some similarly behaving resources) are automatically closed when the object is destructed, coupling the lifetime of the object to the state of the resource is poor practice:

- There are no guarantees as to when the runtime will actually invoke the `__del__` method. Different Python implementations use different memory management techniques, such as delayed garbage collection, which may increase the object's lifetime arbitrarily and indefinitely.
- Unexpected references to the file, e.g. in globals or exception tracebacks, may keep it around longer than intended.

Relying on finalizers to do automatic cleanup that has observable side effects has been rediscovered over and over again to lead to major problems, across many decades and multiple languages (see e.g. [this article](https://wiki.sei.cmu.edu/confluence/display/java/MET12-J.+Do+not+use+finalizers) for Java).

The preferred way to manage files and similar resources is using the [`with` statement](http://docs.python.org/reference/compound_stmts.html#the-with-statement):

```python
with open("hello.txt") as hello_file:
    for line in hello_file:
        print(line)
```

For file-like objects that do not support the `with` statement, use `contextlib.closing()`:

```python
import contextlib

with contextlib.closing(urllib.urlopen("http://www.python.org/")) as front_page:
    for line in front_page:
        print(line)
```

In rare cases where context-based resource management is infeasible, code documentation must explain clearly how resource lifetime is managed.

## 12. TODO Comments

Use `TODO` comments only for intentional technical debt that has ownership and tracking.

Each `TODO` **must** use this exact metadata prefix:

```python
# TODO: [YYYY-MM-DD][developer-name] debt-slug [issue: #123, https://github.com/org/repo/issues/123] - short action/context
```

Required attributes:

1. `TODO:` in uppercase.
2. `[YYYY-MM-DD]` creation date.
3. `[developer-name]` owner (GitHub handle or team-approved identifier).
4. `debt-slug` in `kebab-case` (stable identifier for this debt item).
5. `[issue: ...]` including the related issue number **and** full issue URL.
6. `- ...` concise explanation of what should be fixed.

Example:

```python
# TODO: [2026-08-05][alice-ng] remove-legacy-parser [issue: #482, https://github.com/acme/service/issues/482] - Delete fallback parser after migration cutover.
```

Do not add TODOs without all fields. Missing owner, date, debt slug, or issue reference makes the debt untraceable and should be treated as invalid.

## 13. Imports formatting

Imports should be on separate lines; there are [exceptions for `typing` and `collections.abc` imports](#typing-imports).

E.g.:

Yes:

```python
from collections.abc import Mapping, Sequence
import os
import sys
from typing import Any, NewType
```

No:

```python
import os, sys
```

Imports are always put at the top of the file, just after any module
comments and docstrings and before module globals and constants. Imports
should be grouped from most generic to least generic:

1.  Python future import statements. For example:

```python
from __future__ import annotations
```

    See [above](python_language_rules.md#s20-modern-python-from-future-imports) for more information about those.

2.  Python standard library imports. For example:

```python
import sys
```

3.  [third-party](https://pypi.org/) module or package imports. For
    example:

```python
import tensorflow as tf
```

4.  Code repository sub-package imports. For example:

```python
from otherproject.ai import mind
```

5.  **Deprecated:** application-specific imports that are part of the
    same top-level sub-package as this file. For example:

```python
from myproject.backend.hgwells import time_machine
```

Within each grouping, imports should be sorted lexicographically, ignoring case, according to each module's full package path (the `path` in `from path import ...`). 
Place a blank line between import sections.

```python
import collections
import queue
import sys

from absl import app
from absl import flags
import bs4
import cryptography
import tensorflow as tf

from book.genres import scifi
from myproject.backend import huxley
from myproject.backend.hgwells import time_machine
from myproject.backend.state_machine import main_loop
from otherproject.ai import body
from otherproject.ai import mind
from otherproject.ai import soul
```

## 14. Statements

Generally only one statement per line.

The only exception is an `if` if there is no `else`.

Yes:

```python
if foo: 
    bar(foo)

if foo: bar(foo)
```

No:

```python
if foo: bar(foo)
else:   baz(foo)

try:               bar(foo)
except ValueError: baz(foo)

try:
    bar(foo)
except ValueError: baz(foo)
```

## 15. Getters and Setters

Getter and setter functions (also called accessors and mutators) should be used when they provide a meaningful role or behavior for getting or setting a variable's value.

In particular, they should be used when getting or setting the variable is complex or the cost is significant, either currently or in a reasonable future.

If, for example, a pair of getters/setters simply read and write an internal attribute, the internal attribute should be made public instead. 
By comparison, if setting a variable means some state is invalidated or rebuilt, it should be a setter function. 
The function invocation hints that a potentially non-trivial operation is occurring.
Alternatively, [properties](python_language_rules.md#s13-properties) may be an option when simple logic is needed, or refactoring to no longer need getters and setters.

Getters and setters should follow the [Naming](#s3.16-naming)
guidelines, such as `get_foo()`
and `set_foo()`.

If the past behavior allowed access through a property, do not bind the new getter/setter functions to the property. 
Any code still attempting to access the variable by the old method should break visibly so they are made aware of the change in complexity.

<a id="s3.16-naming"></a>
## 16. Naming

| Type                       | Public               | Internal                          |
|----------------------------|----------------------|-----------------------------------|
| Packages                   | `lower_with_under`   |                                   |
| Modules                    | `lower_with_under`   | `_lower_with_under`               |
| Classes                    | `CapWords`           | `_CapWords`                       |
| Exceptions                 | `CapWords`           |                                   |
| Functions                  | `lower_with_under()` | `_lower_with_under()`             |
| Global/Class Constants     | `CAPS_WITH_UNDER`    | `_CAPS_WITH_UNDER`                |
| Global/Class Variables     | `lower_with_under`   | `_lower_with_under`               |
| Instance Variables         | `lower_with_under`   | `_lower_with_under` (protected)   |
| Method Names               | `lower_with_under()` | `_lower_with_under()` (protected) |
| Function/Method Parameters | `lower_with_under`   |                                   |
| Local Variables            | `lower_with_under`   |                                   |

Names should be descriptive. 
This includes functions, classes, variables, attributes, files and any other type of named entities.

Avoid abbreviation. 
In particular, do not use abbreviations that are ambiguous or unfamiliar to readers outside your project, do not abbreviate by deleting letters within a word.

Always use a `.py` filename extension. Never use dashes (`-`) in filenames, use underscores (`_`) instead.

### 16.1 Names to Avoid

- single character names, except for specifically allowed cases:
  - counters or iterators (e.g. `i`, `j`, `k`, `v`, et al.)
  - `e` as an exception identifier in `try/except` statements.
  - `f` as a file handle in `with` statements
  - private [type variables](#typing-type-var) with no constraints (e.g. `_T = TypeVar("_T")`, `_P = ParamSpec("_P")`)
  - names that match established notation in a reference paper or algorithm (see [Mathematical Notation](#math-notation))
- dashes (`-`) in any package/module name
- `__double_leading_and_trailing_underscore__` names (reserved by Python)
- names that needlessly include the type of the variable (for example: `id_to_name_dict`)

Please be mindful not to abuse too short naming. 
Generally speaking, descriptiveness should be proportional to the name's scope of visibility. 
For example, `i` might be a fine name for a 5-line code block, but within multiple nested scopes, it is likely too vague.

### 16.2 Naming Conventions

- "Internal" means internal to a module, or protected or private within a class.
- Prepending a single underscore (`_`) has some support for protecting module variables and functions (linters will flag protected member access)
- Note that it is okay for unit tests to access protected constants from the modules under test.
- We discourage its use a double underscore (`__`), as it impacts readability. testability, and isn't *really* private. Prefer a single underscore.
- Place related classes and top-level functions together in a module. Unlike Java, there is no need to limit yourself to one class per module.
- Use `CapWords` for class names, but `lower_with_under` for module names.
- Unit test files follow PEP 8 compliant `lower_with_under` method names, for example, `test_<method_under_test>_<state>`. 

### 16.3 File Naming

Python filenames must have a `.py` extension and must not contain dashes (`-`) 
This allows them to be imported and unit-tested.
If you want an executable to be accessible without the extension, use a symbolic link or a simple bash wrapper containing `exec "$0.py" "$@"`.

<a id="math-notation"></a>
### 16.5 Mathematical Notation

For mathematically heavy code, short variable names that would otherwise violate the style guide are preferred when they match established notation in a reference paper or algorithm.

When using names based on established notation, cite the source of all naming conventions, preferably with a hyperlink to academic resource itself, in a comment or docstring.

## 17. Main

In Python, `pydoc` as well as unit tests require modules to be importable. If a file is meant to be used as an executable, its main functionality should be in a `main()` function, and your code should always check `if __name__ == '__main__'` before executing your main program, so that it is not executed when the module is imported.

When using [absl](https://github.com/abseil/abseil-py), use `app.run`:

```python
from absl import app
...

def main(argv: Sequence[str]):
    # process non-flag arguments
    ...

if __name__ == '__main__':
    app.run(main)
```

Otherwise, use:

```python
def main():
    ...
    return 0

if __name__ == '__main__':
    sys.exit(main())
```

Do not use `SystemExit` exception to exit the program. Use `sys.exit()` instead.

All code at the top level will be executed when the module is imported.

Be careful not to call functions, create objects, or perform other operations that should not be executed when the file is being `pydoc`ed.

## 18. Function length

Prefer small and focused functions.

We recognize that long functions are sometimes appropriate, so no hard limit is placed on function length. If a function exceeds about 40 lines, think about whether it can be broken up without harming the structure of the program.

You could find long and complicated functions when working with some code. 

Do not be intimidated by refactoring existing code, and consider breaking up the function into smaller and more manageable pieces.

## 19. Type Annotations

### 19.1 General Rules

- Use type hints where possible
- Annotate your public APIs.
- Use judgment to get to a good balance between safety and clarity on the one hand, and flexibility on the other.
- Annotate code that is prone to type-related errors (previous bugs or complexity).
- Annotate code that is hard to understand.
- Annotate code as it becomes stable from a types' perspective. In many cases, you can annotate all the functions in mature code without losing too much flexibility.

- Annotating `self` or `cls` is generally not necessary. [`Self`](https://docs.python.org/3/library/typing.html#typing.Self) can be used if it is necessary for proper type information, e.g.

```python
from typing import Self

class BaseClass:
    @classmethod
    def create(cls) -> Self:
        ...
  
    def difference(self, other: Self) -> float:
        ...
```

- Similarly, don't feel compelled to annotate the return value of `__init__`
- If any other variable or a returned type should not be expressed, use `Any`.
- You are not required to annotate all the functions in a module.
- Do not annotate returning ` -> None`


### 19.2 Line Breaking

Try to follow the existing [indentation](#indentation) rules.

After annotating, many function signatures may become "one parameter per line". 
To ensure the return type is also given its own line, a comma can be placed after the last parameter.

```python
def my_method(
    self,
    first_var: int,
    second_var: Foo,
    third_var: Optional[Bar],
) -> int:
    ...
```

However, if everything fits on the same line, go for it.

```python
def my_method(self, first_var: int) -> int:
    ...
```

If the combination of the function name, the last parameter, and the return type is too long, indent by 4 in a new line.

When using line breaks, prefer putting each parameter and the return type on their own lines and aligning the closing parenthesis with the `def`:

Yes:

```python
def my_method(
    self,
    other_arg: Optional[MyLongType],
) -> tuple[MyLongType1, MyLongType1]:
    ...
```

Optionally, the return type may be put on the same line as the last
parameter:

Yes:

```python
def my_method(
    self,
    first_var: int,
    second_var: int) -> dict[OtherLongType, MyLongType]:
  ...
```

`pylint` allows you to move the closing parenthesis to a new line and align with the opening one, but this is less readable.

No:

```python
def my_method(self,
              other_arg: Optional[MyLongType],
             ) -> dict[OtherLongType, MyLongType]:
        ...
```

As in the examples above, prefer not to break types. 

However, in very rare cases they are too long to be on a single line. 

Anyway, keep subtypes unbroken.

No:

```python
def my_method(
    self,
    first_var: tuple[list[MyLongType1],
                     list[MyLongType2]],
    second_var: list[dict[
        MyLongType3, MyLongType4]],
):
        ...
```

If a single name and type is too long, consider using an [alias](#typing-aliases) for the type. The last resort is to break after the colon and indent by 4.

Yes:

```python
def my_function(
    long_variable_name:
        long_module_name.LongTypeName,
):
  ...
```

```python
T = long_module_name.LongTypeName
def my_function(
    long_variable_name: T,
):
  ...
```

No:

```python
def my_function(
    long_variable_name: long_module_name.
        LongTypeName,
):
  ...
```

### 19.3 Forward Declarations

If you need to use a class name (from the same module) that is not yet defined -- for example, if you need the class name inside the declaration of that class, or if you use a class that is defined later in the code -- either use `from __future__ import annotations` or use a string for the class name.

Yes:

```python
from __future__ import annotations

class MyClass:
    def __init__(self, stack: Sequence['MyClass'], item: 'OtherClass'):

class OtherClass:
    ...
```

```python
class MyClass:
    def __init__(self, stack: Sequence['MyClass'], item: 'OtherClass'):

class OtherClass:
    ...
```

<a id="typing-default-values"></a>
### 19.4 Default Values

As per PEP-008, use spaces around the `=` *only* for arguments that have both a type annotation and a default value.

Yes:

```python
def func(a: int = 0) -> int:
    ...
```

No:

```python
def func(a:int=0) -> int:
    ...
```

### 19.5 NoneType

In the Python type system, `NoneType` is a "first class" type, and for typing purposes,`None` is an alias for `NoneType`. If an argument can be `None`, it has to be declared!

Do not use `|` union type expressions, prefer `Optional[]` and `Union[]` syntaxes.

Use explicit `Optional[X]` instead of implicit. 

Yes:

```python
def union_optional(a: Union[str, int, None], b: Optional[str] = None) -> str:
    ...
```

No:

```python
def union_type(a: str | int | None, b: str | None = None) -> str:
    ...

def nullable_union(a: Union[None, str]) -> str:
    ...

def implicit_optional(a: str = None) -> str:
    ...
```

<a id="typing-aliases"></a>
### 19.6 Type Aliases

You can declare aliases of complex types. 
The name of an alias should be CapWorded. 

If the alias is used only in this module, it should be `_Private`

```python
from typing import TypeAlias

_LossAndGradient: TypeAlias = tuple[tf.Tensor, tf.Tensor]
ComplexTFMap: TypeAlias = Mapping[str, _LossAndGradient]
```

### 19.7 Ignoring Types

You can disable type checking on a line with the special comment
`# type: ignore`.

`pytype` has a disable option for specific errors (similar to lint):

```python
# pytype: disable=attribute-error
```

### 19.8 Typing Variables
<a id="annotated-assignments"></a>
[*Annotated Assignments*](#annotated-assignments)
If an internal variable has a type that is hard or impossible to infer, specify its type with an annotated assignment - use a colon and type between the variable name and value (the same as is done with function arguments that have a default value)

```python
a: Foo = SomeUndecoratedFunction()
```

<a id="type-comments"></a>
[*Type Comments*](#type-comments)
Do not uses any of `# type: <type name>` comment on the end of the line

```python
a = SomeUndecoratedFunction()  # type: Foo
```

### 19.9 Tuples vs. Lists

Typed lists can only contain objects of a single type. 

Typed tuples can either have a single repeated type or a set number of elements with different types. 

The latter is commonly used as the return type from a function.

```python
a: list[int] = [1, 2, 3]
b: tuple[int, ...] = (1, 2, 3)
c: tuple[int, str, float] = (1, "2", 3.5)
```

<a id="typing-type-var"></a>
### 19.10 Type variables

The Python type system permit to use [generics](https://docs.python.org/3/library/typing.html#generics).

A type variable, such as `TypeVar` and `ParamSpec`, is a common way to use them.

Example:

```python
from collections.abc import Callable
from typing import ParamSpec, TypeVar

_P = ParamSpec("_P")
_T = TypeVar("_T")
...


def next(l: list[_T]) -> _T:
    return l.pop()


def print_when_called(f: Callable[_P, _T]) -> Callable[_P, _T]:
    def inner(*args: _P.args, **kwargs: _P.kwargs) -> _T:
        print("Function was called")
        return f(*args, **kwargs)

    return inner
```

A `TypeVar` can be constrained:

```python
AddableType = TypeVar("AddableType", int, float, str)
def add(a: AddableType, b: AddableType) -> AddableType:
    return a + b
```

A commonly predefined type variable in the `typing` module is `AnyStr`. Use it for multiple annotations that can be
`bytes` or
`str` and must all be the same
type.

```python
from typing import AnyStr


def check_length(x: AnyStr) -> AnyStr:
    if len(x) <= 42:
        return x
    raise ValueError()
```

A type variable must have a descriptive name unless it meets all the following criteria:

- not externally visible
- not constrained

Yes:

```python
_T = TypeVar("_T")
_P = ParamSpec("_P")
AddableType = TypeVar("AddableType", int, float, str)
AnyFunction = TypeVar("AnyFunction", bound=Callable)
```

No:

```python
T = TypeVar("T")
P = ParamSpec("P")
_T = TypeVar("_T", int, float, str)
_F = TypeVar("_F", bound=Callable)
```

### 19.11 String types

Never use `typing.Text`. It's only for Python 2/3 compatibility.

Use `str` for string/text data.

For code that deals with binary data, use `bytes`.

```python
def deals_with_text_data(x: str) -> str:
    ...
def deals_with_binary_data(x: bytes) -> bytes:
    ...
```

<a id="typing-imports"></a>
### 19.12 Imports For Typing

For symbols (including types, functions, and constants) from the `typing` or `collections.abc` modules used to support static analysis and type checking, always import the symbol itself. 

This keeps common annotations more concise and matches typing practices used around the world. 

You are explicitly allowed to import multiple specific symbols on one line from the `typing` and `collections.abc` modules. 

For example:

```python
from collections.abc import Mapping, Sequence
from typing import Any, Generic, cast, TYPE_CHECKING
```

Given that this way of importing adds items to the local namespace, names in `typing` or `collections.abc` should be treated similarly to keywords, and not be defined in your Python code, typed or not. 

If there is a collision between a type and an existing name in a module, import it using `import x as y`.

```python
from typing import Any as AnyType
```

When annotating function signatures, prefer abstract container types like `collections.abc.Sequence` over concrete types like `list`.

If you need to use a concrete type (for example, a `tuple` of typed elements), prefer built-in types like `tuple` over the parametric type aliases from the `typing` module (e.g., `typing.Tuple`)

```python
from typing import List, Tuple

def transform_coordinates(original: list[tuple[float, float]]) -> list[tuple[float, float]]:
    ...
```

```python
from collections.abc import Sequence

def transform_coordinates(original: Sequence[tuple[float, float]]) -> Sequence[tuple[float, float]]:
    ...
```

### 19.13 Conditional Imports

Avoid conditional imports.

This pattern is discouraged; alternatives such as refactoring the code to allow top-level imports should be preferred.

Imports that are needed only for type annotations can be placed within an `if TYPE_CHECKING:` block.

### 19.14 Circular Dependencies

Circular dependencies that are caused by typing are code smells. 

Refactor the code to avoid circular dependencies by design.

In extreme cases, replace modules that create circular dependency imports with `Any`. 

Set an [alias](#typing-aliases) with a meaningful name, and use the real type name from this module (any attribute of `Any` is `Any`).

Alias definitions should be separated from the last import by one line.

```python
from typing import Any

some_mod = Any  # some_mod.py imports this module.
...


def my_method(self, var: "some_mod.SomeType"):
    ...
```

### 19.15 Generics

When annotating, prefer to specify type parameters for [generic](https://docs.python.org/3/library/typing.html#generics) types in a parameter list; otherwise, the generics' parameters will be assumed to be [`Any`](https://docs.python.org/3/library/typing.html#the-any-type).

Yes:

```python
def get_names(employee_ids: Sequence[int]) -> Mapping[int, str]:
    ...
```

No:

```python
# This is interpreted as get_names(employee_ids: Sequence[Any]) -> Mapping[Any, Any]
def get_names(employee_ids: Sequence) -> Mapping:
    ...
```

If the best type parameter for a generic is `Any`, make it explicit, but remember that in many cases [`TypeVar`](#typing-type-var) might be more appropriate:

No:

```python
def get_names(employee_ids: Sequence[Any]) -> Mapping[Any, str]:
    """Returns a mapping from employee ID to employee name for given IDs."""
```

Yes:

```python
_T = TypeVar('_T')

def get_names(employee_ids: Sequence[_T]) -> Mapping[_T, str]:
    """Returns a mapping from employee ID to employee name for given IDs."""
```

## 20. Be Consistent but Know When to Break Consistency

If you're editing an existing codebase, always look at the code around you and determine its style. If they use `_idx` suffixes in index variable names, you should too. If their comments have little boxes of hash marks around them, make your comments have little boxes of hash marks around them too.

The point of having style guidelines is to have a common vocabulary of coding so people can concentrate on what you're saying rather than on how you're saying it. We present global style rules here so people know the vocabulary, but local style is also important. If code you add to a file looks drastically different from the existing code around it, it throws readers out of their rhythm when they go to read it.

However, there are limits to consistency. It applies more heavily locally and on choices unspecified by the global style. Consistency should not generally be used as a justification to do things in an old style without considering the benefits of the new style, or the tendency of the codebase to converge on newer styles over time.
