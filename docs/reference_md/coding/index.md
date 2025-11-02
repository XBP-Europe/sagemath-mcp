<!-- Source: https://doc.sagemath.org/html/en/reference/coding/index.html -->

# Coding Theory[¶](#coding-theory "Link to this heading")

Coding theory is the mathematical theory for algebraic and combinatorial codes
used for forward error correction in communications theory. Sage provides an
extensive library of objects and algorithms in coding theory.

Basic objects in coding theory are codes, channels, encoders, and
decoders. The following modules provide the base classes defining them.

* [Codes](sage/coding/abstract_code.html)
* [Channels](sage/coding/channel.html)
* [Encoders](sage/coding/encoder.html)
* [Decoders](sage/coding/decoder.html)

Catalogs for available constructions of the basic objects and for bounds on
the parameters of linear codes are provided.

* [Index of channels](sage/coding/channels_catalog.html)
* [Index of code constructions](sage/coding/codes_catalog.html)
* [Index of decoders](sage/coding/decoders_catalog.html)
* [Index of encoders](sage/coding/encoders_catalog.html)
* [Index of bounds on the parameters of codes](sage/coding/bounds_catalog.html)

## Linear Codes[¶](#linear-codes "Link to this heading")

The following module is a base class for linear code objects regardless their
metric.

* [Generic structures for linear codes of any metric](sage/coding/linear_code_no_metric.html)

There is a number of representatives of linear codes over a specific metric.

* [Generic structures for linear codes over the Hamming metric](sage/coding/linear_code.html)
* [Generic structures for linear codes over the rank metric](sage/coding/linear_rank_metric.html)

## Families of Linear Codes[¶](#families-of-linear-codes "Link to this heading")

Famous families of codes, listed below, are represented in Sage by their own
classes. For some of them, implementations of special decoding algorithms or
computations for structural invariants are available.

* [Parity-check code](sage/coding/parity_check_code.html)
* [Hamming codes](sage/coding/hamming_code.html)
* [Cyclic code](sage/coding/cyclic_code.html)
* [BCH code](sage/coding/bch_code.html)
* [Golay code](sage/coding/golay_code.html)
* [Reed-Muller code](sage/coding/reed_muller_code.html)
* [Reed-Solomon codes and Generalized Reed-Solomon codes](sage/coding/grs_code.html)
* [Goppa code](sage/coding/goppa_code.html)
* [Kasami code](sage/coding/kasami_codes.html)
* [AG codes](sage/coding/ag_code.html)
* [Gabidulin Code](sage/coding/gabidulin_code.html)

In contrast, for some code families Sage can only construct their generator
matrix and has no other a priori knowledge on them:

* [Linear code constructors that do not preserve the structural information](sage/coding/code_constructions.html)
* [Constructions of generator matrices using the GUAVA package for GAP](sage/coding/guava.html)
* [Enumerating binary self-dual codes](sage/coding/self_dual_codes.html)
* [Optimized low-level binary code representation](sage/coding/binary_code.html)

## Derived Code Constructions[¶](#derived-code-constructions "Link to this heading")

Sage supports the following derived code constructions. If the constituent code
is from a special code family, the derived codes inherit structural properties
like decoding radius or minimum distance:

* [Subfield subcode](sage/coding/subfield_subcode.html)
* [Punctured code](sage/coding/punctured_code.html)
* [Extended code](sage/coding/extended_code.html)

Other derived constructions that simply produce the modified generator matrix
can be found among the methods of a constructed code.

## Decoding[¶](#decoding "Link to this heading")

Information-set decoding for linear codes:

* [Information-set decoding for linear codes](sage/coding/information_set_decoder.html)

Guruswami-Sudan interpolation-based list decoding for Reed-Solomon codes:

* [Guruswami-Sudan decoder for (Generalized) Reed-Solomon codes](sage/coding/guruswami_sudan/gs_decoder.html)
* [Interpolation algorithms for the Guruswami-Sudan decoder](sage/coding/guruswami_sudan/interpolation.html)
* [Guruswami-Sudan utility methods](sage/coding/guruswami_sudan/utils.html)

## Automorphism Groups of Linear Codes[¶](#automorphism-groups-of-linear-codes "Link to this heading")

* [Canonical forms and automorphism group computation for linear codes over finite fields](sage/coding/codecan/codecan.html)
* [Canonical forms and automorphisms for linear codes over finite fields](sage/coding/codecan/autgroup_can_label.html)

## Bounds for Parameters of Linear Codes[¶](#bounds-for-parameters-of-linear-codes "Link to this heading")

* [Bounds for parameters of codes](sage/coding/code_bounds.html)
* [Delsarte (or linear programming) bounds](sage/coding/delsarte_bounds.html)

## Databases for Coding Theory[¶](#databases-for-coding-theory "Link to this heading")

* [Access functions to online databases for coding theory](sage/coding/databases.html)
* [Database of two-weight codes](sage/coding/two_weight_db.html)

## Miscellaneous Modules[¶](#miscellaneous-modules "Link to this heading")

There is at least one module in Sage for source coding in communications theory:

* [Huffman encoding](sage/coding/source_coding/huffman.html)

# Indices and Tables[¶](#indices-and-tables "Link to this heading")

* [Index](../genindex.html)
* [Module Index](../py-modindex.html)
* [Search Page](../search.html)
