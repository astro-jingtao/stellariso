def test_import():
    import stellariso  # noqa: PLC0415 — the import is the behavior under test

    assert stellariso.__version__ == '0.1.0'

