<!-- Source: https://doc.sagemath.org/html/en/reference/valuations/index.html -->

# Discrete Valuations and Discrete Pseudo-Valuations[¶](#discrete-valuations-and-discrete-pseudo-valuations "Link to this heading")

## High-Level Interface[¶](#high-level-interface "Link to this heading")

Valuations can be defined conveniently on some Sage rings such as p-adic rings
and function fields.

### p-adic valuations[¶](#p-adic-valuations "Link to this heading")

Valuations on number fields can be easily specified if they uniquely extend
the valuation of a rational prime:

Sage

```
sage: v = QQ.valuation(2)
sage: v(1024)
10
```

Python

```
>>> from sage.all import *
>>> v = QQ.valuation(Integer(2))
>>> v(Integer(1024))
10
```

They are normalized such that the rational prime has valuation 1:

Sage

```
sage: K.<a> = NumberField(x^2 + x + 1)
sage: v = K.valuation(2)
sage: v(1024)
10
```

Python

```
>>> from sage.all import *
>>> K = NumberField(x**Integer(2) + x + Integer(1), names=('a',)); (a,) = K._first_ngens(1)
>>> v = K.valuation(Integer(2))
>>> v(Integer(1024))
10
```

If there are multiple valuations over a prime, they can be obtained by
extending a valuation from a smaller ring:

Sage

```
sage: K.<a> = NumberField(x^2 + x + 1)
sage: K.valuation(7)
Traceback (most recent call last):
...
ValueError: The valuation Gauss valuation induced by 7-adic valuation does not approximate a unique extension of 7-adic valuation with respect to x^2 + x + 1
sage: w,ww = QQ.valuation(7).extensions(K)
sage: w(a + 3), ww(a + 3)
(1, 0)
sage: w(a + 5), ww(a + 5)
(0, 1)
```

Python

```
>>> from sage.all import *
>>> K = NumberField(x**Integer(2) + x + Integer(1), names=('a',)); (a,) = K._first_ngens(1)
>>> K.valuation(Integer(7))
Traceback (most recent call last):
...
ValueError: The valuation Gauss valuation induced by 7-adic valuation does not approximate a unique extension of 7-adic valuation with respect to x^2 + x + 1
>>> w,ww = QQ.valuation(Integer(7)).extensions(K)
>>> w(a + Integer(3)), ww(a + Integer(3))
(1, 0)
>>> w(a + Integer(5)), ww(a + Integer(5))
(0, 1)
```

### Valuations on Function Fields[¶](#valuations-on-function-fields "Link to this heading")

Similarly, valuations can be defined on function fields:

Sage

```
sage: K.<x> = FunctionField(QQ)
sage: v = K.valuation(x)
sage: v(1/x)
-1

sage: v = K.valuation(1/x)
sage: v(1/x)
1
```

Python

```
>>> from sage.all import *
>>> K = FunctionField(QQ, names=('x',)); (x,) = K._first_ngens(1)
>>> v = K.valuation(x)
>>> v(Integer(1)/x)
-1

>>> v = K.valuation(Integer(1)/x)
>>> v(Integer(1)/x)
1
```

On extensions of function fields, valuations can be created by providing a
prime on the underlying rational function field when the extension is unique:

Sage

```
sage: K.<x> = FunctionField(QQ)
sage: R.<y> = K[]
sage: L.<y> = K.extension(y^2 - x)
sage: v = L.valuation(x)
sage: v(x)
1
```

Python

```
>>> from sage.all import *
>>> K = FunctionField(QQ, names=('x',)); (x,) = K._first_ngens(1)
>>> R = K['y']; (y,) = R._first_ngens(1)
>>> L = K.extension(y**Integer(2) - x, names=('y',)); (y,) = L._first_ngens(1)
>>> v = L.valuation(x)
>>> v(x)
1
```

Valuations can also be extended from smaller function fields:

Sage

```
sage: K.<x> = FunctionField(QQ)
sage: v = K.valuation(x - 4)
sage: R.<y> = K[]
sage: L.<y> = K.extension(y^2 - x)
sage: v.extensions(L)
[[ (x - 4)-adic valuation, v(y + 2) = 1 ]-adic valuation,
 [ (x - 4)-adic valuation, v(y - 2) = 1 ]-adic valuation]
```

Python

```
>>> from sage.all import *
>>> K = FunctionField(QQ, names=('x',)); (x,) = K._first_ngens(1)
>>> v = K.valuation(x - Integer(4))
>>> R = K['y']; (y,) = R._first_ngens(1)
>>> L = K.extension(y**Integer(2) - x, names=('y',)); (y,) = L._first_ngens(1)
>>> v.extensions(L)
[[ (x - 4)-adic valuation, v(y + 2) = 1 ]-adic valuation,
 [ (x - 4)-adic valuation, v(y - 2) = 1 ]-adic valuation]
```

## Low-Level Interface[¶](#low-level-interface "Link to this heading")

### Mac Lane valuations[¶](#mac-lane-valuations "Link to this heading")

Internally, all the above is backed by the algorithms described in
[[Mac1936I]](../references/index.html#mac1936i) and [[Mac1936II]](../references/index.html#mac1936ii). Let us consider the extensions of
`K.valuation(x - 4)` to the field \(L\) above to outline how this works
internally.

First, the valuation on \(K\) is induced by a valuation on \(\QQ[x]\). To construct
this valuation, we start from the trivial valuation on \(\\Q\) and consider its
induced Gauss valuation on \(\\Q[x]\), i.e., the valuation that assigns to a
polynomial the minimum of the coefficient valuations:

Sage

```
sage: R.<x> = QQ[]
sage: v = GaussValuation(R, valuations.TrivialValuation(QQ))
```

Python

```
>>> from sage.all import *
>>> R = QQ['x']; (x,) = R._first_ngens(1)
>>> v = GaussValuation(R, valuations.TrivialValuation(QQ))
```

The Gauss valuation can be augmented by specifying that \(x - 4\) has valuation 1:

Sage

```
sage: v = v.augmentation(x - 4, 1); v
[ Gauss valuation induced by Trivial valuation on Rational Field, v(x - 4) = 1 ]
```

Python

```
>>> from sage.all import *
>>> v = v.augmentation(x - Integer(4), Integer(1)); v
[ Gauss valuation induced by Trivial valuation on Rational Field, v(x - 4) = 1 ]
```

This valuation then extends uniquely to the fraction field:

Sage

```
sage: K.<x> = FunctionField(QQ)
sage: v = v.extension(K); v
(x - 4)-adic valuation
```

Python

```
>>> from sage.all import *
>>> K = FunctionField(QQ, names=('x',)); (x,) = K._first_ngens(1)
>>> v = v.extension(K); v
(x - 4)-adic valuation
```

Over the function field we repeat the above process, i.e., we define the Gauss
valuation induced by it and augment it to approximate an extension to \(L\):

Sage

```
sage: R.<y> = K[]
sage: w = GaussValuation(R, v)
sage: w = w.augmentation(y - 2, 1); w
[ Gauss valuation induced by (x - 4)-adic valuation, v(y - 2) = 1 ]
sage: L.<y> = K.extension(y^2 - x)
sage: ww = w.extension(L); ww
[ (x - 4)-adic valuation, v(y - 2) = 1 ]-adic valuation
```

Python

```
>>> from sage.all import *
>>> R = K['y']; (y,) = R._first_ngens(1)
>>> w = GaussValuation(R, v)
>>> w = w.augmentation(y - Integer(2), Integer(1)); w
[ Gauss valuation induced by (x - 4)-adic valuation, v(y - 2) = 1 ]
>>> L = K.extension(y**Integer(2) - x, names=('y',)); (y,) = L._first_ngens(1)
>>> ww = w.extension(L); ww
[ (x - 4)-adic valuation, v(y - 2) = 1 ]-adic valuation
```

### Limit valuations[¶](#limit-valuations "Link to this heading")

In the previous example the final valuation `ww` is not merely given by
evaluating `w` on the ring \(K[y]\):

Sage

```
sage: ww(y^2 - x)
+Infinity
sage: y = R.gen()
sage: w(y^2 - x)
1
```

Python

```
>>> from sage.all import *
>>> ww(y**Integer(2) - x)
+Infinity
>>> y = R.gen()
>>> w(y**Integer(2) - x)
1
```

Instead `ww` is given by a limit, i.e., an infinite sequence of
augmentations of valuations:

Sage

```
sage: ww._base_valuation
[ Gauss valuation induced by (x - 4)-adic valuation, v(y - 2) = 1 , … ]
```

Python

```
>>> from sage.all import *
>>> ww._base_valuation
[ Gauss valuation induced by (x - 4)-adic valuation, v(y - 2) = 1 , … ]
```

The terms of this infinite sequence are computed on demand:

Sage

```
sage: ww._base_valuation._approximation
[ Gauss valuation induced by (x - 4)-adic valuation, v(y - 2) = 1 ]
sage: ww(y - 1/4*x - 1)
2
sage: ww._base_valuation._approximation
[ Gauss valuation induced by (x - 4)-adic valuation, v(y + 1/64*x^2 - 3/8*x - 3/4) = 3 ]
```

Python

```
>>> from sage.all import *
>>> ww._base_valuation._approximation
[ Gauss valuation induced by (x - 4)-adic valuation, v(y - 2) = 1 ]
>>> ww(y - Integer(1)/Integer(4)*x - Integer(1))
2
>>> ww._base_valuation._approximation
[ Gauss valuation induced by (x - 4)-adic valuation, v(y + 1/64*x^2 - 3/8*x - 3/4) = 3 ]
```

### Non-classical valuations[¶](#non-classical-valuations "Link to this heading")

Using the low-level interface we are not limited to classical valuations on
function fields that correspond to points on the corresponding projective
curves. Instead we can start with a non-trivial valuation on the field of
constants:

Sage

```
sage: v = QQ.valuation(2)
sage: R.<x> = QQ[]
sage: w = GaussValuation(R, v) # v is not trivial
sage: K.<x> = FunctionField(QQ)
sage: w = w.extension(K)
sage: w.residue_field()
Rational function field in x over Finite Field of size 2
```

Python

```
>>> from sage.all import *
>>> v = QQ.valuation(Integer(2))
>>> R = QQ['x']; (x,) = R._first_ngens(1)
>>> w = GaussValuation(R, v) # v is not trivial
>>> K = FunctionField(QQ, names=('x',)); (x,) = K._first_ngens(1)
>>> w = w.extension(K)
>>> w.residue_field()
Rational function field in x over Finite Field of size 2
```

## Mac Lane Approximants[¶](#mac-lane-approximants "Link to this heading")

The main tool underlying this package is an algorithm by Mac Lane to compute,
starting from a Gauss valuation on a polynomial ring and a monic squarefree
polynomial G, approximations to the limit valuation which send G to infinity:

Sage

```
sage: v = QQ.valuation(2)
sage: R.<x> = QQ[]
sage: f = x^5 + 3*x^4 + 5*x^3 + 8*x^2 + 6*x + 12
sage: v.mac_lane_approximants(f) # random output (order may vary)
[[ Gauss valuation induced by 2-adic valuation, v(x^2 + x + 1) = 3 ],
 [ Gauss valuation induced by 2-adic valuation, v(x) = 1/2 ],
 [ Gauss valuation induced by 2-adic valuation, v(x) = 1 ]]
```

Python

```
>>> from sage.all import *
>>> v = QQ.valuation(Integer(2))
>>> R = QQ['x']; (x,) = R._first_ngens(1)
>>> f = x**Integer(5) + Integer(3)*x**Integer(4) + Integer(5)*x**Integer(3) + Integer(8)*x**Integer(2) + Integer(6)*x + Integer(12)
>>> v.mac_lane_approximants(f) # random output (order may vary)
[[ Gauss valuation induced by 2-adic valuation, v(x^2 + x + 1) = 3 ],
 [ Gauss valuation induced by 2-adic valuation, v(x) = 1/2 ],
 [ Gauss valuation induced by 2-adic valuation, v(x) = 1 ]]
```

From these approximants one can already see the residual degrees and
ramification indices of the corresponding extensions. The approximants can be
pushed to arbitrary precision, corresponding to a factorization of `f`:

Sage

```
sage: v.mac_lane_approximants(f, required_precision=10) # random output
[[ Gauss valuation induced by 2-adic valuation, v(x^2 + 193*x + 13/21) = 10 ],
 [ Gauss valuation induced by 2-adic valuation, v(x + 86) = 10 ],
 [ Gauss valuation induced by 2-adic valuation, v(x) = 1/2, v(x^2 + 36/11*x + 2/17) = 11 ]]
```

Python

```
>>> from sage.all import *
>>> v.mac_lane_approximants(f, required_precision=Integer(10)) # random output
[[ Gauss valuation induced by 2-adic valuation, v(x^2 + 193*x + 13/21) = 10 ],
 [ Gauss valuation induced by 2-adic valuation, v(x + 86) = 10 ],
 [ Gauss valuation induced by 2-adic valuation, v(x) = 1/2, v(x^2 + 36/11*x + 2/17) = 11 ]]
```

## References[¶](#references "Link to this heading")

The theory was originally described in [[Mac1936I]](../references/index.html#mac1936i) and [[Mac1936II]](../references/index.html#mac1936ii). A summary and some algorithmic details can also be found in Chapter 4 of [[Rüt2014]](../references/index.html#rut2014).

# More Details[¶](#more-details "Link to this heading")

* [Value groups of discrete valuations](sage/rings/valuation/value_group.html)
* [Discrete valuations](sage/rings/valuation/valuation.html)
* [Spaces of valuations](sage/rings/valuation/valuation_space.html)
* [Trivial valuations](sage/rings/valuation/trivial_valuation.html)
* [Gauss valuations on polynomial rings](sage/rings/valuation/gauss_valuation.html)
* [Valuations on polynomial rings based on \(\phi\)-adic expansions](sage/rings/valuation/developing_valuation.html)
* [Inductive valuations on polynomial rings](sage/rings/valuation/inductive_valuation.html)
* [Augmented valuations on polynomial rings](sage/rings/valuation/augmented_valuation.html)
* [Valuations which are defined as limits of valuations.](sage/rings/valuation/limit_valuation.html)
* [Valuations which are implemented through a map to another valuation](sage/rings/valuation/mapped_valuation.html)
* [Valuations which are scaled versions of another valuation](sage/rings/valuation/scaled_valuation.html)
* [Discrete valuations on function fields](sage/rings/function_field/valuation.html)
* [\(p\)-adic Valuations on Number Fields and Their Subrings and Completions](sage/rings/padics/padic_valuation.html)

# Indices and Tables[¶](#indices-and-tables "Link to this heading")

* [Index](../genindex.html)
* [Module Index](../py-modindex.html)
* [Search Page](../search.html)
