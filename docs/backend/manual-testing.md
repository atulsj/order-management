# Manual backend testing

This walkthrough uses PowerShell and the local simulator. It exercises authentication, catalog, two-warehouse allocation, payment, split fulfillment, cancellation, idempotency, authorization, and failure review.

## 1. Start and seed

```powershell
cd backend
docker compose up --build -d
docker compose exec api python -m app.seed
docker compose ps
```

```powershell
$Api = "http://localhost:8000"
$Keycloak = "http://localhost:8180/realms/oms/protocol/openid-connect/token"
Invoke-RestMethod "$Api/live"
Invoke-RestMethod "$Api/ready"
```

Open `http://localhost:8000/docs` to compare every command with OpenAPI.

## 2. Obtain local learning tokens

The password grant is enabled only to make command-line learning convenient. The Angular application uses authorization code + PKCE, and production must not copy this password-grant setup.

```powershell
function Get-OmsToken([string]$Username, [string]$Password) {
    $response = Invoke-RestMethod `
        -Method Post `
        -Uri $Keycloak `
        -ContentType "application/x-www-form-urlencoded" `
        -Body @{
            client_id  = "oms-spa"
            grant_type = "password"
            username   = $Username
            password   = $Password
        }
    return $response.access_token
}

$CustomerToken = Get-OmsToken "customer" "customer_password"
$OperatorToken = Get-OmsToken "operator" "operator_password"
$AdminToken = Get-OmsToken "admin" "admin_password"

$CustomerHeaders = @{ Authorization = "Bearer $CustomerToken" }
$OperatorHeaders = @{ Authorization = "Bearer $OperatorToken" }
$AdminHeaders = @{ Authorization = "Bearer $AdminToken" }
```

If this fails, wait for Keycloak readiness and inspect:

```powershell
docker compose logs keycloak
```

## 3. Inspect seeded catalog and warehouses

Catalog is public:

```powershell
$catalog = Invoke-RestMethod "$Api/api/v1/products?limit=20&offset=0"
$catalog.items | Format-Table id, sku, name, price, quantity_available
```

Warehouse and detailed inventory are operational:

```powershell
$warehouses = Invoke-RestMethod `
    -Headers $OperatorHeaders `
    "$Api/api/v1/warehouses"
$warehouses | Format-Table id, code, name, priority

$inventory = Invoke-RestMethod `
    -Headers $OperatorHeaders `
    "$Api/api/v1/inventory"
$inventory | Format-Table id, warehouse_id, product_id, quantity_on_hand, quantity_reserved, quantity_available
```

## 4. Create a customer address

```powershell
$addressBody = @{
    label          = "home"
    recipient_name = "Casey Customer"
    line1          = "100 Learning Lane"
    line2          = $null
    city           = "Example City"
    region         = "CA"
    postal_code    = "90001"
    country_code   = "US"
    phone          = "+15555550100"
    is_default     = $true
} | ConvertTo-Json

$address = Invoke-RestMethod `
    -Method Post `
    -Headers $CustomerHeaders `
    -ContentType "application/json" `
    -Body $addressBody `
    "$Api/api/v1/me/addresses"
```

The first authenticated operation creates/synchronizes the local customer profile from Keycloak claims.

## 5. Create a split-allocation order

Seed data places 25 units in EAST and 25 in WEST. Ordering 30 of one product forces a split.

```powershell
$product = $catalog.items[0]
$orderBody = @{
    address_id = $address.id
    items = @(
        @{
            product_id = $product.id
            quantity   = 30
        }
    )
} | ConvertTo-Json -Depth 5

$order = Invoke-RestMethod `
    -Method Post `
    -Headers $CustomerHeaders `
    -ContentType "application/json" `
    -Body $orderBody `
    "$Api/api/v1/orders"

$order | ConvertTo-Json -Depth 10
```

Expected:

- status `PENDING_PAYMENT`;
- one aggregated order item;
- two reserved allocations, normally 25 then 5;
- physical on-hand unchanged;
- reserved increased in both warehouses.

Verify:

```powershell
Invoke-RestMethod `
    -Headers $OperatorHeaders `
    "$Api/api/v1/inventory?product_id=$($product.id)" |
    Format-Table warehouse_id, quantity_on_hand, quantity_reserved, quantity_available
```

## 6. Pay with the simulator

```powershell
$PaymentKey = "manual-payment-$([guid]::NewGuid())"
$paymentBody = @{ order_id = $order.id } | ConvertTo-Json
$paymentHeaders = @{
    Authorization     = "Bearer $CustomerToken"
    "Idempotency-Key" = $PaymentKey
}

$payment = Invoke-RestMethod `
    -Method Post `
    -Headers $paymentHeaders `
    -ContentType "application/json" `
    -Body $paymentBody `
    "$Api/api/v1/payments"

$payment | Format-List
```

Default simulator outcome is `SUCCEEDED`.

Verify order and stock:

```powershell
$order = Invoke-RestMethod `
    -Headers $CustomerHeaders `
    "$Api/api/v1/orders/$($order.id)"
$order.status

Invoke-RestMethod `
    -Headers $OperatorHeaders `
    "$Api/api/v1/inventory?product_id=$($product.id)" |
    Format-Table warehouse_id, quantity_on_hand, quantity_reserved
```

Expected status is `CONFIRMED`. On-hand is still 25/25 and reserved remains 25/5. Payment confirmation does not represent physical dispatch.

## 7. Test payment idempotency

Repeat the exact request with the same key:

```powershell
$repeat = Invoke-RestMethod `
    -Method Post `
    -Headers $paymentHeaders `
    -ContentType "application/json" `
    -Body $paymentBody `
    "$Api/api/v1/payments"

"first=$($payment.id) repeated=$($repeat.id)"
```

IDs must match and stock must not change.

Reusing the key for another order or principal must return HTTP 409.

## 8. Create split shipments

Read allocation IDs:

```powershell
$order = Invoke-RestMethod `
    -Headers $OperatorHeaders `
    "$Api/api/v1/orders/$($order.id)"
$allocations = $order.items[0].allocations
$allocations | Format-Table id, inventory_id, quantity, status
```

Create and ship the first warehouse allocation:

```powershell
$shipmentBody = @{
    order_id        = $order.id
    allocation_ids  = @($allocations[0].id)
    carrier         = "Learning Carrier"
    tracking_number = "LEARN-$([guid]::NewGuid().ToString('N').Substring(0,12))"
} | ConvertTo-Json

$shipment = Invoke-RestMethod `
    -Method Post `
    -Headers $OperatorHeaders `
    -ContentType "application/json" `
    -Body $shipmentBody `
    "$Api/api/v1/shipments"

$shipment = Invoke-RestMethod `
    -Method Post `
    -Headers $OperatorHeaders `
    "$Api/api/v1/shipments/$($shipment.id)/ship"
```

Expected order status becomes `PARTIALLY_FULFILLED`. The first warehouse’s on-hand and reserved decrease by that allocation; the other does not.

Repeat with `$allocations[1].id`. After shipping the second allocation, order status becomes `FULFILLED`.

Record delivery:

```powershell
Invoke-RestMethod `
    -Method Post `
    -Headers $OperatorHeaders `
    "$Api/api/v1/shipments/$($shipment.id)/deliver"
```

## 9. Test unpaid cancellation

Create a new small order, do not pay it, then:

```powershell
$cancelHeaders = @{
    Authorization     = "Bearer $CustomerToken"
    "Idempotency-Key" = "cancel-$([guid]::NewGuid())"
}

Invoke-RestMethod `
    -Method Post `
    -Headers $cancelHeaders `
    "$Api/api/v1/orders/$($newOrder.id)/cancel"
```

Expected: `CANCELLED`, allocations `RELEASED`, on-hand unchanged, reserved reduced.

## 10. Test paid cancellation/refund

Create and successfully pay an order but do not create a shipment. Call the same cancel endpoint with a new cancellation key.

Expected:

1. order enters `CANCELLATION_PENDING`;
2. simulator refund succeeds;
3. payment becomes `REFUNDED`;
4. order becomes `CANCELLED`;
5. reservation releases;
6. physical on-hand remains unchanged.

Once any allocation is shipped, cancellation returns 409 and directs the business flow to returns.

## 11. Test role boundaries

Customer token cannot create products:

```powershell
try {
    Invoke-RestMethod `
        -Method Post `
        -Headers $CustomerHeaders `
        -ContentType "application/json" `
        -Body (@{
            sku = "FORBIDDEN-001"
            name = "Forbidden"
            price = 10
        } | ConvertTo-Json) `
        "$Api/api/v1/products"
} catch {
    $_.Exception.Response.StatusCode.value__
}
```

Expected: 403.

No bearer token on `/api/v1/me` returns 401. A customer requesting another customer’s order receives 404, avoiding resource-existence leakage.

## 12. Test provider failure

Recreate API and worker with definitive failure:

```powershell
$env:SIMULATOR_OUTCOME = "FAILED"
docker compose up -d --force-recreate api worker beat
```

Create a new order and unique payment key. Expected:

- payment `FAILED`;
- order remains `PENDING_PAYMENT` for attempts one and two;
- reservation retained;
- retry is accepted only inside five minutes;
- third failure cancels and releases.

Restore success afterward:

```powershell
$env:SIMULATOR_OUTCOME = "SUCCEEDED"
docker compose up -d --force-recreate api worker beat
```

## 13. Test uncertain payment and review queue

```powershell
$env:SIMULATOR_OUTCOME = "PROCESSING"
docker compose up -d --force-recreate api worker beat
```

Create a new order/payment. Expected:

- payment remains `PENDING`;
- `requires_review` is true;
- `next_reconciliation_at` and deadline exist;
- another payment key for the order returns 409;
- inventory remains reserved.

Operator review list:

```powershell
Invoke-RestMethod `
    -Headers $OperatorHeaders `
    "$Api/api/v1/payments?requires_review=true"
```

Force an immediate reconciliation attempt:

```powershell
Invoke-RestMethod `
    -Method Post `
    -Headers $OperatorHeaders `
    "$Api/api/v1/payments/reconcile"
```

The simulator keeps the original processing result, so the payment remains pending and reschedules.

## 14. Inspect database state

Local-only examples:

```powershell
docker compose exec postgres psql `
    -U oms_user `
    -d order_management `
    -c "SELECT id, status, total_amount, customer_id FROM orders ORDER BY id DESC LIMIT 10;"

docker compose exec postgres psql `
    -U oms_user `
    -d order_management `
    -c "SELECT id, order_id, status, requires_review, next_reconciliation_at, reconciliation_deadline_at FROM payments ORDER BY id DESC LIMIT 10;"

docker compose exec postgres psql `
    -U oms_user `
    -d order_management `
    -c "SELECT warehouse_id, product_id, quantity_on_hand, quantity_reserved FROM inventory ORDER BY warehouse_id, product_id;"
```

Never edit production order/payment/inventory rows manually. Use these as read-only inspection commands.

## 15. Inspect async and observability behavior

- RabbitMQ queues: `http://localhost:15672`, login `oms` / `local_dev_password`.
- Mail messages: `http://localhost:8025`.
- Metrics: `http://localhost:8000/metrics`.
- Prometheus: `http://localhost:9090` with observability profile.
- Grafana: `http://localhost:3000`, `admin` / `local_grafana_password`.
- Structured logs:

```powershell
docker compose logs -f api worker beat
```

Trace one operation by copying `X-Request-ID` from the response and searching JSON logs.

## 16. Clean up

```powershell
docker compose down
```

Do not add `-v` unless you intentionally want to delete all local state.
