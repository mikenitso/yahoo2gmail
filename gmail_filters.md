# Gmail Filters

## Updates (combined: list mail + shipping + banking alerts)

Has the words:

```
(list-id: OR precedence:bulk OR list-unsubscribe: OR "Auto-Submitted: auto-generated" OR
(from:(@ups.com OR @fedex.com OR @usps.gov OR @usps.com OR @informeddelivery.usps.com OR @dhl.com) AND
(subject:("Ship Notification" OR "Shipment" OR "Tracking" OR "Tracking Number" OR "Tracking #" OR "Delivery" OR "Delivery Notice" OR "Delivery Exception" OR "Attempted Delivery" OR "Delivery Attempted" OR "Delivery Failed" OR "Address Issue" OR "Delivery Confirmation" OR "Delivered" OR "Delivery Delayed" OR "Shipment Delayed" OR "Out for Delivery" OR "Informed Delivery" OR "Daily Digest" OR "Digest" OR "Package Update" OR "Delivery Update" OR "Out for Delivery Today" OR "Arriving Today" OR "Scheduled Delivery" OR "Expected Delivery" OR "On the Way" OR "Your Package" OR "Your Shipment" OR "Your Delivery"))) OR
(from:(noreply OR "no-reply" OR alerts OR notifications) AND
(subject:("statement" OR "payment" OR "due" OR "transaction" OR "purchase" OR "card" OR "account" OR "alert" OR "security" OR "verification" OR "fraud" OR "credit score" OR "FICO"))))
```

Categorize as: **Updates**

## Updates (split filters to avoid Gmail warnings)

### Filter 1: list + banking alerts

Has the words:

```
list-id: OR precedence:bulk OR list-unsubscribe: OR "Auto-Submitted: auto-generated" OR
from:(noreply OR "no-reply" OR alerts OR notifications) AND
subject:("statement" OR "payment" OR "due" OR "transaction" OR "purchase" OR "card" OR "account" OR "alert" OR "security" OR "verification" OR "fraud" OR "credit score" OR "FICO")
```

Categorize as: **Updates**

### Filter 2: shipping/delivery

Has the words:

```
from:(@ups.com OR @fedex.com OR @usps.gov OR @usps.com OR @informeddelivery.usps.com OR @dhl.com) AND
subject:("Ship Notification" OR "Shipment" OR "Tracking" OR "Tracking Number" OR "Tracking #" OR "Delivery" OR "Delivery Notice" OR "Delivery Exception" OR "Attempted Delivery" OR "Delivery Attempted" OR "Delivery Failed" OR "Address Issue" OR "Delivery Confirmation" OR "Delivered" OR "Delivery Delayed" OR "Shipment Delayed" OR "Out for Delivery" OR "Informed Delivery" OR "Daily Digest" OR "Digest" OR "Package Update" OR "Delivery Update" OR "Out for Delivery Today" OR "Arriving Today" OR "Scheduled Delivery" OR "Expected Delivery" OR "On the Way" OR "Your Package" OR "Your Shipment" OR "Your Delivery")
```

Categorize as: **Updates**
