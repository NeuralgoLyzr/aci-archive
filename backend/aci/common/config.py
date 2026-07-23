import os
from aci.common.utils import check_and_get_env_variable

AWS_REGION = check_and_get_env_variable("COMMON_AWS_REGION")
# AWS_ENDPOINT_URL can be empty for production (uses default AWS endpoints)
# Only set this for LocalStack or custom endpoints
AWS_ENDPOINT_URL = os.getenv("COMMON_AWS_ENDPOINT_URL") or None
KEY_ENCRYPTION_KEY_ARN = check_and_get_env_variable("COMMON_KEY_ENCRYPTION_KEY_ARN")
API_KEY_HASHING_SECRET = check_and_get_env_variable("COMMON_API_KEY_HASHING_SECRET")
