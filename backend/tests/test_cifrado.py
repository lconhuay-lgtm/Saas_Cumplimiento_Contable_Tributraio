"""Envelope encryption de credenciales SOL (backend/app/security.py)."""
from app.security import cifrar_clave_sol, descifrar_clave_sol


def test_cifrado_descifrado_round_trip():
    clave_original = "MiClaveSOLSuperSecreta123!"
    clave_cifrada, dek_cifrada = cifrar_clave_sol(clave_original)

    assert clave_cifrada != clave_original.encode("utf-8")
    assert dek_cifrada is not None

    clave_recuperada = descifrar_clave_sol(clave_cifrada, dek_cifrada)
    assert clave_recuperada == clave_original


def test_cada_credencial_tiene_su_propia_dek():
    """
    Dos claves iguales deben cifrarse distinto (DEK al azar por credencial)
    -- si esto fallara, una sola DEK filtrada podria abrir mas de una
    credencial en vez de solo la suya.
    """
    _, dek_1 = cifrar_clave_sol("misma-clave-sol")
    _, dek_2 = cifrar_clave_sol("misma-clave-sol")
    assert dek_1 != dek_2


def test_descifrar_con_dek_equivocada_falla():
    """La DEK de una credencial no debe servir para descifrar otra."""
    from cryptography.fernet import InvalidToken

    clave_cifrada_1, _ = cifrar_clave_sol("clave-uno")
    _, dek_cifrada_2 = cifrar_clave_sol("clave-dos")

    try:
        descifrar_clave_sol(clave_cifrada_1, dek_cifrada_2)
        assert False, "deberia haber lanzado InvalidToken"
    except InvalidToken:
        pass
