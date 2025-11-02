<!-- Source: https://doc.sagemath.org/html/en/reference/libs/index.html -->

# C/C++ Library Interfaces[¶](#c-c-library-interfaces "Link to this heading")

An underlying philosophy in the development of Sage is that it
should provide unified library-level access to the some of the best
GPL’d C/C++ libraries. Sage provides access to many libraries which
are included with Sage.

The interfaces are implemented via shared libraries and data is
moved between systems purely in memory. In particular, there is no
interprocess interpreter parsing (e.g., `pexpect`),
since everything is linked together and run as a single process.
This is much more robust and efficient than using `pexpect`.

Each of these interfaces is used by other parts of Sage. For
example, eclib is used by the elliptic curves module to compute
ranks of elliptic curves and PARI is used for computation of class
groups. It is thus probably not necessary for a casual user of Sage
to be aware of the modules described in this chapter.

## ECL[¶](#ecl "Link to this heading")

* [Library interface to Embeddable Common Lisp (ECL)](sage/libs/ecl.html)

## eclib[¶](#eclib "Link to this heading")

* [Sage interface to Cremona’s `eclib` library (also known as `mwrank`)](sage/libs/eclib/interface.html)
* [Cython interface to Cremona’s `eclib` library (also known as `mwrank`)](sage/libs/eclib/mwrank.html)
* [Cremona matrices](sage/libs/eclib/mat.html)
* [Modular symbols using eclib newforms](sage/libs/eclib/newforms.html)
* [Cremona modular symbols](sage/libs/eclib/homspace.html)
* [Cremona modular symbols](sage/libs/eclib/constructor.html)

## FLINT[¶](#flint "Link to this heading")

* [FLINT fmpz\_poly class wrapper](sage/libs/flint/fmpz_poly_sage.html)
* [File: sage/libs/flint/fmpq\_poly\_sage.pyx (starting at line 1)](sage/libs/flint/fmpq_poly_sage.html)
* [FLINT Arithmetic Functions](sage/libs/flint/arith_sage.html)
* [Interface to FLINT’s `qsieve_factor()`. This used to interact](sage/libs/flint/qsieve_sage.html)
* [File: sage/libs/flint/ulong\_extras\_sage.pyx (starting at line 1)](sage/libs/flint/ulong_extras_sage.html)

## GMP-ECM[¶](#gmp-ecm "Link to this heading")

* [The Elliptic Curve Method for Integer Factorization (ECM)](sage/libs/libecm.html)

## GSL[¶](#gsl "Link to this heading")

* [GSL arrays](sage/libs/gsl/array.html)

## lcalc[¶](#lcalc "Link to this heading")

* [Rubinstein’s lcalc library](sage/libs/lcalc/lcalc_Lfunction.html)

## libSingular[¶](#libsingular "Link to this heading")

* [libSingular: Functions](sage/libs/singular/function.html)
* [libSingular: Function Factory](sage/libs/singular/function_factory.html)
* [libSingular: Conversion Routines and Initialisation](sage/libs/singular/singular.html)
* [Wrapper for Singular’s Polynomial Arithmetic](sage/libs/singular/polynomial.html)
* [libSingular: Options](sage/libs/singular/option.html)
* [Wrapper for Singular’s Rings](sage/libs/singular/ring.html)
* [Singular’s Groebner Strategy Objects](sage/libs/singular/groebner_strategy.html)

## GAP[¶](#gap "Link to this heading")

* [Context Managers for LibGAP](sage/libs/gap/context_managers.html)
* [Common global functions defined by GAP.](sage/libs/gap/gap_functions.html)
* [Long tests for GAP](sage/libs/gap/test_long.html)
* [Utility functions for GAP](sage/libs/gap/util.html)
* [Library Interface to GAP](sage/libs/gap/libgap.html)
* [Short tests for GAP](sage/libs/gap/test.html)
* [GAP element wrapper](sage/libs/gap/element.html)
* [LibGAP Workspace Support](sage/libs/gap/saved_workspace.html)

## LinBox[¶](#linbox "Link to this heading")

* [Interface between flint matrices and linbox](sage/libs/linbox/linbox_flint_interface.html)

## lrcalc[¶](#lrcalc "Link to this heading")

* [An interface to Anders Buch’s Littlewood-Richardson Calculator `lrcalc`](sage/libs/lrcalc/lrcalc.html)

## mpmath[¶](#mpmath "Link to this heading")

* [Utilities for Sage-mpmath interaction](sage/libs/mpmath/utils.html)

## NTL[¶](#ntl "Link to this heading")

* [Victor Shoup’s NTL C++ Library](sage/libs/ntl/all.html)

## PARI[¶](#pari "Link to this heading")

* [Interface between Sage and PARI](sage/libs/pari.html)
* [Convert PARI objects to Sage types](sage/libs/pari/convert_sage.html)
* [Ring of pari objects](sage/rings/pari_ring.html)

## Symmetrica[¶](#symmetrica "Link to this heading")

* [Symmetrica library](sage/libs/symmetrica/symmetrica.html)

# Indices and Tables[¶](#indices-and-tables "Link to this heading")

* [Index](../genindex.html)
* [Module Index](../py-modindex.html)
* [Search Page](../search.html)
