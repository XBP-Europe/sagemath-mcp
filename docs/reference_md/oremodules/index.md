<!-- Source: https://doc.sagemath.org/html/en/reference/oremodules/index.html -->

# Modules over Ore rings[¶](#modules-over-ore-rings "Link to this heading")

Let \(R\) be a commutative ring, \(\theta : K \to K\) by a ring
endomorphism and \(\partial : K \to K\) be a \(\theta\)-derivation,
that is an additive map satisfying the following axiom

\[\partial(x y) = \theta(x) \partial(y) + \partial(x) y\]

The Ore polynomial ring associated to these data is
\(\mathcal S = R[X; \theta, \partial]\); its elements are the
usual polynomials over \(R\) but the multiplication is twisted
according to the rule

\[\partial(x y) = \theta(x) \partial(y) + \partial(x) y\]

We refer to `sage.rings.polynomial.ore_polynomial_ring.OrePolynomial`
for more details.

A Ore module over \((R, \theta, \partial)\) is by definition a
module over \(\mathcal S\); it is the same than a \(R\)-module \(M\)
equipped with an additive \(f : M \to M\) such that

\[f(a x) = \theta(a) f(x) + \partial(a) x\]

Such a map \(f\) is called a pseudomorphism
(see also [`sage.modules.free_module.FreeModule_generic.pseudohom()`](../modules/sage/modules/free_module.html#sage.modules.free_module.FreeModule_generic.pseudohom "(in Modules v10.6)")).

SageMath provides support for creating and manipulating Ore
modules that are finite free over the base ring \(R\).
This includes, in particular, Frobenius modules and modules
with connexions.

## Modules, submodules and quotients[¶](#modules-submodules-and-quotients "Link to this heading")

* [Ore modules](sage/modules/ore_module.html)
* [Elements in Ore modules](sage/modules/ore_module_element.html)

## Morphisms[¶](#morphisms "Link to this heading")

* [Space of morphisms between Ore modules](sage/modules/ore_module_homspace.html)
* [Morphisms between Ore modules](sage/modules/ore_module_morphism.html)
