import os
import traceback
from aci.common.encryption import decrypt, encrypt
from aci.common.exceptions import DependencyCheckError


def check_aws_kms_dependency() -> None:
    check_data = b"start up dependency check"

    try:
        encrypted_data = encrypt(check_data)
        decrypted_data = decrypt(encrypted_data)

        if check_data != decrypted_data:
            raise DependencyCheckError(
                f"Encryption/decryption using AWS KMS failed: original data '{check_data!r}'"
                f"does not match decrypted result '{decrypted_data!r}'"
            )
    except Exception as e:
        # Provide more detailed error information
        error_msg = (
            f"AWS KMS dependency check failed: {type(e).__name__}: {str(e)}\n"
            f"This usually indicates a permissions or configuration issue.\n"
            f"Please check:\n"
            f"1. The KMS key exists and is accessible\n"
            f"2. The ECS task role has kms:Encrypt, kms:Decrypt, and kms:GenerateDataKey permissions\n"
            f"3. The COMMON_KEY_ENCRYPTION_KEY_ARN is correct\n"
            f"4. The AWS region matches where the key was created\n\n"
            f"Full traceback:\n{traceback.format_exc()}"
        )
        raise DependencyCheckError(error_msg) from e


def check_dependencies() -> None:
    # Skip KMS check only in local environment (for development)
    if os.getenv("SERVER_ENVIRONMENT") == "local":
        print("Skipping KMS dependency check for local environment")
        return
    
    check_aws_kms_dependency()
