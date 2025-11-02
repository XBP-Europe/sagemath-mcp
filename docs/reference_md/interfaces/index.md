<!-- Source: https://doc.sagemath.org/html/en/reference/interfaces/index.html -->

# Interpreter Interfaces[¶](#interpreter-interfaces "Link to this heading")

Sage provides a unified interface to the best computational
software. This is accomplished using both C-libraries (see
[C/C++ Library Interfaces](../libs/index.html))
and interpreter interfaces, which are
implemented using pseudo-tty’s, system files, etc. This chapter is
about these interpreter interfaces.

Note

Each interface requires that the corresponding software is
installed on your computer. Sage includes GAP, PARI, Singular, and
Maxima, but does not include Octave (very easy to install), MAGMA
(non-free), Maple (non-free), or Mathematica (non-free).

There is overhead associated with each call to one of these
systems. For example, computing `2+2` thousands of times using
the GAP interface will be slower than doing it directly in
Sage. In contrast, the C-library interfaces of
[C/C++ Library Interfaces](../libs/index.html)
incur less overhead.

In addition to the commands described for each of the interfaces
below, you can also type e.g., `%gap`,
`%magma`, etc., to directly interact with a given
interface in its state. Alternatively, if `X` is an
interface object, typing `X.interact()` allows you to
interact with it. This is completely different than
`X.console()` which starts a complete new copy of
whatever program `X` interacts with. Note that the
input for `X.interact()` is handled by Sage, so the
history buffer is the same as for Sage, tab completion is as for
Sage (unfortunately!), and input that spans multiple lines must be
indicated using a backslash at the end of each line. You can pull
data into an interactive session with `X` using
`sage(expression)`.

The console and interact methods of an interface do very different
things. For example, using gap as an example:

1. `gap.console()`: You are completely using another
   program, e.g., gap/magma/gp Here Sage is serving as nothing more
   than a convenient program launcher, similar to bash.
2. `gap.interact()`: This is a convenient way to
   interact with a running gap instance that may be “full of” Sage
   objects. You can import Sage objects into this gap (even from the
   interactive interface), etc.

The console function is very useful on occasion, since you get the
exact actual program available (especially useful for tab completion
and testing to make sure nothing funny is going on).

* [Common Interface Functionality](sage/interfaces/interface.html)
* [Common Interface Functionality through Pexpect](sage/interfaces/expect.html)
* [Sage wrapper around pexpect’s `spawn` class and](sage/interfaces/sagespawn.html)
* [Abstract base classes for interface elements](sage/interfaces/abc.html)
* [Interface to Axiom](sage/interfaces/axiom.html)
* [The Elliptic Curve Factorization Method](sage/interfaces/ecm.html)
* [Interface to 4ti2](sage/interfaces/four_ti_2.html)
* [Interface to FriCAS](sage/interfaces/fricas.html)
* [Interface to Frobby for fast computations on monomial ideals.](sage/interfaces/frobby.html)
* [Interface to GAP](sage/interfaces/gap.html)
* [Interface to GAP3](sage/interfaces/gap3.html)
* [Interface to Groebner Fan](sage/interfaces/gfan.html)
* [Pexpect Interface to Giac](sage/interfaces/giac.html)
* [Interface to the Gnuplot interpreter](sage/interfaces/gnuplot.html)
* [Interface to the GP calculator of PARI/GP](sage/interfaces/gp.html)
* [Interface for extracting data and generating images from Jmol readable files.](sage/interfaces/jmoldata.html)
* [Interface to KASH](sage/interfaces/kash.html)
* [Library interface to Kenzo](sage/interfaces/kenzo.html)
* [Interface to LattE integrale programs](sage/interfaces/latte.html)
* [Interface to LiE](sage/interfaces/lie.html)
* [Lisp Interface](sage/interfaces/lisp.html)
* [Interface to Macaulay2](sage/interfaces/macaulay2.html)
* [Interface to Magma](sage/interfaces/magma.html)
* [Interface to the free online MAGMA calculator](sage/interfaces/magma_free.html)
* [Interface to Maple](sage/interfaces/maple.html)
* [Interface to Mathematica](sage/interfaces/mathematica.html)
* [Interface to Mathics](sage/interfaces/mathics.html)
* [Interface to MATLAB](sage/interfaces/matlab.html)
* [Pexpect interface to Maxima](sage/interfaces/maxima.html)
* [Abstract interface to Maxima](sage/interfaces/maxima_abstract.html)
* [Library interface to Maxima](sage/interfaces/maxima_lib.html)
* [Interface to MuPAD](sage/interfaces/mupad.html)
* [Interface to mwrank](sage/interfaces/mwrank.html)
* [Interface to GNU Octave](sage/interfaces/octave.html)
* [Interface to PHC.](sage/interfaces/phc.html)
* [Interface to polymake](sage/interfaces/polymake.html)
* [POV-Ray, The Persistence of Vision Ray Tracer](sage/interfaces/povray.html)
* [Parallel Interface to the Sage interpreter](sage/interfaces/psage.html)
* [Interface to QEPCAD](sage/interfaces/qepcad.html)
* [Interfaces to R](sage/interfaces/r.html)
* [Interface to several Rubik’s cube solvers.](sage/interfaces/rubik.html)
* [Interface to Sage](sage/interfaces/sage0.html)
* [Interface to Scilab](sage/interfaces/scilab.html)
* [Interface to Singular](sage/interfaces/singular.html)
* [SymPy –> Sage conversion](sage/interfaces/sympy.html)
* [The Tachyon Ray Tracer](sage/interfaces/tachyon.html)
* [Interface to TIDES](sage/interfaces/tides.html)
* [Interface to the Sage cleaner](sage/interfaces/cleaner.html)
* [Quitting interfaces](sage/interfaces/quit.html)
* [An interface to read data files](sage/interfaces/read_data.html)

# Indices and Tables[¶](#indices-and-tables "Link to this heading")

* [Index](../genindex.html)
* [Module Index](../py-modindex.html)
* [Search Page](../search.html)
