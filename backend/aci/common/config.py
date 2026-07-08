import os

from aci.common.utils import get_or_generate_secret

# Azure Key Vault config — when set, takes precedence over AWS KMS for encryption.
# AZURE_KEY_ENCRYPTION_KEY_NAME: name of the key in the vault (e.g. "aci-encryption-key")
# AZURE_KEY_VAULT_URL: vault endpoint (e.g. "https://my-vault.vault.azure.net/")
AZURE_KEY_ENCRYPTION_KEY_NAME = os.getenv("AZURE_KEY_ENCRYPTION_KEY_NAME")
AZURE_KEY_VAULT_URL = os.getenv("AZURE_KEY_VAULT_URL")

# AWS KMS config — optional. When unset, field-level encryption is skipped
# (and the KMS dependency check at startup is skipped too) so on-prem
# deployments that don't use AWS KMS/Azure Key Vault can still start.
AWS_REGION = os.getenv("COMMON_AWS_REGION") or None
# AWS_ENDPOINT_URL can be empty for production (uses default AWS endpoints)
# Only set this for LocalStack or custom endpoints
AWS_ENDPOINT_URL = os.getenv("COMMON_AWS_ENDPOINT_URL") or None
KEY_ENCRYPTION_KEY_ARN = os.getenv("COMMON_KEY_ENCRYPTION_KEY_ARN") or None

API_KEY_HASHING_SECRET = get_or_generate_secret("COMMON_API_KEY_HASHING_SECRET")
