"""AI DJ — structure-aware auto-mixing."""

import os

__version__ = "0.1.0"


def _ensure_ca_bundle() -> None:
    """Give Python a CA bundle to verify HTTPS against, if it lacks one.

    The python.org macOS installer ships an OpenSSL with no usable default CA file
    until "Install Certificates.command" is run, so every urllib HTTPS request fails —
    including Demucs and torch.hub fetching model weights on first use. Pointing
    SSL_CERT_FILE at certifi's Mozilla bundle fixes that without disabling
    verification. Child processes (Demucs runs as one) inherit it. A value the user
    already set is left alone.
    """
    if os.environ.get("SSL_CERT_FILE"):
        return
    import ssl

    if os.path.exists(ssl.get_default_verify_paths().openssl_cafile or ""):
        return  # this Python already has a working trust store
    try:
        import certifi
    except ImportError:
        return
    os.environ["SSL_CERT_FILE"] = certifi.where()


_ensure_ca_bundle()
