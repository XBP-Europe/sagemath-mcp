<!-- Source: https://doc.sagemath.org/html/en/reference/repl/index.html -->

# The Sage Command Line[¶](#the-sage-command-line "Link to this heading")

The Sage Read-Eval-Print-Loop (REPL) is based on IPython. In this
document, you’ll find how the IPython integration works. You should
also be familiar with the documentation for IPython.

For more details about using the Sage command line, see [the Sage
tutorial](../../tutorial/index.html).

## Running Sage[¶](#running-sage "Link to this heading")

* [Invoking Sage](options.html)
* [Sage startup scripts](startup.html)
* [Environment variables used by Sage](environ.html)
* [Relevant environment variables for other packages](environ.html#relevant-environment-variables-for-other-packages)
* [Interactively tracing execution of a command](sage/misc/trace.html)

## Preparsing[¶](#preparsing "Link to this heading")

Sage commands are “preparsed” to valid Python syntax. This allows
for example to support the `R.<x> = QQ[]` syntax.

* [The Sage Preparser](sage/repl/preparse.html)

## Loading and attaching files[¶](#loading-and-attaching-files "Link to this heading")

Sage or Python files can be loaded (similar to Python’s `execfile`)
in a Sage session. Attaching is similar, except that the attached file
is reloaded whenever it is changed.

* [Load Python, Sage, Cython, Fortran and Magma files in Sage](sage/repl/load.html)
* [Keep track of attached files](sage/repl/attach.html)

## Pretty Printing[¶](#pretty-printing "Link to this heading")

In addition to making input nicer, we also modify how results are
printed. This again builds on how IPython formats output. Technically,
this works using a modified displayhook in Python.

* [IPython Displayhook Formatters](sage/repl/display/formatter.html)
* [The Sage pretty printer](sage/repl/display/pretty_print.html)
* [Representations of objects](sage/repl/display/fancy_repr.html)
* [Utility functions for pretty-printing](sage/repl/display/util.html)

## Display Backend Infrastructure[¶](#display-backend-infrastructure "Link to this heading")

* [Display Manager](sage/repl/rich_output/display_manager.html)
* [Display Preferences](sage/repl/rich_output/preferences.html)
* [The `pretty_print` command](sage/repl/rich_output/pretty_print.html)
* [Output Buffer](sage/repl/rich_output/buffer.html)
* [Basic Output Types](sage/repl/rich_output/output_basic.html)
* [Graphics Output Types](sage/repl/rich_output/output_graphics.html)
* [Three-Dimensional Graphics Output Types](sage/repl/rich_output/output_graphics3d.html)
* [Video Output Types](sage/repl/rich_output/output_video.html)
* [Catalog of all available output container types.](sage/repl/rich_output/output_catalog.html)
* [Base Class for Backends](sage/repl/rich_output/backend_base.html)
* [Test Backend](sage/repl/rich_output/test_backend.html)
* [The backend used for doctests](sage/repl/rich_output/backend_doctest.html)
* [IPython Backend for the Sage Rich Output System](sage/repl/rich_output/backend_ipython.html)

## Miscellaneous[¶](#miscellaneous "Link to this heading")

* [Sage’s IPython Modifications](sage/repl/interpreter.html)
* [Sage’s IPython Extension](sage/repl/ipython_extension.html)
* [Magics for each of the Sage interfaces](sage/repl/interface_magic.html)
* [Interacts for the Sage Jupyter notebook](sage/repl/ipython_kernel/interact.html)
* [Widgets to be used for the Sage Jupyter notebook](sage/repl/ipython_kernel/widgets.html)
* [Installing the SageMath Jupyter Kernel and Extensions](sage/repl/ipython_kernel/install.html)
* [The Sage ZMQ Kernel](sage/repl/ipython_kernel/kernel.html)
* [Tests for the IPython integration](sage/repl/ipython_tests.html)
* [HTML Generator for JSmol](sage/repl/display/jsmol_iframe.html)
* [Sage Wrapper for Bitmap Images](sage/repl/image.html)
* [The Sage Input Hook](sage/repl/inputhook.html)

# Indices and Tables[¶](#indices-and-tables "Link to this heading")

* [Index](../genindex.html)
* [Module Index](../py-modindex.html)
* [Search Page](../search.html)
