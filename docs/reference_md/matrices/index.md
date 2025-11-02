<!-- Source: https://doc.sagemath.org/html/en/reference/matrices/index.html -->

# Matrices and Spaces of Matrices[¶](#matrices-and-spaces-of-matrices "Link to this heading")

Sage provides native support for working with matrices over any
commutative or noncommutative ring. The parent object for a matrix
is a matrix space `MatrixSpace(R, n, m)` of all
\(n\times
m\) matrices over a ring \(R\).

To create a matrix, either use the `matrix(...)`
function or create a matrix space using the
`MatrixSpace` command and coerce an object into it.

Matrices also act on row vectors, which you create using the
`vector(...)` command or by making a
`VectorSpace` and coercing lists into it. The natural
action of matrices on row vectors is from the right. Sage currently
does not have a column vector class (on which matrices would act
from the left), but this is planned.

In addition to native Sage matrices, Sage also includes the
following additional ways to compute with matrices:

* Several math software systems included with Sage have their own
  native matrix support, which can be used from Sage. E.g., PARI,
  GAP, Maxima, and Singular all have a notion of matrices.
* The GSL C-library is included with Sage, and can be used via
  Cython.
* The [`scipy`](https://docs.scipy.org/doc/scipy/index.html#module-scipy "(in SciPy v1.12.0)") module provides support for
  *sparse* numerical linear algebra, among many other things.
* The `numpy` module, which you load by typing
  `import numpy` is included standard with Sage. It
  contains a very sophisticated and well developed array class, plus
  optimized support for *numerical linear algebra*. Sage’s matrices
  over RDF and CDF (native floating-point real and complex numbers)
  use numpy.

Finally, this module contains some data-structures for matrix-like
objects like operation tables (e.g. the multiplication table of a group).

* [Matrix Spaces](sage/matrix/matrix_space.html)
* [General matrix Constructor and display options](sage/matrix/constructor.html)
* [Constructors for special matrices](sage/matrix/special.html)
* [Helpers for creating matrices](sage/matrix/args.html)
* [Matrices over an arbitrary ring](sage/matrix/docs.html)
* [Base class for matrices, part 0](sage/matrix/matrix0.html)
* [Base class for matrices, part 1](sage/matrix/matrix1.html)
* [Base class for matrices, part 2](sage/matrix/matrix2.html)
* [Generic Asymptotically Fast Strassen Algorithms](sage/matrix/strassen.html)
* [Minimal Polynomials of Linear Recurrence Sequences](sage/matrix/berlekamp_massey.html)
* [Base class for dense matrices](sage/matrix/matrix_dense.html)
* [Base class for sparse matrices](sage/matrix/matrix_sparse.html)
* [Dense Matrices over a general ring](sage/matrix/matrix_generic_dense.html)
* [Sparse Matrices over a general ring](sage/matrix/matrix_generic_sparse.html)
* [Dense matrices over the integer ring](sage/matrix/matrix_integer_dense.html)
* [Sparse integer matrices](sage/matrix/matrix_integer_sparse.html)
* [Modular algorithm to compute Hermite normal forms of integer matrices](sage/matrix/matrix_integer_dense_hnf.html)
* [Saturation over ZZ](sage/matrix/matrix_integer_dense_saturation.html)
* [Dense matrices over the rational field](sage/matrix/matrix_rational_dense.html)
* [Sparse rational matrices](sage/matrix/matrix_rational_sparse.html)
* [Dense matrices using a NumPy backend](sage/matrix/matrix_double_dense.html)
* [Dense matrices over the Real Double Field using NumPy](sage/matrix/matrix_real_double_dense.html)
* [Dense matrices over GF(2) using the M4RI library](sage/matrix/matrix_mod2_dense.html)
* [Dense matrices over \(\GF{2^e}\) for \(2 \leq e \leq 16\) using the M4RIE library](sage/matrix/matrix_gf2e_dense.html)
* [Dense matrices over \(\ZZ/n\ZZ\) for \(n < 94906266\) using LinBox’s `Modular<double>`](sage/matrix/matrix_modn_dense_double.html)
* [Dense matrices over \(\ZZ/n\ZZ\) for \(n < 2^{8}\) using LinBox’s `Modular<float>`](sage/matrix/matrix_modn_dense_float.html)
* [Sparse matrices over \(\ZZ/n\ZZ\) for \(n\) small](sage/matrix/matrix_modn_sparse.html)
* [Symbolic dense matrices](sage/matrix/matrix_symbolic_dense.html)
* [Symbolic sparse matrices](sage/matrix/matrix_symbolic_sparse.html)
* [Dense matrices over the Complex Double Field using NumPy](sage/matrix/matrix_complex_double_dense.html)
* [Arbitrary precision complex ball matrices](sage/matrix/matrix_complex_ball_dense.html)
* [Dense matrices over univariate polynomials over fields](sage/matrix/matrix_polynomial_dense.html)
* [Dense matrices over multivariate polynomials over fields](sage/matrix/matrix_mpolynomial_dense.html)
* [Matrices over Cyclotomic Fields](sage/matrix/matrix_cyclo_dense.html)
* [Operation Tables](sage/matrix/operation_table.html)
* [Actions used by the coercion model for matrix and vector multiplications](sage/matrix/action.html)
* [Functions for changing the base ring of matrices quickly](sage/matrix/change_ring.html)
* [Echelon matrices over finite fields.](sage/matrix/echelon_matrix.html)
* [Miscellaneous matrix functions](sage/matrix/matrix_misc.html)
* [Matrix windows](sage/matrix/matrix_window.html)
* [Misc matrix algorithms](sage/matrix/misc.html)
* [Misc matrix algorithms using MPFR](sage/matrix/misc_mpfr.html)
* [Misc matrix algorithms using FLINT](sage/matrix/misc_flint.html)
* [Calculate symplectic bases for matrices over fields and the integers.](sage/matrix/symplectic_basis.html)
* [\(J\)-ideals of matrices](sage/matrix/compute_J_ideal.html)
* [Benchmarks for matrices](sage/matrix/benchmark.html)

# Indices and Tables[¶](#indices-and-tables "Link to this heading")

* [Index](../genindex.html)
* [Module Index](../py-modindex.html)
* [Search Page](../search.html)
