<!-- Source: https://doc.sagemath.org/html/en/reference/coercion/index.html -->

# Coercion[¶](#coercion "Link to this heading")

## Preliminaries[¶](#preliminaries "Link to this heading")

### What is coercion all about?[¶](#what-is-coercion-all-about "Link to this heading")

*The primary goal of coercion is to be able to transparently do arithmetic,
comparisons, etc. between elements of distinct sets.*

As a concrete example, when one writes \(1 + 1/2\) one wants to perform
arithmetic on the operands as rational numbers, despite the left being
an integer. This makes sense given the obvious and natural inclusion
of the integers into the rational numbers. The goal of the coercion
system is to facilitate this (and more complicated arithmetic) without
having to explicitly map everything over into the same domain, and at
the same time being strict enough to not resolve ambiguity or accept
nonsense. Here are some examples:

Sage

```
sage: 1 + 1/2
3/2
sage: R.<x,y> = ZZ[]
sage: R
Multivariate Polynomial Ring in x, y over Integer Ring
sage: parent(x)
Multivariate Polynomial Ring in x, y over Integer Ring
sage: parent(1/3)
Rational Field
sage: x+1/3
x + 1/3
sage: parent(x+1/3)
Multivariate Polynomial Ring in x, y over Rational Field

sage: GF(5)(1) + CC(I)
Traceback (most recent call last):
...
TypeError: unsupported operand parent(s) for +: 'Finite Field of size 5' and 'Complex Field with 53 bits of precision'
```

Python

```
>>> from sage.all import *
>>> Integer(1) + Integer(1)/Integer(2)
3/2
>>> R = ZZ['x, y']; (x, y,) = R._first_ngens(2)
>>> R
Multivariate Polynomial Ring in x, y over Integer Ring
>>> parent(x)
Multivariate Polynomial Ring in x, y over Integer Ring
>>> parent(Integer(1)/Integer(3))
Rational Field
>>> x+Integer(1)/Integer(3)
x + 1/3
>>> parent(x+Integer(1)/Integer(3))
Multivariate Polynomial Ring in x, y over Rational Field

>>> GF(Integer(5))(Integer(1)) + CC(I)
Traceback (most recent call last):
...
TypeError: unsupported operand parent(s) for +: 'Finite Field of size 5' and 'Complex Field with 53 bits of precision'
```

### Parents and Elements[¶](#parents-and-elements "Link to this heading")

Parents are objects in concrete categories, and Elements are their
members. Parents are first-class objects. Most things in Sage are
either parents or have a parent. Typically whenever one sees the word
*Parent* one can think *Set*. Here are some examples:

Sage

```
sage: parent(1)
Integer Ring
sage: parent(1) is ZZ
True
sage: ZZ
Integer Ring
sage: parent(1.50000000000000000000000000000000000)
Real Field with 120 bits of precision
sage: parent(x)
Symbolic Ring
sage: x^sin(x)
x^sin(x)
sage: R.<t> = Qp(5)[]
sage: f = t^3-5; f
(1 + O(5^20))*t^3 + 4*5 + 4*5^2 + 4*5^3 + 4*5^4 + 4*5^5 + 4*5^6 + 4*5^7 + 4*5^8 + 4*5^9 + 4*5^10 + 4*5^11 + 4*5^12 + 4*5^13 + 4*5^14 + 4*5^15 + 4*5^16 + 4*5^17 + 4*5^18 + 4*5^19 + 4*5^20 + O(5^21)
sage: parent(f)
Univariate Polynomial Ring in t over 5-adic Field with capped relative precision 20
sage: f = EllipticCurve('37a').lseries().taylor_series(10); f  # abs tol 1e-14
0.997997869801216 + 0.00140712894524925*z - 0.000498127610960097*z^2 + 0.000118835596665956*z^3 - 0.0000215906522442708*z^4 + (3.20363155418421e-6)*z^5 + O(z^6)  # 32-bit
0.997997869801216 + 0.00140712894524925*z - 0.000498127610960097*z^2 + 0.000118835596665956*z^3 - 0.0000215906522442708*z^4 + (3.20363155418427e-6)*z^5 + O(z^6)  # 64-bit
sage: parent(f)
Power Series Ring in z over Complex Field with 53 bits of precision
```

Python

```
>>> from sage.all import *
>>> parent(Integer(1))
Integer Ring
>>> parent(Integer(1)) is ZZ
True
>>> ZZ
Integer Ring
>>> parent(RealNumber('1.50000000000000000000000000000000000'))
Real Field with 120 bits of precision
>>> parent(x)
Symbolic Ring
>>> x**sin(x)
x^sin(x)
>>> R = Qp(Integer(5))['t']; (t,) = R._first_ngens(1)
>>> f = t**Integer(3)-Integer(5); f
(1 + O(5^20))*t^3 + 4*5 + 4*5^2 + 4*5^3 + 4*5^4 + 4*5^5 + 4*5^6 + 4*5^7 + 4*5^8 + 4*5^9 + 4*5^10 + 4*5^11 + 4*5^12 + 4*5^13 + 4*5^14 + 4*5^15 + 4*5^16 + 4*5^17 + 4*5^18 + 4*5^19 + 4*5^20 + O(5^21)
>>> parent(f)
Univariate Polynomial Ring in t over 5-adic Field with capped relative precision 20
>>> f = EllipticCurve('37a').lseries().taylor_series(Integer(10)); f  # abs tol 1e-14
0.997997869801216 + 0.00140712894524925*z - 0.000498127610960097*z^2 + 0.000118835596665956*z^3 - 0.0000215906522442708*z^4 + (3.20363155418421e-6)*z^5 + O(z^6)  # 32-bit
0.997997869801216 + 0.00140712894524925*z - 0.000498127610960097*z^2 + 0.000118835596665956*z^3 - 0.0000215906522442708*z^4 + (3.20363155418427e-6)*z^5 + O(z^6)  # 64-bit
>>> parent(f)
Power Series Ring in z over Complex Field with 53 bits of precision
```

There is an important distinction between Parents and types:

Sage

```
sage: a = GF(5).random_element()
sage: b = GF(7).random_element()
sage: type(a)
<class 'sage.rings.finite_rings.integer_mod.IntegerMod_int'>
sage: type(b)
<class 'sage.rings.finite_rings.integer_mod.IntegerMod_int'>
sage: type(a) == type(b)
True
sage: parent(a)
Finite Field of size 5
sage: parent(a) == parent(b)
False
```

Python

```
>>> from sage.all import *
>>> a = GF(Integer(5)).random_element()
>>> b = GF(Integer(7)).random_element()
>>> type(a)
<class 'sage.rings.finite_rings.integer_mod.IntegerMod_int'>
>>> type(b)
<class 'sage.rings.finite_rings.integer_mod.IntegerMod_int'>
>>> type(a) == type(b)
True
>>> parent(a)
Finite Field of size 5
>>> parent(a) == parent(b)
False
```

However, non-Sage objects do not really have parents, but we still want
to be able to reason with them, so their type is used instead:

Sage

```
sage: a = int(10)
sage: parent(a)
<... 'int'>
```

Python

```
>>> from sage.all import *
>>> a = int(Integer(10))
>>> parent(a)
<... 'int'>
```

In fact, under the hood, a special kind of parent “The set of all
Python objects of class T” is used in these cases.

Note that parents are **not** always as tight as possible.

Sage

```
sage: parent(1/2)
Rational Field
sage: parent(2/1)
Rational Field
```

Python

```
>>> from sage.all import *
>>> parent(Integer(1)/Integer(2))
Rational Field
>>> parent(Integer(2)/Integer(1))
Rational Field
```

### Maps between Parents[¶](#maps-between-parents "Link to this heading")

Many parents come with maps to and from other parents.

Sage makes a distinction between being able to **convert** between
various parents, and **coerce** between them. Conversion is explicit
and tries to make sense of an object in the target domain if at all
possible. It is invoked by calling:

Sage

```
sage: ZZ(5)
5
sage: ZZ(10/5)
2
sage: QQ(10)
10
sage: parent(QQ(10))
Rational Field
sage: a = GF(5)(2); a
2
sage: parent(a)
Finite Field of size 5
sage: parent(ZZ(a))
Integer Ring
sage: GF(71)(1/5)
57
sage: ZZ(1/2)
Traceback (most recent call last):
...
TypeError: no conversion of this rational to integer
```

Python

```
>>> from sage.all import *
>>> ZZ(Integer(5))
5
>>> ZZ(Integer(10)/Integer(5))
2
>>> QQ(Integer(10))
10
>>> parent(QQ(Integer(10)))
Rational Field
>>> a = GF(Integer(5))(Integer(2)); a
2
>>> parent(a)
Finite Field of size 5
>>> parent(ZZ(a))
Integer Ring
>>> GF(Integer(71))(Integer(1)/Integer(5))
57
>>> ZZ(Integer(1)/Integer(2))
Traceback (most recent call last):
...
TypeError: no conversion of this rational to integer
```

Conversions need not be canonical (they may for example involve a
choice of lift) or even make sense mathematically (e.g. constructions
of some kind).

Sage

```
sage: ZZ("123")
123
sage: ZZ(GF(5)(14))
4
sage: ZZ['x']([4,3,2,1])
x^3 + 2*x^2 + 3*x + 4
sage: a = Qp(5, 10)(1/3); a
2 + 3*5 + 5^2 + 3*5^3 + 5^4 + 3*5^5 + 5^6 + 3*5^7 + 5^8 + 3*5^9 + O(5^10)
sage: ZZ(a)
6510417
```

Python

```
>>> from sage.all import *
>>> ZZ("123")
123
>>> ZZ(GF(Integer(5))(Integer(14)))
4
>>> ZZ['x']([Integer(4),Integer(3),Integer(2),Integer(1)])
x^3 + 2*x^2 + 3*x + 4
>>> a = Qp(Integer(5), Integer(10))(Integer(1)/Integer(3)); a
2 + 3*5 + 5^2 + 3*5^3 + 5^4 + 3*5^5 + 5^6 + 3*5^7 + 5^8 + 3*5^9 + O(5^10)
>>> ZZ(a)
6510417
```

On the other hand, Sage has the notion of a **coercion**, which is a
canonical morphism (occasionally up to a conventional choice made by
developers) between parents. A coercion from one parent to another
**must** be defined on the whole domain, and always succeeds. As it
may be invoked implicitly, it should be obvious and natural (in both
the mathematically rigorous and colloquial sense of the word). Up to
inescapable rounding issues that arise with inexact representations,
these coercion morphisms should all commute. In particular, if there
are coercion maps \(A \to B\) and \(B \to A\), then their composites
must be the identity maps.

Coercions can be discovered via the [`Parent.has_coerce_map_from()`](../structure/sage/structure/parent.html#sage.structure.parent.Parent.has_coerce_map_from "(in Parents and Elements v10.6)")
method, and if needed explicitly invoked with the
[`Parent.coerce()`](../structure/sage/structure/parent.html#sage.structure.parent.Parent.coerce "(in Parents and Elements v10.6)") method:

Sage

```
sage: QQ.has_coerce_map_from(ZZ)
True
sage: QQ.has_coerce_map_from(RR)
False
sage: ZZ['x'].has_coerce_map_from(QQ)
False
sage: ZZ['x'].has_coerce_map_from(ZZ)
True
sage: ZZ['x'].coerce(5)
5
sage: ZZ['x'].coerce(5).parent()
Univariate Polynomial Ring in x over Integer Ring
sage: ZZ['x'].coerce(5/1)
Traceback (most recent call last):
...
TypeError: no canonical coercion from Rational Field to Univariate Polynomial Ring in x over Integer Ring
```

Python

```
>>> from sage.all import *
>>> QQ.has_coerce_map_from(ZZ)
True
>>> QQ.has_coerce_map_from(RR)
False
>>> ZZ['x'].has_coerce_map_from(QQ)
False
>>> ZZ['x'].has_coerce_map_from(ZZ)
True
>>> ZZ['x'].coerce(Integer(5))
5
>>> ZZ['x'].coerce(Integer(5)).parent()
Univariate Polynomial Ring in x over Integer Ring
>>> ZZ['x'].coerce(Integer(5)/Integer(1))
Traceback (most recent call last):
...
TypeError: no canonical coercion from Rational Field to Univariate Polynomial Ring in x over Integer Ring
```

## Basic Arithmetic Rules[¶](#basic-arithmetic-rules "Link to this heading")

Suppose we want to add two element, a and b, whose parents are A and B
respectively. When we type `a+b` then

1. If A `is` B, call a.\_add\_(b)
2. If there is a coercion \(\phi: B \rightarrow A\), call a.\_add\_( \(\phi\) (b))
3. If there is a coercion \(\phi: A \rightarrow B\), call \(\phi\) (a).\_add\_(b)
4. Look for \(Z\) such that there is a coercion \(\phi\_A: A \rightarrow Z\) and
   \(\phi\_B: B \rightarrow Z\), call \(\phi\_A\) (a).\_add\_( \(\phi\_B\) (b))

These rules are evaluated in order; therefore if there are coercions
in both directions, then the parent of a.\_add\_b is A – the parent
of the left-hand operand is used in such cases.

The same rules are used for subtraction, multiplication, and
division. This logic is embedded in a coercion model object, which can
be obtained and queried.

Sage

```
sage: parent(1 + 1/2)
Rational Field
sage: cm = coercion_model; cm
<sage.structure.coerce.CoercionModel object at ...>
sage: cm.explain(ZZ, QQ)
Coercion on left operand via
   Natural morphism:
     From: Integer Ring
     To:   Rational Field
Arithmetic performed after coercions.
Result lives in Rational Field
Rational Field

sage: cm.explain(ZZ['x','y'], QQ['x'])
Coercion on left operand via
   Coercion map:
     From: Multivariate Polynomial Ring in x, y over Integer Ring
     To:   Multivariate Polynomial Ring in x, y over Rational Field
Coercion on right operand via
   Coercion map:
     From: Univariate Polynomial Ring in x over Rational Field
     To:   Multivariate Polynomial Ring in x, y over Rational Field
Arithmetic performed after coercions.
Result lives in Multivariate Polynomial Ring in x, y over Rational Field
Multivariate Polynomial Ring in x, y over Rational Field
```

Python

```
>>> from sage.all import *
>>> parent(Integer(1) + Integer(1)/Integer(2))
Rational Field
>>> cm = coercion_model; cm
<sage.structure.coerce.CoercionModel object at ...>
>>> cm.explain(ZZ, QQ)
Coercion on left operand via
   Natural morphism:
     From: Integer Ring
     To:   Rational Field
Arithmetic performed after coercions.
Result lives in Rational Field
Rational Field

>>> cm.explain(ZZ['x','y'], QQ['x'])
Coercion on left operand via
   Coercion map:
     From: Multivariate Polynomial Ring in x, y over Integer Ring
     To:   Multivariate Polynomial Ring in x, y over Rational Field
Coercion on right operand via
   Coercion map:
     From: Univariate Polynomial Ring in x over Rational Field
     To:   Multivariate Polynomial Ring in x, y over Rational Field
Arithmetic performed after coercions.
Result lives in Multivariate Polynomial Ring in x, y over Rational Field
Multivariate Polynomial Ring in x, y over Rational Field
```

The coercion model can be used directly for any binary operation
(callable taking two arguments).

Sage

```
sage: cm.bin_op(77, 9, gcd)
1
```

Python

```
>>> from sage.all import *
>>> cm.bin_op(Integer(77), Integer(9), gcd)
1
```

There are also **actions** in the sense that a field \(K\) acts on a
module over \(K\), or a permutation group acts on a set. These are
discovered between steps 1 and 2 above.

Sage

```
sage: cm.explain(ZZ['x'], ZZ, operator.mul)
Action discovered.
   Right scalar multiplication by Integer Ring on Univariate Polynomial Ring in x over Integer Ring
Result lives in Univariate Polynomial Ring in x over Integer Ring
Univariate Polynomial Ring in x over Integer Ring

sage: cm.explain(ZZ['x'], ZZ, operator.truediv)
Action discovered.
   Right inverse action by Rational Field on Univariate Polynomial Ring in x over Integer Ring
   with precomposition on right by Natural morphism:
     From: Integer Ring
     To:   Rational Field
Result lives in Univariate Polynomial Ring in x over Rational Field
Univariate Polynomial Ring in x over Rational Field

sage: f = QQ.coerce_map_from(ZZ)
sage: f(3).parent()
Rational Field
```

Python

```
>>> from sage.all import *
>>> cm.explain(ZZ['x'], ZZ, operator.mul)
Action discovered.
   Right scalar multiplication by Integer Ring on Univariate Polynomial Ring in x over Integer Ring
Result lives in Univariate Polynomial Ring in x over Integer Ring
Univariate Polynomial Ring in x over Integer Ring

>>> cm.explain(ZZ['x'], ZZ, operator.truediv)
Action discovered.
   Right inverse action by Rational Field on Univariate Polynomial Ring in x over Integer Ring
   with precomposition on right by Natural morphism:
     From: Integer Ring
     To:   Rational Field
Result lives in Univariate Polynomial Ring in x over Rational Field
Univariate Polynomial Ring in x over Rational Field

>>> f = QQ.coerce_map_from(ZZ)
>>> f(Integer(3)).parent()
Rational Field
```

Note that by [Issue #14711](https://github.com/sagemath/sage/issues/14711) Sage’s coercion system uses maps with weak
references to the domain. Such maps should only be used internally, and so a
copy should be used instead (unless one knows what one is doing):

Sage

```
sage: QQ._internal_coerce_map_from(int)
(map internal to coercion system -- copy before use)
Native morphism:
  From: Set of Python objects of class 'int'
  To:   Rational Field
sage: copy(QQ._internal_coerce_map_from(int))
Native morphism:
  From: Set of Python objects of class 'int'
  To:   Rational Field
```

Python

```
>>> from sage.all import *
>>> QQ._internal_coerce_map_from(int)
(map internal to coercion system -- copy before use)
Native morphism:
  From: Set of Python objects of class 'int'
  To:   Rational Field
>>> copy(QQ._internal_coerce_map_from(int))
Native morphism:
  From: Set of Python objects of class 'int'
  To:   Rational Field
```

Note that the user-visible method (without underscore) automates this copy:

Sage

```
sage: copy(QQ.coerce_map_from(int))
Native morphism:
  From: Set of Python objects of class 'int'
  To:   Rational Field
```

Python

```
>>> from sage.all import *
>>> copy(QQ.coerce_map_from(int))
Native morphism:
  From: Set of Python objects of class 'int'
  To:   Rational Field
```

Sage

```
sage: QQ.has_coerce_map_from(RR)
False
sage: QQ['x'].get_action(QQ)
Right scalar multiplication by Rational Field on Univariate Polynomial Ring in x over Rational Field
sage: QQ2 = QQ^2
sage: (QQ2).get_action(QQ)
Right scalar multiplication by Rational Field on Vector space of dimension 2 over Rational Field
sage: QQ['x'].get_action(RR)
Right scalar multiplication by Real Field with 53 bits of precision on Univariate Polynomial Ring in x over Rational Field
```

Python

```
>>> from sage.all import *
>>> QQ.has_coerce_map_from(RR)
False
>>> QQ['x'].get_action(QQ)
Right scalar multiplication by Rational Field on Univariate Polynomial Ring in x over Rational Field
>>> QQ2 = QQ**Integer(2)
>>> (QQ2).get_action(QQ)
Right scalar multiplication by Rational Field on Vector space of dimension 2 over Rational Field
>>> QQ['x'].get_action(RR)
Right scalar multiplication by Real Field with 53 bits of precision on Univariate Polynomial Ring in x over Rational Field
```

## How to Implement[¶](#how-to-implement "Link to this heading")

### Methods to implement[¶](#methods-to-implement "Link to this heading")

* Arithmetic on Elements: `_add_`, `_sub_`, `_mul_`, `_div_`

  This is where the binary arithmetic operators should be
  implemented. Unlike Python’s `__add__`, both operands are
  *guaranteed* to have the same Parent at this point.
* Coercion for Parents: `_coerce_map_from_`

  Given two parents R and S, `R._coerce_map_from_(S)` is called to
  determine if there is a coercion \(\phi: S \rightarrow R\). Note that
  the function is called on the potential codomain. To indicate that
  there is no coercion from S to R (self), return `False` or
  `None`. This is the default behavior. If there is a coercion,
  return `True` (in which case a morphism using
  `R._element_constructor_` will be created) or an actual
  [`Morphism`](../categories/sage/categories/morphism.html#sage.categories.morphism.Morphism "(in Category Framework v10.6)") object with S as the domain and R as the codomain.
* Actions for Parents: `_get_action_` or `_rmul_`, `_lmul_`, `_act_on_`, `_acted_upon_`

  Suppose one wants R to act on S. Some examples of this could be
  \(R = \QQ\), \(S = \QQ[x]\) or \(R = {\rm Gal}(S/\QQ)\)
  where \(S\) is a number field. There are several ways to implement this:

  + If \(R\) is the base of \(S\) (as in the first example), simply
    implement `_rmul_` and/or `_lmul_` on the Elements of \(S\).
    In this case `r * s` gets handled as `s._rmul_(r)` and
    `s * r` as `s._lmul_(r)`. The argument to `_rmul_`
    and `_lmul_` are *guaranteed* to be Elements of the base of
    \(S\) (with coercion happening beforehand if necessary).
  + If \(R\) acts on \(S\), one can define the methods
    `_act_on_` on Elements of \(R\) or `_acted_upon_` on Elements of \(S\). In
    this case `r * s` gets handled as `r._act_on_(s, True)` or
    `s._acted_upon_(r, False)` and `s * r` as `r._act_on_(s, False)` or
    `s._acted_upon_(r, True)`. There is no constraint on the type or parents
    of objects passed to these methods; raise a [`TypeError`](https://docs.python.org/library/exceptions.html#TypeError "(in Python v3.12)") or [`ValueError`](https://docs.python.org/library/exceptions.html#ValueError "(in Python v3.12)")
    if the wrong kind of object is passed in to indicate the action is not
    appropriate here.
  + If either \(R\) acts on \(S\) *or* \(S\) acts on \(R\), one may implement
    `R._get_action_` to return an actual
    [`Action`](sage/categories/action.html#sage.categories.action.Action "sage.categories.action.Action") object to be used. This is how
    non-multiplicative actions must be implemented, and is the most powerful
    and complete way to do things.

  It should be noted that for the first way to work, elements of \(S\) are
  required to be ModuleElements. This requirement is likely to be lifted in the
  future.
* Element conversion/construction for Parents: use `_element_constructor_` **not** `__call__`

  The [`Parent.__call__()`](../structure/sage/structure/parent.html#sage.structure.parent.Parent.__call__ "(in Parents and Elements v10.6)") method dispatches to
  `_element_constructor_`. When someone writes `R(x, ...)`, this is
  the method that eventually gets called in most cases. See the
  documentation on the `__call__` method below.

Parents may also call the `self._populate_coercion_lists_` method in
their `__init__` functions to pass any callable for use instead of
`_element_constructor_`, provide a list of Parents with coercions to
self (as an alternative to implementing `_coerce_map_from_`),
provide special construction methods (like `_integer_` for ZZ),
etc. This also allows one to specify a single coercion embedding *out*
of self (whereas the rest of the coercion functions all specify maps
*into* self). There is extensive documentation in the docstring of the
`_populate_coercion_lists_` method.

### Example[¶](#example "Link to this heading")

Sometimes a simple example is worth a thousand words. Here is a
minimal example of setting up a simple Ring that handles coercion. (It
is easy to imagine much more sophisticated and powerful localizations,
but that would obscure the main points being made here.)

Sage

```
sage: from sage.structure.richcmp import richcmp
sage: from sage.structure.element import Element

sage: class MyLocalization(Parent):
....:     def __init__(self, primes):
....:         r"""
....:         Localization of `\ZZ` away from primes.
....:         """
....:         Parent.__init__(self, base=ZZ, category=Rings().Commutative())
....:         self._primes = primes
....:         self._populate_coercion_lists_()
....:
....:     def _repr_(self) -> str:
....:         """
....:         How to print ``self``.
....:         """
....:         return "%s localized at %s" % (self.base(), self._primes)
....:
....:     def _element_constructor_(self, x):
....:         """
....:         Make sure ``x`` is a valid member of ``self``, and return the constructed element.
....:         """
....:         if isinstance(x, MyLocalizationElement):
....:             x = x._value
....:         else:
....:             x = QQ(x)
....:         for p, e in x.denominator().factor():
....:             if p not in self._primes:
....:                 raise ValueError("not integral at %s" % p)
....:         return self.element_class(self, x)
....:
....:     def _an_element_(self):
....:         return self.element_class(self, 6)
....:
....:     def _coerce_map_from_(self, S):
....:         """
....:         The only things that coerce into this ring are:
....:
....:         - the integer ring
....:
....:         - other localizations away from fewer primes
....:         """
....:         if S is ZZ:
....:             return True
....:         if isinstance(S, MyLocalization):
....:             return all(p in self._primes for p in S._primes)

sage: class MyLocalizationElement(Element):
....:
....:     def __init__(self, parent, x):
....:         Element.__init__(self, parent)
....:         self._value = x
....:
....:     # We are just printing out this way to make it easy to see what's going on in the examples.
....:
....:     def _repr_(self) -> str:
....:         return f"LocalElt({self._value})"
....:
....:     # Now define addition, subtraction and multiplication of elements.
....:     # Note that self and right always have the same parent.
....:
....:     def _add_(self, right):
....:         return self.parent()(self._value + right._value)
....:
....:     def _sub_(self, right):
....:         return self.parent()(self._value - right._value)
....:
....:     def _mul_(self, right):
....:         return self.parent()(self._value * right._value)
....:
....:     # The basering was set to ZZ, so c is guaranteed to be in ZZ
....:
....:     def _rmul_(self, c):
....:         return self.parent()(c * self._value)
....:
....:     def _lmul_(self, c):
....:         return self.parent()(self._value * c)
....:
....:     def _richcmp_(self, other, op):
....:         return richcmp(self._value, other._value, op)

sage: MyLocalization.element_class = MyLocalizationElement
```

Python

```
>>> from sage.all import *
>>> from sage.structure.richcmp import richcmp
>>> from sage.structure.element import Element

>>> class MyLocalization(Parent):
...     def __init__(self, primes):
...         r"""
...         Localization of `\ZZ` away from primes.
...         """
...         Parent.__init__(self, base=ZZ, category=Rings().Commutative())
...         self._primes = primes
...         self._populate_coercion_lists_()
....:
>>>     def _repr_(self) -> str:
...         """
...         How to print ``self``.
...         """
...         return "%s localized at %s" % (self.base(), self._primes)
....:
>>>     def _element_constructor_(self, x):
...         """
...         Make sure ``x`` is a valid member of ``self``, and return the constructed element.
...         """
...         if isinstance(x, MyLocalizationElement):
...             x = x._value
...         else:
...             x = QQ(x)
...         for p, e in x.denominator().factor():
...             if p not in self._primes:
...                 raise ValueError("not integral at %s" % p)
...         return self.element_class(self, x)
....:
>>>     def _an_element_(self):
...         return self.element_class(self, Integer(6))
....:
>>>     def _coerce_map_from_(self, S):
...         """
...         The only things that coerce into this ring are:
....:
>>>         - the integer ring
....:
>>>         - other localizations away from fewer primes
...         """
...         if S is ZZ:
...             return True
...         if isinstance(S, MyLocalization):
...             return all(p in self._primes for p in S._primes)

>>> class MyLocalizationElement(Element):
....:
>>>     def __init__(self, parent, x):
...         Element.__init__(self, parent)
...         self._value = x
....:
>>>     # We are just printing out this way to make it easy to see what's going on in the examples.
....:
>>>     def _repr_(self) -> str:
...         return f"LocalElt({self._value})"
....:
>>>     # Now define addition, subtraction and multiplication of elements.
...     # Note that self and right always have the same parent.
....:
>>>     def _add_(self, right):
...         return self.parent()(self._value + right._value)
....:
>>>     def _sub_(self, right):
...         return self.parent()(self._value - right._value)
....:
>>>     def _mul_(self, right):
...         return self.parent()(self._value * right._value)
....:
>>>     # The basering was set to ZZ, so c is guaranteed to be in ZZ
....:
>>>     def _rmul_(self, c):
...         return self.parent()(c * self._value)
....:
>>>     def _lmul_(self, c):
...         return self.parent()(self._value * c)
....:
>>>     def _richcmp_(self, other, op):
...         return richcmp(self._value, other._value, op)

>>> MyLocalization.element_class = MyLocalizationElement
```

That’s all there is to it. Now we can test it out:

Sage

```
sage: TestSuite(R).run(skip="_test_pickling")
sage: R = MyLocalization([2]); R
Integer Ring localized at [2]
sage: R(1)
LocalElt(1)
sage: R(1/2)
LocalElt(1/2)
sage: R(1/3)
Traceback (most recent call last):
...
ValueError: not integral at 3

sage: R.coerce(1)
LocalElt(1)
sage: R.coerce(1/4)
Traceback (most recent call last):
...
TypeError: no canonical coercion from Rational Field to Integer Ring localized at [2]

sage: R(1/2) + R(3/4)
LocalElt(5/4)
sage: R(1/2) + 5
LocalElt(11/2)
sage: 5 + R(1/2)
LocalElt(11/2)
sage: R(1/2) + 1/7
Traceback (most recent call last):
...
TypeError: unsupported operand parent(s) for +: 'Integer Ring localized at [2]' and 'Rational Field'
sage: R(3/4) * 7
LocalElt(21/4)

sage: cm = sage.structure.element.get_coercion_model()
sage: cm.explain(R, ZZ, operator.add)
Coercion on right operand via
   Coercion map:
     From: Integer Ring
     To:   Integer Ring localized at [2]
Arithmetic performed after coercions.
Result lives in Integer Ring localized at [2]
Integer Ring localized at [2]

sage: cm.explain(R, ZZ, operator.mul)
Coercion on right operand via
    Coercion map:
      From: Integer Ring
      To:   Integer Ring localized at [2]
Arithmetic performed after coercions.
Result lives in Integer Ring localized at [2]
Integer Ring localized at [2]

sage: R6 = MyLocalization([2,3]); R6
Integer Ring localized at [2, 3]
sage: R6(1/3) - R(1/2)
LocalElt(-1/6)
sage: parent(R6(1/3) - R(1/2))
Integer Ring localized at [2, 3]

sage: R.has_coerce_map_from(ZZ)
True
sage: R.coerce_map_from(ZZ)
Coercion map:
 From: Integer Ring
 To:   Integer Ring localized at [2]

sage: R6.coerce_map_from(R)
Coercion map:
 From: Integer Ring localized at [2]
 To:   Integer Ring localized at [2, 3]

sage: R6.coerce(R(1/2))
LocalElt(1/2)

sage: cm.explain(R, R6, operator.mul)
Coercion on left operand via
   Coercion map:
     From: Integer Ring localized at [2]
     To:   Integer Ring localized at [2, 3]
Arithmetic performed after coercions.
Result lives in Integer Ring localized at [2, 3]
Integer Ring localized at [2, 3]
```

Python

```
>>> from sage.all import *
>>> TestSuite(R).run(skip="_test_pickling")
>>> R = MyLocalization([Integer(2)]); R
Integer Ring localized at [2]
>>> R(Integer(1))
LocalElt(1)
>>> R(Integer(1)/Integer(2))
LocalElt(1/2)
>>> R(Integer(1)/Integer(3))
Traceback (most recent call last):
...
ValueError: not integral at 3

>>> R.coerce(Integer(1))
LocalElt(1)
>>> R.coerce(Integer(1)/Integer(4))
Traceback (most recent call last):
...
TypeError: no canonical coercion from Rational Field to Integer Ring localized at [2]

>>> R(Integer(1)/Integer(2)) + R(Integer(3)/Integer(4))
LocalElt(5/4)
>>> R(Integer(1)/Integer(2)) + Integer(5)
LocalElt(11/2)
>>> Integer(5) + R(Integer(1)/Integer(2))
LocalElt(11/2)
>>> R(Integer(1)/Integer(2)) + Integer(1)/Integer(7)
Traceback (most recent call last):
...
TypeError: unsupported operand parent(s) for +: 'Integer Ring localized at [2]' and 'Rational Field'
>>> R(Integer(3)/Integer(4)) * Integer(7)
LocalElt(21/4)

>>> cm = sage.structure.element.get_coercion_model()
>>> cm.explain(R, ZZ, operator.add)
Coercion on right operand via
   Coercion map:
     From: Integer Ring
     To:   Integer Ring localized at [2]
Arithmetic performed after coercions.
Result lives in Integer Ring localized at [2]
Integer Ring localized at [2]

>>> cm.explain(R, ZZ, operator.mul)
Coercion on right operand via
    Coercion map:
      From: Integer Ring
      To:   Integer Ring localized at [2]
Arithmetic performed after coercions.
Result lives in Integer Ring localized at [2]
Integer Ring localized at [2]

>>> R6 = MyLocalization([Integer(2),Integer(3)]); R6
Integer Ring localized at [2, 3]
>>> R6(Integer(1)/Integer(3)) - R(Integer(1)/Integer(2))
LocalElt(-1/6)
>>> parent(R6(Integer(1)/Integer(3)) - R(Integer(1)/Integer(2)))
Integer Ring localized at [2, 3]

>>> R.has_coerce_map_from(ZZ)
True
>>> R.coerce_map_from(ZZ)
Coercion map:
 From: Integer Ring
 To:   Integer Ring localized at [2]

>>> R6.coerce_map_from(R)
Coercion map:
 From: Integer Ring localized at [2]
 To:   Integer Ring localized at [2, 3]

>>> R6.coerce(R(Integer(1)/Integer(2)))
LocalElt(1/2)

>>> cm.explain(R, R6, operator.mul)
Coercion on left operand via
   Coercion map:
     From: Integer Ring localized at [2]
     To:   Integer Ring localized at [2, 3]
Arithmetic performed after coercions.
Result lives in Integer Ring localized at [2, 3]
Integer Ring localized at [2, 3]
```

### Provided Methods[¶](#provided-methods "Link to this heading")

* `__call__`

  This provides a consistent interface for element construction. In
  particular, it makes sure that conversion always gives the same
  result as coercion, if a coercion exists. (This used to be violated
  for some Rings in Sage as the code for conversion and coercion got
  edited separately.) Let R be a Parent and assume the user types
  R(x), where x has parent X. Roughly speaking, the following occurs:

  1. If X `is` R, return x (\*)
  2. If there is a coercion \(f: X \rightarrow R\), return \(f(x)\)
  3. If there is a coercion \(f: R \rightarrow X\), try to return \({f^{-1}}(x)\)
  4. Return `R._element_constructor_(x)` (\*\*)

  Keywords and extra arguments are passed on. The result of all this logic is cached.

  (\*) Unless there is a “copy” keyword like R(x, copy=False)

  (\*\*) Technically, a generic morphism is created from X to R, which
  may use magic methods like `_integer_` or other data provided by
  `_populate_coercion_lists_`.
* `coerce`

  Coerces elements into self, raising a type error if there is no
  coercion map.
* `coerce_map_from, convert_map_from`

  Returns an actual `Morphism` object to coerce/convert from
  another Parent to self. Barring direct construction of elements of
  R, `R.convert_map_from(S)` will provide a callable Python object
  which is the fastest way to convert elements of S to elements of
  R. From Cython, it can be invoked via the cdef `_call_` method.
* `has_coerce_map_from`

  Returns `True` or `False` depending on whether or not there is
  a coercion. `R.has_coerce_map_from(S)` is shorthand for
  `R.coerce_map_from(S) is not None`
* `get_action`

  This will unwind all the `_get_action_, _rmul_, _lmul_, _act_on_, _acted_upon_, ...`
  methods to provide an actual `Action` object, if one exists.

## Discovering new parents[¶](#discovering-new-parents "Link to this heading")

New parents are discovered using an algorithm in
sage/category/pushout.py. The fundamental idea is that most Parents
in Sage are constructed from simpler objects via various functors.
These are accessed via the `construction()` method, which returns a
(simpler) Parent along with a functor with which one can create self.

Sage

```
sage: CC.construction()
(AlgebraicClosureFunctor, Real Field with 53 bits of precision)
sage: RR.construction()
(Completion[+Infinity, prec=53], Rational Field)
sage: QQ.construction()
(FractionField, Integer Ring)
sage: ZZ.construction()  # None

sage: Zp(5).construction()
(Completion[5, prec=20], Integer Ring)
sage: QQ.completion(5, 100, {})
5-adic Field with capped relative precision 100
sage: c, R = RR.construction()
sage: a = CC.construction()[0]
sage: a.commutes(c)
False
sage: RR == c(QQ)
True

sage: sage.categories.pushout.construction_tower(Frac(CDF['x']))
[(None,
  Fraction Field of Univariate Polynomial Ring in x over Complex Double Field),
 (FractionField, Univariate Polynomial Ring in x over Complex Double Field),
 (Poly[x], Complex Double Field),
 (AlgebraicClosureFunctor, Real Double Field),
 (Completion[+Infinity, prec=53], Rational Field),
 (FractionField, Integer Ring)]
```

Python

```
>>> from sage.all import *
>>> CC.construction()
(AlgebraicClosureFunctor, Real Field with 53 bits of precision)
>>> RR.construction()
(Completion[+Infinity, prec=53], Rational Field)
>>> QQ.construction()
(FractionField, Integer Ring)
>>> ZZ.construction()  # None

>>> Zp(Integer(5)).construction()
(Completion[5, prec=20], Integer Ring)
>>> QQ.completion(Integer(5), Integer(100), {})
5-adic Field with capped relative precision 100
>>> c, R = RR.construction()
>>> a = CC.construction()[Integer(0)]
>>> a.commutes(c)
False
>>> RR == c(QQ)
True

>>> sage.categories.pushout.construction_tower(Frac(CDF['x']))
[(None,
  Fraction Field of Univariate Polynomial Ring in x over Complex Double Field),
 (FractionField, Univariate Polynomial Ring in x over Complex Double Field),
 (Poly[x], Complex Double Field),
 (AlgebraicClosureFunctor, Real Double Field),
 (Completion[+Infinity, prec=53], Rational Field),
 (FractionField, Integer Ring)]
```

Given Parents R and S, such that there is no coercion either from R to
S or from S to R, one can find a common Z with coercions
\(R \rightarrow Z\) and \(S \rightarrow Z\) by considering the sequence of
construction functors to get from a common ancestor to both R and S.
We then use a *heuristic* algorithm to interleave these constructors
in an attempt to arrive at a suitable Z (if one exists). For example:

Sage

```
sage: ZZ['x'].construction()
(Poly[x], Integer Ring)
sage: QQ.construction()
(FractionField, Integer Ring)
sage: sage.categories.pushout.pushout(ZZ['x'], QQ)
Univariate Polynomial Ring in x over Rational Field
sage: sage.categories.pushout.pushout(ZZ['x'], QQ).construction()
(Poly[x], Rational Field)
```

Python

```
>>> from sage.all import *
>>> ZZ['x'].construction()
(Poly[x], Integer Ring)
>>> QQ.construction()
(FractionField, Integer Ring)
>>> sage.categories.pushout.pushout(ZZ['x'], QQ)
Univariate Polynomial Ring in x over Rational Field
>>> sage.categories.pushout.pushout(ZZ['x'], QQ).construction()
(Poly[x], Rational Field)
```

The common ancestor is \(Z\) and our options for Z are
\(\mathrm{Frac}(\ZZ[x])\) or \(\mathrm{Frac}(\ZZ)[x]\).
In Sage we choose the later, treating the fraction
field functor as binding “more tightly” than the polynomial functor,
as most people agree that \(\QQ[x]\) is the more natural choice. The same
procedure is applied to more complicated Parents, returning a new
Parent if one can be unambiguously determined.

Sage

```
sage: sage.categories.pushout.pushout(Frac(ZZ['x,y,z']), QQ['z, t'])
Univariate Polynomial Ring in t over Fraction Field of Multivariate Polynomial Ring in x, y, z over Rational Field
```

Python

```
>>> from sage.all import *
>>> sage.categories.pushout.pushout(Frac(ZZ['x,y,z']), QQ['z, t'])
Univariate Polynomial Ring in t over Fraction Field of Multivariate Polynomial Ring in x, y, z over Rational Field
```

## Modules[¶](#modules "Link to this heading")

* [The coercion model](sage/structure/coerce.html)
* [Coerce actions](sage/structure/coerce_actions.html)
* [Coerce maps](sage/structure/coerce_maps.html)
* [Coercion via construction functors](sage/categories/pushout.html)
* [Group, ring, etc. actions on objects](sage/categories/action.html)
* [Containers for storing coercion data](sage/structure/coerce_dict.html)
* [Exceptions raised by the coercion model](sage/structure/coerce_exceptions.html)

# Indices and Tables[¶](#indices-and-tables "Link to this heading")

* [Index](../genindex.html)
* [Module Index](../py-modindex.html)
* [Search Page](../search.html)
