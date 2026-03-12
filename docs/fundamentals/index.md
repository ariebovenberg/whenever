(fundamentals)=
# The fundamentals of time

Time isn't actually that hard once you understand the basic concepts.

The difficulty is that most people learn to work with time by learning an API first.
In Python, that usually means starting with the standard library’s {mod}`datetime` module
and figuring things out by trial and error, without ever forming a clear picture
of what time values are supposed to represent.

This is similar to how many people start using {class}`str` long before they understand
Unicode or text encodings.
You can write plenty of correct code without that knowledge,
and simple rules of thumb—like "just use UTF-8"—often work well enough.
But when something behaves unexpectedly,
it is hard to reason about the problem without understanding the underlying model.

Time works the same way.
Advice like "just use UTC" can take you surprisingly far,
and you may be able to rely on it for a long time.
But when edge cases appear, the only reliable way forward
is to understand the concepts those rules are trying to paper over.

You do not need to be a time expert to write correct code,
but you do need to understand a small number of fundamental ideas
and apply them consistently.

The pages that follow introduce those ideas,
starting with the most important distinction of all:
the difference between exact time and local time.

```{tip}
Once you're comfortable with the fundamentals,
head to the {ref}`guide <guide>` to see how `whenever` puts them into practice.
```

```{eval-rst}
.. toctree::
   :maxdepth: 1

   exact-vs-local
   timezones
   ambiguity
   arithmetic
```
