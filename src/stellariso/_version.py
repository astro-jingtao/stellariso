"""The package version, alone in its own module.

Kept separate from ``stellariso/__init__.py`` so submodules can import it
at module level without touching the partially initialized package during
``import stellariso``.
"""

__version__ = "0.1.0"
