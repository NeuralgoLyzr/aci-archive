import asyncio
import hashlib
import hmac
import os
import struct
import threading
from typing import cast

import aws_encryption_sdk  # type: ignore
import boto3  # type: ignore
from aws_cryptographic_material_providers.mpl import (  # type: ignore
    AwsCryptographicMaterialProviders,
)
from aws_cryptographic_material_providers.mpl.config import MaterialProvidersConfig  # type: ignore
from aws_cryptographic_material_providers.mpl.models import CreateAwsKmsKeyringInput  # type: ignore
from aws_cryptographic_material_providers.mpl.references import IKeyring  # type: ignore
from aws_encryption_sdk import CommitmentPolicy

from aci.common import config

client = aws_encryption_sdk.EncryptionSDKClient(
    commitment_policy=CommitmentPolicy.REQUIRE_ENCRYPT_REQUIRE_DECRYPT
)

# Lazy initialization of KMS / Azure Key Vault resources
_kms_keyring: IKeyring | None = None
_azure_crypto_client: object | None = None

# --- cloudrift-backed envelope encryption -----------------------------------
#
# New ciphertext is written as a cloud-agnostic envelope: a random 256-bit data
# key encrypts the payload with AES-256-GCM (no size limit), and the data key is
# wrapped by a managed KMS/Key Vault key via cloudrift's crypto backend. Values
# written by the *previous* schemes (AWS Encryption SDK, and the bespoke Azure
# envelope below) are still read via the legacy fallback in ``decrypt`` — the
# 4-byte magic prefix distinguishes the new format and cannot collide with them
# (legacy Azure starts with 0x00, AWS-ESDK messages start with 0x01/0x02).
_CLOUDRIFT_MAGIC = b"CRV1"

_cloudrift_crypto: object | None = None

# Dedicated background event loop so the async cloudrift crypto client can be
# driven from aci's synchronous encrypt/decrypt (called inside a SQLAlchemy
# TypeDecorator, where no event loop is available / a running loop may exist).
_loop: asyncio.AbstractEventLoop | None = None
_loop_lock = threading.Lock()


def _get_async_loop() -> asyncio.AbstractEventLoop:
    global _loop
    if _loop is None:
        with _loop_lock:
            if _loop is None:
                loop = asyncio.new_event_loop()
                threading.Thread(target=loop.run_forever, daemon=True).start()
                _loop = loop
    return _loop


def _run_sync(coro: object) -> object:
    """Run an async coroutine to completion from synchronous code."""
    return asyncio.run_coroutine_threadsafe(coro, _get_async_loop()).result()  # type: ignore[arg-type]


def _get_cloudrift_crypto() -> object:
    """Lazily build the cloudrift crypto backend (AWS KMS or Azure Key Vault)."""
    global _cloudrift_crypto
    if _cloudrift_crypto is None:
        from cloudrift.crypto import get_crypto  # type: ignore

        if config.AZURE_KEY_ENCRYPTION_KEY_NAME:
            key_id = (
                f"{config.AZURE_KEY_VAULT_URL.rstrip('/')}"
                f"/keys/{config.AZURE_KEY_ENCRYPTION_KEY_NAME}"
            )
            _cloudrift_crypto = get_crypto("azure_keyvault", key_id=key_id)
        else:
            kwargs: dict = {
                "key_id": config.KEY_ENCRYPTION_KEY_ARN,
                "region": config.AWS_REGION,
            }
            if config.AWS_ENDPOINT_URL:
                kwargs["endpoint_url"] = config.AWS_ENDPOINT_URL
            _cloudrift_crypto = get_crypto("aws_kms", **kwargs)
    return _cloudrift_crypto


def _cloudrift_encrypt(plain_data: bytes) -> bytes:
    """Envelope encrypt: AES-256-GCM data key wrapped via cloudrift crypto.

    Wire format: MAGIC + [4-byte wrapped_dek_len][wrapped_dek][12-byte nonce][GCM ct+tag]
    """
    import secrets

    from cryptography.hazmat.primitives.ciphers.aead import AESGCM  # type: ignore

    dek = secrets.token_bytes(32)
    nonce = secrets.token_bytes(12)
    ciphertext = AESGCM(dek).encrypt(nonce, plain_data, None)
    wrapped_dek = cast(bytes, _run_sync(_get_cloudrift_crypto().encrypt(dek)))  # type: ignore[attr-defined]
    return _CLOUDRIFT_MAGIC + struct.pack(">I", len(wrapped_dek)) + wrapped_dek + nonce + ciphertext


def _cloudrift_decrypt(cipher_data: bytes) -> bytes:
    """Reverse of :func:`_cloudrift_encrypt` (input includes the magic prefix)."""
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM  # type: ignore

    offset = len(_CLOUDRIFT_MAGIC)
    (wrapped_dek_len,) = struct.unpack_from(">I", cipher_data, offset)
    offset += 4
    wrapped_dek = cipher_data[offset : offset + wrapped_dek_len]
    offset += wrapped_dek_len
    nonce = cipher_data[offset : offset + 12]
    offset += 12
    ciphertext = cipher_data[offset:]
    dek = cast(bytes, _run_sync(_get_cloudrift_crypto().decrypt(wrapped_dek)))  # type: ignore[attr-defined]
    return AESGCM(dek).decrypt(nonce, ciphertext, None)


def _get_kms_keyring() -> IKeyring:
    """Lazy initialization of KMS keyring to avoid errors in local environment."""
    global _kms_keyring
    if _kms_keyring is None:
        kms_client = boto3.client(
            "kms",
            region_name=config.AWS_REGION,
            endpoint_url=config.AWS_ENDPOINT_URL,
        )

        mat_prov: AwsCryptographicMaterialProviders = AwsCryptographicMaterialProviders(
            config=MaterialProvidersConfig()
        )

        keyring_input: CreateAwsKmsKeyringInput = CreateAwsKmsKeyringInput(
            kms_key_id=config.KEY_ENCRYPTION_KEY_ARN,
            kms_client=kms_client,
        )

        _kms_keyring = mat_prov.create_aws_kms_keyring(input=keyring_input)
    return _kms_keyring


def _get_azure_crypto_client() -> object:
    """Lazy initialization of Azure Key Vault CryptographyClient."""
    global _azure_crypto_client
    if _azure_crypto_client is None:
        from azure.identity import DefaultAzureCredential  # type: ignore
        from azure.keyvault.keys import KeyClient  # type: ignore
        from azure.keyvault.keys.crypto import CryptographyClient  # type: ignore

        credential = DefaultAzureCredential()
        key_client = KeyClient(vault_url=config.AZURE_KEY_VAULT_URL, credential=credential)
        key = key_client.get_key(config.AZURE_KEY_ENCRYPTION_KEY_NAME)
        _azure_crypto_client = CryptographyClient(key, credential=credential)
    return _azure_crypto_client


def _azure_encrypt(plain_data: bytes) -> bytes:
    """Envelope encryption: AES-256-GCM for data, Azure Key Vault RSA-OAEP-256 for DEK wrapping.

    Wire format: [4-byte big-endian wrapped_dek_len][wrapped_dek][12-byte nonce][GCM ciphertext+tag]
    """
    import secrets

    from azure.keyvault.keys.crypto import CryptographyClient  # type: ignore
    from azure.keyvault.keys.crypto import KeyWrapAlgorithm  # type: ignore
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM  # type: ignore

    dek = secrets.token_bytes(32)  # 256-bit data encryption key
    nonce = secrets.token_bytes(12)  # 96-bit GCM nonce
    ciphertext = AESGCM(dek).encrypt(nonce, plain_data, None)

    crypto_client = cast(CryptographyClient, _get_azure_crypto_client())
    wrapped_dek = crypto_client.wrap_key(KeyWrapAlgorithm.rsa_oaep_256, dek).encrypted_key

    return struct.pack(">I", len(wrapped_dek)) + wrapped_dek + nonce + ciphertext


def _azure_decrypt(cipher_data: bytes) -> bytes:
    """Envelope decryption: unwrap DEK via Azure Key Vault, then AES-256-GCM decrypt."""
    from azure.keyvault.keys.crypto import CryptographyClient  # type: ignore
    from azure.keyvault.keys.crypto import KeyWrapAlgorithm  # type: ignore
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM  # type: ignore

    offset = 0
    (wrapped_dek_len,) = struct.unpack_from(">I", cipher_data, offset)
    offset += 4
    wrapped_dek = cipher_data[offset : offset + wrapped_dek_len]
    offset += wrapped_dek_len
    nonce = cipher_data[offset : offset + 12]
    offset += 12
    ciphertext = cipher_data[offset:]

    crypto_client = cast(CryptographyClient, _get_azure_crypto_client())
    dek = crypto_client.unwrap_key(KeyWrapAlgorithm.rsa_oaep_256, wrapped_dek).key

    return AESGCM(dek).decrypt(nonce, ciphertext, None)


def encrypt(plain_data: bytes) -> bytes:
    # Skip encryption in local environment (for development)
    if os.getenv("SERVER_ENVIRONMENT") == "local":
        return plain_data

    # New writes use the cloud-agnostic cloudrift envelope (works for both AWS
    # KMS and Azure Key Vault, selected inside _get_cloudrift_crypto).
    return _cloudrift_encrypt(plain_data)


def decrypt(cipher_data: bytes) -> bytes:
    # Skip decryption in local environment (for development)
    if os.getenv("SERVER_ENVIRONMENT") == "local":
        return cipher_data

    # New format: cloudrift envelope (tagged with the magic prefix).
    if cipher_data.startswith(_CLOUDRIFT_MAGIC):
        return _cloudrift_decrypt(cipher_data)

    # Legacy formats (written before the cloudrift migration) stay readable:
    #   Azure  -> bespoke AES-GCM + RSA-OAEP envelope (_azure_decrypt)
    #   AWS    -> AWS Encryption SDK message (client.decrypt)
    if config.AZURE_KEY_ENCRYPTION_KEY_NAME:
        return _azure_decrypt(cipher_data)

    # TODO: ignore decryptor_header for now
    my_plaintext, _ = client.decrypt(source=cipher_data, keyring=_get_kms_keyring())
    return cast(bytes, my_plaintext)


def hmac_sha256(message: str) -> str:
    return hmac.new(
        config.API_KEY_HASHING_SECRET.encode("utf-8"), message.encode("utf-8"), hashlib.sha256
    ).hexdigest()
