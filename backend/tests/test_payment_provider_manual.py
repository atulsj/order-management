
import os
from decimal import Decimal

from app.services.payment_provider import (
    ProviderPaymentStatus,
    process_test_payment,
    get_test_payment_status,
)

amount = Decimal("100.00")

# Use a unique key so old simulator transactions don't affect this test.
test_key = "manual-test-" + os.urandom(8).hex()

os.environ["TEST_PROVIDER_OUTCOME"] = "FAILED"
failed_result = process_test_payment(amount, test_key)

print("First result:", failed_result.status.value)
assert failed_result.status == ProviderPaymentStatus.FAILED

# Reusing the same key must return the stored result,
# even after changing the configured outcome.
os.environ["TEST_PROVIDER_OUTCOME"] = "SUCCEEDED"
repeated_result = process_test_payment(amount, test_key)

print("Repeated result:", repeated_result.status.value)
assert repeated_result.status == ProviderPaymentStatus.FAILED

# Status lookup must return the same stored transaction.
status_result = get_test_payment_status(test_key)

print("Lookup result:", status_result.status.value)
assert status_result.status == ProviderPaymentStatus.FAILED

print("PASS: simulator outcome and idempotency checks")
