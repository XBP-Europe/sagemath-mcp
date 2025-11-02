<!-- Source: https://doc.sagemath.org/html/en/reference/sat/index.html -->

# Sat[¶](#sat "Link to this heading")

Sage supports solving clauses in Conjunctive Normal Form (see [Wikipedia article Conjunctive\_normal\_form](https://en.wikipedia.org/wiki/Conjunctive_normal_form)),
i.e., SAT solving, via an interface inspired by the usual DIMACS format used in SAT solving
[[SG09]](#sg09). For example, to express that:

```
x1 OR x2 OR (NOT x3)
```

should be true, we write:

```
(1, 2, -3)
```

Warning

Variable indices **must** start at one.

## Solvers[¶](#solvers "Link to this heading")

By default, Sage solves SAT instances as an Integer Linear Program (see
[`sage.numerical.mip`](../numerical/sage/numerical/mip.html#module-sage.numerical.mip "(in Reference Manual v10.6)")), but any SAT solver supporting the DIMACS input
format is easily interfaced using the [`sage.sat.solvers.dimacs.DIMACS`](sage/sat/solvers/dimacs.html#sage.sat.solvers.dimacs.DIMACS "sage.sat.solvers.dimacs.DIMACS")
blueprint. Sage ships with pre-written interfaces for *RSat* [[RS]](#rs) and *Glucose*
[[GL]](#gl). Furthermore, Sage provides an interface to the *CryptoMiniSat* [[CMS]](#cms) SAT
solver which can be used interchangeably with DIMACS-based solvers. For this last
solver, the optional CryptoMiniSat package must be installed, this can be
accomplished by typing the following in the shell:

```
sage -i cryptominisat sagelib
```

We now show how to solve a simple SAT problem.

```
(x1 OR x2 OR x3) AND (x1 OR x2 OR (NOT x3))
```

In Sage’s notation:

Sage

```
sage: solver = SAT()
sage: solver.add_clause( ( 1,  2,  3) )
sage: solver.add_clause( ( 1,  2, -3) )
sage: solver()       # random
(None, True, True, False)
```

Python

```
>>> from sage.all import *
>>> solver = SAT()
>>> solver.add_clause( ( Integer(1),  Integer(2),  Integer(3)) )
>>> solver.add_clause( ( Integer(1),  Integer(2), -Integer(3)) )
>>> solver()       # random
(None, True, True, False)
```

Note

[`add_clause()`](sage/sat/solvers/dimacs.html#sage.sat.solvers.dimacs.DIMACS.add_clause "sage.sat.solvers.dimacs.DIMACS.add_clause") creates new variables
when necessary. When using CryptoMiniSat, it creates *all* variables up to
the given index. Hence, adding a literal involving the variable 1000 creates
up to 1000 internal variables.

DIMACS-base solvers can also be used to write DIMACS files:

Sage

```
sage: from sage.sat.solvers.dimacs import DIMACS
sage: fn = tmp_filename()
sage: solver = DIMACS(filename=fn)
sage: solver.add_clause( ( 1,  2,  3) )
sage: solver.add_clause( ( 1,  2, -3) )
sage: _ = solver.write()
sage: for line in open(fn).readlines():
....:    print(line)
p cnf 3 2
1 2 3 0
1 2 -3 0
```

Python

```
>>> from sage.all import *
>>> from sage.sat.solvers.dimacs import DIMACS
>>> fn = tmp_filename()
>>> solver = DIMACS(filename=fn)
>>> solver.add_clause( ( Integer(1),  Integer(2),  Integer(3)) )
>>> solver.add_clause( ( Integer(1),  Integer(2), -Integer(3)) )
>>> _ = solver.write()
>>> for line in open(fn).readlines():
...    print(line)
p cnf 3 2
1 2 3 0
1 2 -3 0
```

Alternatively, there is [`sage.sat.solvers.dimacs.DIMACS.clauses()`](sage/sat/solvers/dimacs.html#sage.sat.solvers.dimacs.DIMACS.clauses "sage.sat.solvers.dimacs.DIMACS.clauses"):

Sage

```
sage: from sage.sat.solvers.dimacs import DIMACS
sage: fn = tmp_filename()
sage: solver = DIMACS()
sage: solver.add_clause( ( 1,  2,  3) )
sage: solver.add_clause( ( 1,  2, -3) )
sage: solver.clauses(fn)
sage: for line in open(fn).readlines():
....:    print(line)
p cnf 3 2
1 2 3 0
1 2 -3 0
```

Python

```
>>> from sage.all import *
>>> from sage.sat.solvers.dimacs import DIMACS
>>> fn = tmp_filename()
>>> solver = DIMACS()
>>> solver.add_clause( ( Integer(1),  Integer(2),  Integer(3)) )
>>> solver.add_clause( ( Integer(1),  Integer(2), -Integer(3)) )
>>> solver.clauses(fn)
>>> for line in open(fn).readlines():
...    print(line)
p cnf 3 2
1 2 3 0
1 2 -3 0
```

These files can then be passed external SAT solvers.

### Details on Specific Solvers[¶](#details-on-specific-solvers "Link to this heading")

* [Abstract SAT Solver](sage/sat/solvers/satsolver.html)
* [SAT-Solvers via DIMACS Files](sage/sat/solvers/dimacs.html)
* [PicoSAT Solver](sage/sat/solvers/picosat.html)
* [Solve SAT problems Integer Linear Programming](sage/sat/solvers/sat_lp.html)
* [CryptoMiniSat Solver](sage/sat/solvers/cryptominisat.html)

## Converters[¶](#converters "Link to this heading")

Sage supports conversion from Boolean polynomials (also known as Algebraic Normal Form) to
Conjunctive Normal Form:

Sage

```
sage: B.<a,b,c> = BooleanPolynomialRing()
sage: from sage.sat.converters.polybori import CNFEncoder
sage: from sage.sat.solvers.dimacs import DIMACS
sage: fn = tmp_filename()
sage: solver = DIMACS(filename=fn)
sage: e = CNFEncoder(solver, B)
sage: e.clauses_sparse(a*b + a + 1)
sage: _ = solver.write()
sage: print(open(fn).read())
p cnf 3 2
-2 0
1 0
```

Python

```
>>> from sage.all import *
>>> B = BooleanPolynomialRing(names=('a', 'b', 'c',)); (a, b, c,) = B._first_ngens(3)
>>> from sage.sat.converters.polybori import CNFEncoder
>>> from sage.sat.solvers.dimacs import DIMACS
>>> fn = tmp_filename()
>>> solver = DIMACS(filename=fn)
>>> e = CNFEncoder(solver, B)
>>> e.clauses_sparse(a*b + a + Integer(1))
>>> _ = solver.write()
>>> print(open(fn).read())
p cnf 3 2
-2 0
1 0
<BLANKLINE>
```

### Details on Specific Converterts[¶](#details-on-specific-converterts "Link to this heading")

* [An ANF to CNF Converter using a Dense/Sparse Strategy](sage/sat/converters/polybori.html)

## Highlevel Interfaces[¶](#highlevel-interfaces "Link to this heading")

Sage provides various highlevel functions which make working with Boolean polynomials easier. We
construct a very small-scale AES system of equations and pass it to a SAT solver:

Sage

```
sage: sr = mq.SR(1,1,1,4,gf2=True,polybori=True)
sage: while True:
....:     try:
....:         F,s = sr.polynomial_system()
....:         break
....:     except ZeroDivisionError:
....:         pass
sage: from sage.sat.boolean_polynomials import solve as solve_sat # optional - pycryptosat
sage: s = solve_sat(F)                                            # optional - pycryptosat
sage: F.subs(s[0])                                                # optional - pycryptosat
Polynomial Sequence with 36 Polynomials in 0 Variables
```

Python

```
>>> from sage.all import *
>>> sr = mq.SR(Integer(1),Integer(1),Integer(1),Integer(4),gf2=True,polybori=True)
>>> while True:
...     try:
...         F,s = sr.polynomial_system()
...         break
...     except ZeroDivisionError:
...         pass
>>> from sage.sat.boolean_polynomials import solve as solve_sat # optional - pycryptosat
>>> s = solve_sat(F)                                            # optional - pycryptosat
>>> F.subs(s[Integer(0)])                                                # optional - pycryptosat
Polynomial Sequence with 36 Polynomials in 0 Variables
```

### Details on Specific Highlevel Interfaces[¶](#details-on-specific-highlevel-interfaces "Link to this heading")

* [SAT Functions for Boolean Polynomials](sage/sat/boolean_polynomials.html)

REFERENCES:

[[RS](#id2)]

<http://reasoning.cs.ucla.edu/rsat/>

[[GL](#id3)]

<http://www.lri.fr/~simon/?page=glucose>

[[CMS](#id4)]

<http://www.msoos.org>

[[SG09](#id1)]

<http://www.satcompetition.org/2009/format-benchmarks2009.html>

# Indices and Tables[¶](#indices-and-tables "Link to this heading")

* [Index](../genindex.html)
* [Module Index](../py-modindex.html)
* [Search Page](../search.html)
