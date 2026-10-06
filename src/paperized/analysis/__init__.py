"""Measurement: source blockstates and model roots in, IR geometry out.

A package rather than a loose directory on purpose. Without an ``__init__.py`` here,
``setuptools.find_packages`` does not see it, so a built wheel omits this whole
subpackage and every ``paperized.analysis`` import fails at runtime -- while working
fine from a source checkout, because the path resolution differs. That is the worst
failure mode for packaging: invisible until someone installs the thing.
"""
