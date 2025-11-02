<!-- Source: https://doc.sagemath.org/html/en/reference/rings_numerical/index.html -->

# Fixed and Arbitrary Precision Numerical Fields[¶](#fixed-and-arbitrary-precision-numerical-fields "Link to this heading")

## Floating-Point Arithmetic[¶](#floating-point-arithmetic "Link to this heading")

Sage supports arbitrary precision real ([`RealField`](sage/rings/real_mpfr.html#sage.rings.real_mpfr.RealField "sage.rings.real_mpfr.RealField")) and complex fields
([`ComplexField`](sage/rings/complex_mpfr.html#sage.rings.complex_mpfr.ComplexField "sage.rings.complex_mpfr.ComplexField")). Sage also provides two optimized fixed precision fields for
numerical computation, the real double ([`RealDoubleField`](sage/rings/real_double.html#sage.rings.real_double.RealDoubleField "sage.rings.real_double.RealDoubleField")) and complex double
fields ([`ComplexDoubleField`](sage/rings/complex_double.html#sage.rings.complex_double.ComplexDoubleField "sage.rings.complex_double.ComplexDoubleField")).

Real and complex double elements are optimized implementations that use the
[GNU Scientific Library](../spkg/gsl.html#spkg-gsl "(in Packages and Features v10.6)") for arithmetic and some special functions.
Arbitrary precision real and complex numbers are implemented using the
[MPFR](../spkg/mpfr.html#spkg-mpfr "(in Packages and Features v10.6)") library, which builds on [GMP](../spkg/gmp.html#spkg-gmp "(in Packages and Features v10.6)").
In many cases, the [PARI](../spkg/pari.html#spkg-pari "(in Packages and Features v10.6)") C-library is used to compute
special functions when implementations aren’t otherwise available.

* [Arbitrary precision floating point real numbers using GNU MPFR](sage/rings/real_mpfr.html)
* [Arbitrary precision floating point complex numbers using GNU MPFR](sage/rings/complex_mpfr.html)
* [Arbitrary precision floating point complex numbers using GNU MPC](sage/rings/complex_mpc.html)
* [Double precision floating point real numbers](sage/rings/real_double.html)
* [Double precision floating point complex numbers](sage/rings/complex_double.html)

## Interval Arithmetic[¶](#interval-arithmetic "Link to this heading")

Sage implements real and complex interval arithmetic using
[MPFI](../spkg/mpfi.html#spkg-mpfi "(in Packages and Features v10.6)") ([`RealIntervalField`](sage/rings/real_mpfi.html#sage.rings.real_mpfi.RealIntervalField "sage.rings.real_mpfi.RealIntervalField"), [`ComplexIntervalField`](sage/rings/complex_interval_field.html#sage.rings.complex_interval_field.ComplexIntervalField "sage.rings.complex_interval_field.ComplexIntervalField"))
and [FLINT](../spkg/flint.html#spkg-flint "(in Packages and Features v10.6)") ([`RealBallField`](sage/rings/real_arb.html#sage.rings.real_arb.RealBallField "sage.rings.real_arb.RealBallField"), [`ComplexBallField`](sage/rings/complex_arb.html#sage.rings.complex_arb.ComplexBallField "sage.rings.complex_arb.ComplexBallField")).

* [Arbitrary precision real intervals using MPFI](sage/rings/real_mpfi.html)
* [Real intervals with a fixed absolute precision](sage/rings/real_interval_absolute.html)
* [Arbitrary precision complex intervals (parent class)](sage/rings/complex_interval_field.html)
* [Arbitrary precision complex intervals](sage/rings/complex_interval.html)
* [Arbitrary precision real balls](sage/rings/real_arb.html)
* [Arbitrary precision complex balls](sage/rings/complex_arb.html)

## Exact Real Arithmetic[¶](#exact-real-arithmetic "Link to this heading")

* [Lazy real and complex numbers](sage/rings/real_lazy.html)

# Indices and Tables[¶](#indices-and-tables "Link to this heading")

* [Index](../genindex.html)
* [Module Index](../py-modindex.html)
* [Search Page](../search.html)
